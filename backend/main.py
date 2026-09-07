import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from core.rag import (
    PROMPT_TEMPLATES,
    RETRIEVAL_STRATEGIES,
    DEFAULT_STRATEGY,
    add_documents,
    ensure_seed_kb,
    list_documents,
    get_document_content,
    load_kb,
    stream_answer,
)

# In-memory async task store
_tasks: dict[str, dict] = {}
_pool = ThreadPoolExecutor(max_workers=2)


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SEED_DIR = ROOT_DIR / "producttext"
DEFAULT_USER_ID = 1
ALLOWED_SUFFIXES = {".md", ".pdf", ".docx"}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key:
            os.environ[key] = value


_load_dotenv(ROOT_DIR / ".env")
_load_dotenv(Path(__file__).resolve().parent / ".env")

_test_key = os.getenv("DEMO_CHAT_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
print(f"[ENV CHECK] Loaded API Key: {_test_key[:6]}******, Base URL: {os.getenv('OPENAI_BASE_URL')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_result = ensure_seed_kb(DATA_DIR, DEFAULT_USER_ID, SEED_DIR)
    print("seed-kb:", seed_result)
    yield


app = FastAPI(title="AI Product Knowledge Assistant API", lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _db_path() -> Path:
    from core.storage import init_db
    return init_db(DATA_DIR)


def _process_upload_task(task_id: str, data_dir: Path, user_id: int,
                          files: list, category: str,
                          embed_model: str, embed_api_key: str,
                          embed_base_url: str) -> None:
    """Background task: parse files, create chunks, update status."""
    try:
        _tasks[task_id]["status"] = "processing"
        _tasks[task_id]["progress"] = "Parsing documents..."
        result = add_documents(
            data_dir, user_id, files,
            category=category,
            embed_model=embed_model,
            embed_api_key=embed_api_key,
            embed_base_url=embed_base_url,
        )
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["result"] = result
        _tasks[task_id]["progress"] = f"Ready: {result['total_chunks']} chunks"
    except Exception as exc:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(exc)
        _tasks[task_id]["progress"] = f"Failed: {exc}"


def _real_key(value) -> str:
    """Return a usable API key, or '' for empty / placeholder values."""
    v = (value or "").strip()
    if not v or len(v) < 8:
        return ""
    low = v.lower()
    if low.startswith(("your-", "sk-your", "sk-xxx")) or low in {"changeme", "demo", "..."}:
        return ""
    if set(v) <= {"*"}:
        return ""
    return v


def _chat_cfg(data: dict) -> tuple:
    """Resolve chat credentials with BYOK-first, .env demo fallback.

    A real user-supplied key is authoritative: it runs against the user's own
    base_url (default OpenAI when none given) so it is never silently pointed at
    the demo gateway. Only when the user key is empty/placeholder do we use the
    system .env demo credentials. If a supplied key later fails (401/403/bad
    model), core.rag._chat_create retries once against the .env demo channel.
    """
    user_key = _real_key(data.get("api_key"))
    if user_key:
        base_url = (data.get("base_url") or "").strip()
        model = (data.get("model") or "").strip() or "gpt-4o-mini"
        return user_key, base_url, model
    api_key = os.getenv("DEMO_CHAT_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = os.getenv("DEMO_CHAT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""
    model = os.getenv("DEMO_CHAT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    return api_key, base_url, model


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/documents")
async def documents(user_id: int = DEFAULT_USER_ID):
    return list_documents(DATA_DIR, user_id)


@app.get("/documents/categories")
async def document_categories(user_id: int = DEFAULT_USER_ID):
    """Return all topic categories with the documents under each (scope filter UI)."""
    from core import storage as storage_mod

    docs = storage_mod.list_documents_by_user(_db_path(), user_id)
    grouped: dict[str, list] = {}
    for d in docs:
        grouped.setdefault(d.get("category") or "default", []).append(d)
    return {
        "categories": [
            {"category": c, "documents": items}
            for c, items in sorted(grouped.items())
        ],
        "total": len(docs),
    }


@app.get("/documents/{doc_id}/content")
async def document_content(doc_id: int, user_id: int = DEFAULT_USER_ID):
    """Return reconstructed full text of a document for the viewer."""
    try:
        return get_document_content(DATA_DIR, user_id, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/documents/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    user_id: int = DEFAULT_USER_ID,
    category: str = Form("default"),
):
    """Upload documents — returns task_id immediately, processes in background."""
    parsed_files = []
    for uploaded in files:
        suffix = Path(uploaded.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {uploaded.filename}")
        raw = await uploaded.read()
        parsed_files.append((uploaded.filename, raw))
    if not parsed_files:
        raise HTTPException(status_code=400, detail="No files provided")
    category = (category or "default").strip() or "default"

    task_id = str(uuid.uuid4())
    _tasks[task_id] = {"status": "pending", "progress": "Queued..."}

    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _pool,
        _process_upload_task,
        task_id, DATA_DIR, user_id, parsed_files, category,
        _env("DEMO_EMBED_MODEL"), _env("DEMO_EMBED_API_KEY"), _env("DEMO_EMBED_BASE_URL"),
    )

    return {"status": "accepted", "task_id": task_id}


@app.get("/documents/task/{task_id}")
async def get_task_status(task_id: str):
    """Poll upload task status."""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/retrieval/config")
async def retrieval_config():
    """Return available retrieval strategies and prompt templates."""
    return {
        "strategies": list(RETRIEVAL_STRATEGIES),
        "default_strategy": os.getenv("RETRIEVAL_STRATEGY", DEFAULT_STRATEGY),
        "presets": [
            {"id": key, "label": value["label"], "placeholder": value["placeholder"]}
            for key, value in PROMPT_TEMPLATES.items()
        ],
    }


@app.get("/metrics/overview")
async def metrics_overview(user_id: int = DEFAULT_USER_ID):
    """Aggregate feedback, query metrics, and eval results for the dashboard."""
    from core import storage as storage_mod

    overview = storage_mod.metrics_overview(_db_path(), user_id)
    eval_file = ROOT_DIR / "evals" / "EVAL_RESULTS.json"
    if eval_file.exists():
        overview["eval_results"] = json.loads(eval_file.read_text(encoding="utf-8"))
    else:
        overview["eval_results"] = None
    return overview


@app.post("/feedback")
async def submit_feedback(request: Request):
    """Record 👍/👎 feedback with optional attribution reasons."""
    from core import storage as storage_mod

    data = await request.json()
    user_id = int(data.get("user_id", DEFAULT_USER_ID))
    thumbs = int(data.get("thumbs", 1))
    reasons = data.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = []
    feedback_id = storage_mod.add_feedback(
        _db_path(),
        user_id,
        thumbs,
        question=str(data.get("question", "")),
        answer_excerpt=str(data.get("answer_excerpt", ""))[:500],
        reasons=reasons,
        conversation_id=data.get("conversation_id"),
    )
    return {"status": "ok", "id": feedback_id}


@app.get("/conversations")
async def list_user_conversations(user_id: int = DEFAULT_USER_ID):
    """Return current user's conversations, newest first."""
    from core import storage as storage_mod
    return {"conversations": storage_mod.list_conversations(_db_path(), user_id)}


@app.post("/conversations")
async def create_conversation(request: Request):
    from core import storage as storage_mod
    data = await request.json()
    user_id = int(data.get("user_id", DEFAULT_USER_ID))
    title = str(data.get("title") or "").strip() or "新的会话"
    conv_id = storage_mod.create_conversation(_db_path(), user_id, title)
    return {"status": "ok", "conversation_id": conv_id, "title": title}


@app.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: int, user_id: int = DEFAULT_USER_ID):
    from core import storage as storage_mod
    convs = storage_mod.list_conversations(_db_path(), user_id)
    if not any(c["id"] == conversation_id for c in convs):
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = storage_mod.list_messages(_db_path(), conversation_id)
    return {"conversation_id": conversation_id, "messages": messages}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, user_id: int = DEFAULT_USER_ID):
    from core import storage as storage_mod
    convs = storage_mod.list_conversations(_db_path(), user_id)
    if not any(c["id"] == conversation_id for c in convs):
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage_mod.delete_conversation(_db_path(), conversation_id)
    return {"status": "ok", "deleted": conversation_id}


@app.post("/query")
async def query(request: Request):
    from core import storage as storage_mod

    data = await request.json()
    question = data.get("question", "")
    if not question.strip():
        return {"error": "question is required"}

    data_dir = Path(data.get("data_dir", DATA_DIR))
    user_id = int(data.get("user_id", DEFAULT_USER_ID))
    doc_ids = data.get("doc_ids")  # optional list[int] for document filtering
    raw_categories = data.get("categories")  # optional list[str] topic-scope filter
    categories = [c for c in (raw_categories or []) if isinstance(c, str) and c.strip()] or None
    strategy = data.get("strategy") or os.getenv("RETRIEVAL_STRATEGY", DEFAULT_STRATEGY)
    preset = data.get("preset")
    if strategy not in RETRIEVAL_STRATEGIES:
        strategy = os.getenv("RETRIEVAL_STRATEGY", DEFAULT_STRATEGY)
    if preset not in PROMPT_TEMPLATES:
        preset = None

    kb = load_kb(data_dir, user_id, doc_ids=doc_ids)

    history = data.get("history") or []
    api_key, base_url, model = _chat_cfg(data)
    embed_model = _env("DEMO_EMBED_MODEL")
    embed_api_key = _env("DEMO_EMBED_API_KEY")
    embed_base_url = _env("DEMO_EMBED_BASE_URL")

    # Session persistence: use provided conversation or create one automatically.
    db_path = _db_path()
    conversation_id = data.get("conversation_id")
    clean_question = " ".join(str(question).split())
    auto_title = (clean_question[:15] or "新会话") + ("…" if len(clean_question) > 15 else "")
    default_titles = {"newSession", "New Conversation", "新的会话", "New Chat", ""}
    needs_title_update = False
    if conversation_id:
        conversation_id = int(conversation_id)
        known = storage_mod.list_conversations(db_path, user_id)
        match = next((c for c in known if c["id"] == conversation_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if match["message_count"] == 0 or str(match["title"]).strip() in default_titles:
            needs_title_update = True
    else:
        conversation_id = storage_mod.create_conversation(db_path, user_id, auto_title)
    storage_mod.add_message(db_path, conversation_id, "user", question)
    async def event_stream():
        started = time.time()
        first_token_ms = None
        retrieve_ms = 0.0
        total_tokens = 0
        refusal = 0
        assistant_text = ""
        assistant_sources = []
        assistant_meta = {}

        # Tell the frontend which conversation this answer belongs to.
        yield "event: conversation\ndata: " + json.dumps(
            {"conversation_id": conversation_id}, ensure_ascii=False
        ) + "\n\n"

        try:
            for event in stream_answer(
                api_key,
                question,
                kb,
                history=history,
                base_url=base_url,
                model=model,
                embed_model=embed_model,
                embed_api_key=embed_api_key,
                embed_base_url=embed_base_url,
                strategy=strategy,
                preset=preset,
                categories=categories,
                doc_ids=doc_ids,
            ):
                event_type = event["event"]
                if event_type == "token":
                    if first_token_ms is None:
                        first_token_ms = (time.time() - started) * 1000
                    assistant_text += event["data"]
                elif event_type == "sources":
                    try:
                        assistant_sources = json.loads(event["data"])
                    except Exception:
                        assistant_sources = []
                elif event_type == "done":
                    try:
                        stats = json.loads(event["data"])
                        total_tokens = int(stats.get("total_tokens") or 0)
                        retrieve_ms = float(stats.get("retrieve_time_ms") or 0)
                        assistant_meta = {
                            "latency_ms": stats.get("time_ms"),
                            "retrieve_ms": stats.get("retrieve_time_ms"),
                            "total_tokens": stats.get("total_tokens"),
                        }
                    except Exception:
                        pass
                elif event_type == "refusal":
                    refusal = 1
                    try:
                        parsed = json.loads(event["data"])
                        assistant_text = parsed.get("message") or event["data"]
                    except Exception:
                        assistant_text = event["data"]
                elif event_type == "error":
                    assistant_text = assistant_text or ("Error: " + event["data"])

                if event_type == "token":
                    # Wrap the raw token in JSON so leading/trailing spaces and
                    # newlines survive SSE framing intact (a plain text value
                    # would lose its leading space to the "data: " glue and any
                    # literal newline would be treated as an SSE frame boundary).
                    wire_data = json.dumps(event["data"], ensure_ascii=False)
                else:
                    wire_data = event["data"]
                yield "event: {0}\ndata: {1}\n\n".format(event_type, wire_data)
        finally:
            # Persist the assistant turn + telemetry after streaming ends.
            try:
                if assistant_text:
                    storage_mod.add_message(
                        db_path,
                        conversation_id,
                        "assistant",
                        assistant_text,
                        sources=assistant_sources,
                        latency_meta=assistant_meta,
                    )
                storage_mod.touch_conversation(db_path, conversation_id)
                if needs_title_update:
                    storage_mod.update_conversation_title(db_path, conversation_id, auto_title)
                storage_mod.add_query_metric(
                    db_path,
                    user_id,
                    conversation_id=conversation_id,
                    question=str(question)[:500],
                    strategy=strategy,
                    preset=preset or "",
                    refusal=refusal,
                    total_tokens=total_tokens,
                    retrieve_ms=retrieve_ms,
                    first_token_ms=first_token_ms or 0.0,
                    total_ms=(time.time() - started) * 1000,
                )
            except Exception:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
