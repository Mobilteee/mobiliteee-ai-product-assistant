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
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
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


# ---- P4 demo hardening: rate limits + preset answer cache ---------------------

RATE_LIMIT_MSG = (
    "当前 Demo 体验频次已达上限，建议稍后再试或在右上角配置您的专属 API Key 解锁无限调用。"
)
# Recommended starters kept in sync with the frontend (zh + en). Demo requests
# that exactly match one are served from the preset cache; arbitrary questions
# ("自定义提问") are what the per-IP hourly cap applies to.
DEFAULT_PRESET_STARTERS = [
    "电商客服 PRD 中设定的分块策略与元数据字段有哪些？",
    "传统客服与 RAG 智能客服的核心差异与业务收益？",
    "PRD 风险审查：请评估当前客服系统的降级兜底方案",
    "What chunking strategy and metadata fields does the e-commerce PRD define?",
    "What are the key differences and business gains of RAG customer service vs traditional chatbot?",
    "PRD risk review: evaluate the fallback/refusal design of this customer service system",
]

# Hand-authored static answers for the recommended starters. These back the
# demo cache so preset questions never depend on startup API calls and never
# consume LLM tokens. Keyed by the raw starter text; looked up via the same
# normalized key as the runtime cache.
_PRD_SOURCE = {
    "source": "电商智能客服RAG系统_PRD.md #1",
    "excerpt": "按语义段落进行切块，Chunk Size 设置为 600 tokens，Overlap 为 120 tokens。",
    "score": 0.97,
}
_KB_SOURCE = {
    "source": "AI产品岗高频面试知识库.md #1",
    "excerpt": "RAG：检索增强生成，先检索相关知识再生成回复。",
    "score": 0.92,
}

PRESET_STATIC_RESPONSES = {
    "电商客服 PRD 中设定的分块策略与元数据字段有哪些？": {
        "text": (
            "# 分块策略与元数据字段\n\n"
            "**分块策略**（电商智能客服 RAG 系统 PRD v1.2）：\n"
            "- 按**语义段落**进行切块，Chunk Size = **600 tokens**，Overlap = **120 tokens**；\n"
            "- 支持格式：PDF（店铺售后政策）、Word/MD（商品详情与规约）。\n\n"
            "**入库元数据字段**（每条 chunk 必须携带）：店铺 ID、类目 ID、文档发布时间、生效状态（有效/作废）。\n\n"
            "> 检索阶段执行「意图初筛 → 向量 + BM25 双路召回 → BGE-Reranker 精排取 Top-3」"
        ),
        "sources": [_PRD_SOURCE],
    },
    "传统客服与 RAG 智能客服的核心差异与业务收益？": {
        "text": (
            "# 传统客服 vs RAG 智能客服\n\n"
            "**本质差异**\n"
            "- 传统规则型 Chatbot：依赖「关键词 + 预设规则 + 决策树路由」，机械应答，**无法理解长尾复杂售后、无法关联订单与退换货数据**；\n"
            "- RAG 智能客服：先**检索企业知识库**（向量 + BM25），再把命中的原文切片作为上下文交给大模型生成，答案**可溯源**。\n\n"
            "**业务收益**（PRD v1.2 目标）\n"
            "- 降低人工分流：将售前 / 退换货咨询的**人工转接率降低 40%**；\n"
            "- 体验指标：**TTFT ≤ 800ms**、单轮问题解决率 ≥ **75%**；\n"
            "- 知识准确：RAG 检索 **Top-3 准确率 ≥ 88%**。\n\n"
            "**为什么用 RAG 而非微调**（面试知识库）：无需对模型高频微调，直接外挂动态企业知识，降成本、可追溯、易做权限隔离。"
        ),
        "sources": [_PRD_SOURCE, _KB_SOURCE],
    },
    "PRD 风险审查：请评估当前客服系统的降级兜底方案": {
        "text": (
            "# PRD 风险审查：降级兜底方案评估\n\n"
            "**结论**：兜底链路设计较完整，主风险集中在「阈值口径单一」与「缺少人工闭环指标」，建议补充监控。\n\n"
            "**已有防线**\n"
            "1. **拒答兜底**：重排后最高置信度 **< 0.35** 时禁止大模型强答，统一返回“很抱歉…正在为您转接人工”，避免幻觉；\n"
            "2. **边界风控**：涉及退款金额 / 价格争议，**强制调用底层结算 API** 查询真实订单，禁止模型虚构优惠金额；\n"
            "3. **重排过滤**：BGE-Reranker 过滤 **得分 < 0.4** 的片段，控制送入 LLM 的上下文质量。\n\n"
            "**建议补强**\n"
            "- 兜底仅看单一“融合置信度”，建议增加**意图路由 + 拒答归因埋点**（哪些 query 常被拒/常错）；\n"
            "- 为“转人工”建立**解决率与满意度回环**，量化降级对体验的实际影响；\n"
            "- 置信度阈值建议按类目（法规 / 价格争议）差异化配置。"
        ),
        "sources": [_PRD_SOURCE],
    },
    "What chunking strategy and metadata fields does the e-commerce PRD define?": {
        "text": (
            "# Chunking strategy & metadata fields\n\n"
            "The e-commerce RAG PRD (v1.2) defines:\n"
            "- **Chunking**: split by **semantic paragraphs**, Chunk Size = **600 tokens**, Overlap = **120 tokens**;\n"
            "- **Formats**: PDF (after-sales policy), Word/MD (product specs & rules).\n\n"
            "**Metadata every chunk must carry**: store ID, category ID, publish time, effective status (valid / void).\n\n"
            "Retrieval runs: intent pre-screen → dual recall (vector + BM25) → BGE-Reranker top-3."
        ),
        "sources": [_PRD_SOURCE],
    },
    "What are the key differences and business gains of RAG customer service vs traditional chatbot?": {
        "text": (
            "# Traditional chatbot vs RAG customer service\n\n"
            "**Core difference**\n"
            "- Rule-based chatbots match keywords against hand-coded rules; they can't handle long-tail, complex after-sales or join order/refund data;\n"
            "- RAG grounds generation in retrieved knowledge chunks, so every answer is traceable.\n\n"
            "**Business gains (PRD targets)**\n"
            "- Lower manual hand-off rate for pre-sales / refund consultations by **40%**;\n"
            "- **TTFT ≤ 800ms**, one-turn resolution ≥ **75%**;\n"
            "- Retrieval **Top-3 accuracy ≥ 88%**.\n\n"
            "Why RAG over fine-tuning: no frequent retraining, plug-in dynamic knowledge, lower cost, traceable citations."
        ),
        "sources": [_PRD_SOURCE, _KB_SOURCE],
    },
    "PRD risk review: evaluate the fallback/refusal design of this customer service system": {
        "text": (
            "# PRD risk review: fallback / refusal design\n\n"
            "**Verdict**: the fallback chain is solid; the main risks are a single confidence-threshold gate and no closed-loop metrics after hand-off.\n\n"
            "**Existing guards**\n"
            "1. **Refusal**: post-rerank confidence < **0.35** → the model must not answer and replies “Sorry, no matching rule; transferring to an agent.”\n"
            "2. **Boundary risk**: refund / price disputes **force a call to the settlement API**; the model never invents discounts.\n"
            "3. **Rerank filter**: candidates scoring < **0.4** are dropped before LLM context.\n\n"
            "**Suggested hardening**: add intent routing + refusal-attribution telemetry, close the loop on agent resolution/satisfaction, and make the threshold per-category configurable."
        ),
        "sources": [_PRD_SOURCE],
    },
}

# In-memory rolling windows (ephemeral per process; fine for a demo).
_llm_calls: list[float] = []  # demo LLM calls, shared globally, per minute
_ip_calls: dict[str, list[float]] = {}  # per-IP demo LLM calls, per hour
_preset_cache: dict[str, dict] = {}  # normalized question -> {"text":..., "sources":[...]}


def _rl_limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except Exception:
        return default


def _trim(records: list[float], period: float, now: float) -> None:
    records[:] = [t for t in records if t > now - period]


def _window_allowed(records: list[float], limit: int, period: float, now: float) -> bool:
    _trim(records, period, now)
    return len(records) < limit


def _record_now(records: list[float], now: float) -> None:
    records.append(now)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip() or "unknown"
    return (request.client.host if request.client else "unknown") or "unknown"


def _normalize_question(q: str) -> str:
    return " ".join(str(q).split())


def _preset_cache_key(question: str) -> str:
    return _normalize_question(question)


# Seed the demo cache from the hand-authored static responses so preset
# questions never depend on startup API calls and never stay empty.
_preset_cache.update({
    _preset_cache_key(q): {"text": v["text"], "sources": v.get("sources", [])}
    for q, v in PRESET_STATIC_RESPONSES.items()
})


def _is_recommended_starter(question: str) -> bool:
    q = _normalize_question(question)
    return any(_normalize_question(s) == q for s in DEFAULT_PRESET_STARTERS)


def _demo_cfg() -> tuple:
    key = os.getenv("DEMO_CHAT_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base = os.getenv("DEMO_CHAT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""
    model = os.getenv("DEMO_CHAT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    return key, base, model


def _chat_cfg(data: dict, header_key: str = "") -> tuple:
    """Resolve chat credentials with BYOK-first, .env demo fallback.

    A real custom key (from the X-Custom-Api-Key header or the request body)
    wins and bypasses the demo rate limits — the caller pays for their own LLM
    usage. Otherwise we fall back to the system demo key, which is rate limited.
    """
    user_key = _real_key(header_key) or _real_key(data.get("api_key"))
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
    language = data.get("language")  # optional "zh"/"en"; else inferred from the question
    if strategy not in RETRIEVAL_STRATEGIES:
        strategy = os.getenv("RETRIEVAL_STRATEGY", DEFAULT_STRATEGY)
    if preset not in PROMPT_TEMPLATES:
        preset = None

    kb = load_kb(data_dir, user_id, doc_ids=doc_ids)

    history = data.get("history") or []

    header_key = request.headers.get("x-custom-api-key", "")
    custom_key = _real_key(header_key) or _real_key(data.get("api_key"))
    api_key, base_url, model = _chat_cfg(data, header_key)
    demo = not bool(custom_key)

    # Preset exact-hit cache: demo (no custom key) requests that match a cached
    # recommended question are served without touching the LLM.
    preset_cache_key = _preset_cache_key(question)
    cache_entry = None
    if demo:
        _entry = _preset_cache.get(preset_cache_key)
        # Never treat an empty cached answer as a valid hit — fall through to LLM.
        if _entry and (_entry.get("text") or "").strip():
            cache_entry = _entry

    # Rate limits only guard the shared demo key (BYOK users pay their own way).
    if demo and cache_entry is None:
        now = time.time()
        client_ip = _client_ip(request)
        ip_records = _ip_calls.setdefault(client_ip, [])
        # Per-IP hourly cap targets arbitrary ("自定义") questions, not starters.
        if not _is_recommended_starter(question) and not _window_allowed(
            ip_records, _rl_limit("RATE_LIMIT_IP_PER_HOUR", 8), 3600, now
        ):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MSG)
        # Global per-minute cap for every real demo LLM call.
        if not _window_allowed(_llm_calls, _rl_limit("RATE_LIMIT_GLOBAL_PER_MIN", 8), 60, now):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MSG)
        if not _is_recommended_starter(question):
            _record_now(ip_records, now)
        _record_now(_llm_calls, now)

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
            if cache_entry and (cache_entry.get("text") or "").strip():
                # Preset exact-hit: replay the cached answer as SSE, zero LLM tokens.
                cached_sources = cache_entry.get("sources") or []
                assistant_sources = cached_sources
                yield "event: sources\ndata: " + json.dumps(cached_sources, ensure_ascii=False) + "\n\n"
                cached_text = cache_entry.get("text") or ""
                if cached_text:
                    first_token_ms = (time.time() - started) * 1000
                    for i in range(0, len(cached_text), 24):
                        chunk = cached_text[i:i + 24]
                        assistant_text += chunk
                        yield "event: token\ndata: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
                assistant_meta = {
                    "latency_ms": round((time.time() - started) * 1000),
                    "retrieve_ms": 0,
                    "total_tokens": 0,
                    "cached": True,
                }
                yield "event: done\ndata: " + json.dumps(
                    {"total_tokens": 0, "time_ms": round((time.time() - started) * 1000),
                     "retrieve_time_ms": 0.0, "cached": True},
                    ensure_ascii=False,
                ) + "\n\n"
                return

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
                language=language,
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
