import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI

# text-embedding-3-small is a multilingual model: an English question is embedded
# and can still match Chinese chunks directly, so cross-lingual vector recall needs
# no translation. Query translation (below) is only a rescue, run after a first
# retrieval comes back empty/weak for a non-Chinese question.
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"

# ---- Credential resolution: BYOK first, automatic .env demo fallback ----------

_DEFAULT_CHAT_KEY_ENV = ("DEMO_CHAT_API_KEY", "OPENAI_API_KEY")
_DEFAULT_CHAT_BASE_ENV = ("DEMO_CHAT_BASE_URL", "OPENAI_BASE_URL")
_DEFAULT_CHAT_MODEL_ENV = ("DEMO_CHAT_MODEL", "OPENAI_MODEL")


def _clean_key(value: str) -> str:
    """Return a usable API key or '' for empty / placeholder values."""
    key = (value or "").strip()
    if not key or len(key) < 8:
        return ""
    low = key.lower()
    if low in {"your-api-key", "sk-your-api-key", "sk-your-key", "changeme", "replacethis", "demo", "..."}:
        return ""
    if low.startswith("your-") or low.startswith("sk-your") or low.startswith("sk-xxx"):
        return ""
    if set(key) <= {"*"}:
        return ""
    return key


def _env_value(names, default: str = "") -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


def _env_chat_cfg() -> tuple:
    key = _clean_key(_env_value(_DEFAULT_CHAT_KEY_ENV))
    base = _env_value(_DEFAULT_CHAT_BASE_ENV)
    model = _env_value(_DEFAULT_CHAT_MODEL_ENV) or DEFAULT_CHAT_MODEL
    return key, base, model


def _cred_or_model_error(exc: Exception) -> bool:
    """True for gateway errors that a different credential set can fix (401/403/bad model)."""
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return True
    if name == "BadRequestError":
        msg = str(exc).lower()
        return ("api key" in msg or "authorization" in msg or "model" in msg
                or "you passed" in msg or "invalid" in msg and "request" not in msg)
    return False


def _chat_create(messages: list[dict], api_key: str = "", base_url: str = "",
                 model: str = DEFAULT_CHAT_MODEL, *, stream: bool = False,
                 temperature: float = 0.2, max_tokens: int | None = None):
    """Create a chat completion with automatic .env demo fallback.

    A real user-supplied key is tried first. If it is empty/placeholder, or the
    gateway rejects it (401/403/unsupported model), the call is retried once with
    the system .env credentials. The happy path stays a single call.
    """
    env_key, env_base, env_model = _env_chat_cfg()
    api_key = _clean_key(api_key)
    base_url = (base_url or "").strip()
    if not api_key:
        api_key, base_url, model = env_key, env_base or base_url, env_model

    def _call(key: str, b_url: str, mdl: str):
        kwargs: dict = dict(model=mdl, messages=messages, temperature=temperature, stream=stream)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        return _client(key, b_url).chat.completions.create(**kwargs)

    try:
        return _call(api_key, base_url, model)
    except Exception as exc:
        if env_key and env_key != api_key and _cred_or_model_error(exc):
            return _call(env_key, env_base or base_url, env_model)
        raise

# ---- P2 retrieval config -------------------------------------------------
DEFAULT_PARENT_CHUNK_SIZE = 1500
DEFAULT_CHILD_CHUNK_SIZE = 300
DEFAULT_CHUNK_OVERLAP = 60
RRF_K = 60
DEFAULT_REFUSAL_THRESHOLD = 0.10

STRATEGY_NAIVE = "naive"
STRATEGY_HYBRID = "hybrid"
STRATEGY_PARENT_CHILD = "hybrid_parent_child"
RETRIEVAL_STRATEGIES = (STRATEGY_NAIVE, STRATEGY_HYBRID, STRATEGY_PARENT_CHILD)
DEFAULT_STRATEGY = STRATEGY_PARENT_CHILD

PROMPT_TEMPLATES = {
    "prd_review": {
        "label": "PRD risk review",
        "placeholder": "e.g., What is the biggest delivery risk in this PRD?",
        "system": (
            "You are a senior AI product manager doing PRD risk review. "
            "Strictly base your analysis on the references. For each point, "
            "identify requirement gaps, technical risks, business risks, and deployment omissions. "
            "Cite [Source N]. Clearly state when information is not covered."
        ),
    },
    "competitor_gap": {
        "label": "Competitor gap analysis",
        "placeholder": "e.g., Compare this solution with mainstream competitors",
        "system": (
            "You are a senior AI product analyst. Based on the references, "
            "perform a competitor gap analysis structured into: capability comparison, "
            "UX gaps, data metric gaps, and priority recommendations. "
            "Cite [Source N]. Only use information from the provided references."
        ),
    },
    "interview_quiz": {
        "label": "Interview follow-ups",
        "placeholder": "e.g., Generate 10 deep follow-up questions from this PRD",
        "system": (
            "You are a senior AI product interview coach. Based on the references, "
            "generate insightful follow-up questions with high-discrimination answer keys. "
            "Cite [Source N]. Prioritize questions about retrieval, cost, evaluation metrics, and edge cases."
        ),
    },
}


def _client(api_key: str, base_url: str = "") -> OpenAI:
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


# ---- Text extraction -------------------------------------------------------


def extract_text(file_bytes: bytes, file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(file_bytes)
    if suffix == ".docx":
        return _extract_docx(file_bytes)
    return _extract_plain(file_bytes)


def _extract_pdf(file_bytes: bytes) -> str:
    from io import BytesIO
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _extract_docx(file_bytes: bytes) -> str:
    from io import BytesIO
    from docx import Document

    doc = Document(BytesIO(file_bytes))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(lines)


def _extract_plain(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("gbk", errors="ignore")


# ---- Chunking (flat + parent-child tree) ------------------------------------


def _clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_sections(text: str) -> list[str]:
    if not text:
        return []
    sections = re.split(r"(?m)^#{1,3}\s+.*$|\n\n", _clean_text(text))
    return [s.strip() for s in sections if s.strip()]


def _pack_sections(sections: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    buffer = ""
    for section in sections:
        while len(section) > chunk_size:
            cut = section[:chunk_size]
            if buffer:
                chunks.append((buffer + "\n" + cut).strip())
                buffer = cut[-overlap:] if overlap else ""
            else:
                chunks.append(cut.strip())
                buffer = cut[-overlap:] if overlap else ""
            section = section[chunk_size:]
        if buffer:
            if len(buffer) + len(section) <= chunk_size:
                buffer = buffer + "\n" + section
                continue
            chunks.append(buffer.strip())
        buffer = section
    if buffer.strip():
        chunks.append(buffer.strip())
    return [c for c in chunks if len(c.strip()) > 40]


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    return _pack_sections(_split_sections(text), chunk_size, overlap)


def split_doc_tree(
    text: str,
    parent_size: int = DEFAULT_PARENT_CHUNK_SIZE,
    child_size: int = DEFAULT_CHILD_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict]:
    parents = _pack_sections(_split_sections(text), parent_size, overlap)
    tree: list[dict] = []
    for seq, parent in enumerate(parents, 1):
        children = _pack_sections(_split_sections(parent), child_size, overlap)
        if not children:
            continue
        tree.append({"seq": seq, "parent": parent, "children": children})
    return tree


# ---- Embeddings -------------------------------------------------------------


def embed_texts(
    api_key: str,
    texts: list[str],
    base_url: str = "",
    model: str = DEFAULT_EMBED_MODEL,
) -> list[list[float]]:
    client = _client(api_key, base_url)
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def _embed_tree(tree: list[dict], embed_api_key: str, embed_model: str, embed_base_url: str) -> bool:
    texts: list[str] = []
    for item in tree:
        texts.append(item["parent"])
        texts.extend(item["children"])
    try:
        vectors = embed_texts(embed_api_key, texts, embed_base_url, embed_model)
    except Exception:
        return False
    idx = 0
    for item in tree:
        item["embedding"] = vectors[idx]
        idx += 1
        for child_text in item["children"]:
            child_entry = item.setdefault("_children_data", [])
            child_entry.append({"text": child_text, "embedding": vectors[idx]})
            idx += 1
    return True


# ---- Knowledge-base load / document ingest -----------------------------------


def save_kb(
    data_dir: Path,
    user_id: int,
    api_key: str,
    files: Iterable[Any],
    base_url: str = "",
    embed_model: str = "",
    embed_api_key: str = "",
    embed_base_url: str = "",
):
    doc_list = []
    for uploaded in files:
        raw_bytes = uploaded.getvalue()
        doc_list.append((uploaded.name, raw_bytes))
    if not doc_list:
        raise ValueError("No files provided")
    result = add_documents(
        data_dir,
        user_id,
        doc_list,
        embed_model=embed_model,
        embed_api_key=embed_api_key,
        embed_base_url=embed_base_url,
    )
    return result["total_chunks"], result["mode"]


def _legacy_kb_payload(kb_file: Path) -> dict:
    payload = json.loads(kb_file.read_text(encoding="utf-8"))
    payload.setdefault("mode", "keyword")
    payload.setdefault("chunks", [])
    return payload


def _chunk_from_db_row(r: dict, parent_by_id: dict) -> dict:
    filename = r["filename"]
    if r["parent_id"] is None:
        return {
            "id": r["id"],
            "doc_id": r["doc_id"],
            "parent_id": None,
            "seq": r["seq"],
            "filename": filename,
            "category": r.get("category") or "default",
            "source": f"{filename} #{r['seq']}",
            "text": r["text"],
            "parent_text": r["text"],
            "embedding": r.get("embedding"),
            "is_parent": True,
        }
    parent = parent_by_id.get(r["parent_id"]) or {}
    parent_text = parent.get("text") or r["text"]
    parent_seq = parent.get("seq") or 0
    return {
        "id": r["id"],
        "doc_id": r["doc_id"],
        "parent_id": r["parent_id"],
        "seq": r["seq"],
        "filename": filename,
        "category": r.get("category") or "default",
        "source": f"{filename} #{parent_seq}.{r['seq']}",
        "text": r["text"],
        "parent_text": parent_text,
        "embedding": r.get("embedding"),
        "is_parent": False,
    }


def load_kb(data_dir: Path, user_id: int, doc_ids: list[int] | None = None) -> dict:
    from core.storage import get_all_chunks_for_user

    db_path = data_dir / "app.db"
    legacy_file = data_dir / "users" / str(user_id) / "kb.json"
    if not db_path.exists():
        if legacy_file.exists():
            return _legacy_kb_payload(legacy_file)
        return {"mode": "keyword", "chunks": []}

    try:
        rows = get_all_chunks_for_user(db_path, user_id)
        if not rows:
            return {"mode": "keyword", "chunks": []}

        parent_by_id = {r["id"]: r for r in rows if r["parent_id"] is None}
        chunks = [_chunk_from_db_row(r, parent_by_id) for r in rows]
        has_any_embedding = any(r.get("embedding") for r in rows)
        mode = "vector" if has_any_embedding else "keyword"
        if doc_ids is not None:
            chunks = [c for c in chunks if c.get("doc_id") in doc_ids]
        return {"mode": mode, "strategy": DEFAULT_STRATEGY, "chunks": chunks}
    except Exception:
        if legacy_file.exists():
            return _legacy_kb_payload(legacy_file)
        return {"mode": "keyword", "chunks": []}


def ensure_seed_kb(data_dir: Path, user_id: int, source_dir: Path) -> dict:
    from core.storage import get_all_chunks_for_user, init_db

    db_path = init_db(data_dir)
    try:
        existing = get_all_chunks_for_user(db_path, user_id)
        if existing:
            has_embedding = any(r.get("embedding") for r in existing)
            leaf_count = sum(1 for r in existing if r["parent_id"] is not None) or len(existing)
            return {"status": "skipped", "mode": "vector" if has_embedding else "keyword", "total_chunks": leaf_count}
    except Exception:
        pass
    documents = [
        (file_path.name, file_path.read_bytes())
        for file_path in sorted(source_dir.glob("*.md"))
        if file_path.is_file()
    ]
    if not documents:
        return {"status": "no-source-docs", "mode": "keyword", "total_chunks": 0}
    result = add_documents(data_dir, user_id, documents)
    return {"status": "seeded", "mode": result["mode"], "total_chunks": result["total_chunks"]}


def add_documents(
    data_dir: Path,
    user_id: int,
    documents: list,
    embed_model: str = "",
    embed_api_key: str = "",
    embed_base_url: str = "",
    category: str = "default",
    strategy: str = DEFAULT_STRATEGY,
) -> dict:
    from core.storage import (
        create_document,
        delete_documents_by_filename,
        init_db,
        insert_chunk_tree,
        update_document_status,
    )

    db_path = init_db(data_dir)
    uploaded_names = []
    parent_total = 0
    child_total = 0
    mode = "keyword"

    for file_name, raw_bytes in documents:
        uploaded_names.append(file_name)
        tree = split_doc_tree(extract_text(raw_bytes, file_name))
        if not tree:
            continue

        insert_tree = []
        all_texts: list[str] = []
        for item in tree:
            parent_row = {"seq": item["seq"], "text": item["parent"], "embedding": None, "children": []}
            for child_text in item["children"]:
                parent_row["children"].append({"text": child_text, "embedding": None})
            insert_tree.append(parent_row)
            all_texts.append(parent_row["text"])
            all_texts.extend(child["text"] for child in parent_row["children"])

        delete_documents_by_filename(db_path, user_id, file_name)
        doc_id = create_document(db_path, user_id, file_name, category=category)

        if embed_model and embed_api_key:
            try:
                vectors = embed_texts(embed_api_key, all_texts, embed_base_url, embed_model)
                vec_idx = 0
                for parent_row in insert_tree:
                    parent_row["embedding"] = vectors[vec_idx]
                    vec_idx += 1
                    for child in parent_row["children"]:
                        child["embedding"] = vectors[vec_idx]
                        vec_idx += 1
                mode = "vector"
            except Exception:
                pass

        insert_chunk_tree(db_path, doc_id, insert_tree)
        doc_children = sum(len(parent_row["children"]) for parent_row in insert_tree)
        update_document_status(db_path, doc_id, "ready", doc_children)
        parent_total += len(insert_tree)
        child_total += doc_children

    if not uploaded_names:
        raise ValueError("No documents could be parsed")

    return {"uploaded": sorted(uploaded_names), "parent_chunks": parent_total, "child_chunks": child_total, "total_chunks": child_total, "mode": mode, "strategy": strategy}


def list_documents(data_dir: Path, user_id: int) -> dict:
    from core.storage import get_all_chunks_for_user, list_documents_by_user

    db_path = data_dir / "app.db"
    if db_path.exists():
        try:
            docs = list_documents_by_user(db_path, user_id)
            all_chunks = get_all_chunks_for_user(db_path, user_id)
            has_any_embedding = any(r.get("embedding") for r in all_chunks)
            mode = "vector" if has_any_embedding else "keyword"
            total_chunks = sum(d["chunk_count"] for d in docs)
            return {"documents": [{"id": d["id"], "filename": d["filename"], "category": d.get("category", "default"), "chunk_count": d["chunk_count"], "status": d["status"], "created_at": d["created_at"]} for d in docs], "total_chunks": total_chunks, "mode": mode}
        except Exception:
            pass
    kb = load_kb(data_dir, user_id)
    grouped: dict = {}
    for chunk in kb["chunks"]:
        doc_name = chunk["source"].rsplit(" #", 1)[0]
        entry = grouped.setdefault(doc_name, {"filename": doc_name, "category": "default", "chunk_count": 0, "status": "ready"})
        entry["chunk_count"] += 1
    return {"documents": sorted(grouped.values(), key=lambda item: item["filename"]), "total_chunks": len(kb["chunks"]), "mode": kb["mode"]}


# ---- Retrieval ----------------------------------------------------------------


def _cosine(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_TOKEN_RE = re.compile(r"([A-Za-z0-9_]+|[\u4e00-\u9fff]+)")


def _tokenize(text: str) -> list[str]:
    tokens = []
    for match in _TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", match):
            tokens.extend(match[i : i + 2] for i in range(max(1, len(match) - 1)))
        else:
            tokens.append(match)
    return tokens


def _overlap_score(query: str, text: str) -> float:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return 0.0
    text_tokens = set(_tokenize(text))
    return len(query_tokens & text_tokens) / len(query_tokens)


def _chunk_context(chunk: dict) -> str:
    return chunk.get("parent_text") or chunk.get("text") or ""


def _hit_from_chunk(chunk: dict, score: float) -> dict:
    context = _chunk_context(chunk)
    own_text = chunk.get("text") or context
    return {
        "source": chunk.get("source") or f"{chunk.get('filename', 'doc')} #{chunk.get('seq', 0)}",
        "text": context,
        "excerpt": own_text,
        "score": round(max(0.0, min(1.0, score)), 4),
        "doc_id": chunk.get("doc_id"),
        "filename": chunk.get("filename"),
        "chunk_id": chunk.get("id"),
        "parent_id": chunk.get("parent_id"),
        "is_parent": chunk.get("is_parent", True),
    }


def _keyword_retrieve(query: str, chunks: list[dict], top_k: int = 4) -> list[dict]:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []
    scored = []
    for chunk in chunks:
        overlap = _overlap_score(query, chunk.get("text") or "")
        if overlap <= 0:
            continue
        scored.append((overlap, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [_hit_from_chunk(c, s) for s, c in scored[:top_k]]


def _bm25_retrieve(query: str, chunks: list[dict], top_k: int = 4, k1: float = 1.5, b: float = 0.75) -> list[dict]:
    tokenized_docs = [_tokenize(c.get("text") or "") for c in chunks]
    total = len(chunks)
    if total == 0:
        return []
    doc_lens = [len(tokens) for tokens in tokenized_docs]
    avgdl = (sum(doc_lens) / total) or 1.0
    df: Counter = Counter()
    for tokens in tokenized_docs:
        for token in set(tokens):
            df[token] += 1

    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    scored = []
    for idx, chunk in enumerate(chunks):
        term_freq = Counter(tokenized_docs[idx])
        doc_len = doc_lens[idx]
        bm25_score = 0.0
        for term in query_tokens:
            freq = term_freq.get(term, 0)
            if freq == 0:
                continue
            doc_freq = df.get(term, 0)
            idf = math.log((total - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
            denom = freq + k1 * (1 - b + b * doc_len / avgdl)
            bm25_score += idf * (freq * (k1 + 1.0)) / denom
        overlap = _overlap_score(query, chunk.get("text") or "")
        if bm25_score > 0 or overlap > 0:
            scored.append((bm25_score, overlap, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [_hit_from_chunk(c, max(overlap, 0.0)) for _, overlap, c in scored[:top_k]]


def _vector_retrieve(api_key: str, chunks: list[dict], query: str, base_url: str, embed_model: str, top_k: int = 4) -> list[dict]:
    query_vector = embed_texts(api_key, [query], base_url, embed_model)[0]
    scored = []
    for chunk in chunks:
        if not chunk.get("embedding"):
            continue
        score = _cosine(query_vector, chunk["embedding"])
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [_hit_from_chunk(c, s) for s, c in scored[:top_k]]


def _rrf_fuse(ranked_lists: list[list[dict]], top_k: int = 4, k: int = RRF_K) -> list[dict]:
    fused: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            key = str(hit.get("chunk_id")) if hit.get("chunk_id") is not None else hit.get("source", "") + str(hit.get("doc_id"))
            entry = fused.setdefault(key, {"hit": hit, "rrf": 0.0, "similarity": hit["score"]})
            entry["rrf"] += 1.0 / (k + rank)
            entry["similarity"] = max(entry["similarity"], hit["score"])
    ordered = sorted(fused.values(), key=lambda item: item["rrf"], reverse=True)[:top_k]
    out = []
    for item in ordered:
        hit = dict(item["hit"])
        hit["score"] = round(item["similarity"], 4)
        hit["rrf_score"] = round(item["rrf"], 6)
        out.append(hit)
    return out


def retrieve(
    query: str,
    kb: dict,
    chat_api_key: str = "",
    chat_base_url: str = "",
    embed_model: str = "",
    embed_api_key: str = "",
    embed_base_url: str = "",
    top_k: int = 4,
    doc_ids: list[int] | None = None,
    categories: list[str] | None = None,
    strategy: str | None = None,
    translated_query: str | None = None,
) -> list[dict]:
    strategy = (strategy or kb.get("strategy") or DEFAULT_STRATEGY).lower()
    if strategy not in RETRIEVAL_STRATEGIES:
        strategy = DEFAULT_STRATEGY

    chunks = kb.get("chunks", [])
    if not chunks:
        return []

    if doc_ids is not None:
        filtered = [c for c in chunks if c.get("doc_id") in doc_ids]
        if filtered:
            chunks = filtered

    # Topic-scope pre-filtering: restrict the candidate pool BEFORE any similarity
    # scoring, so both dense and sparse retrieval rank only inside the requested
    # categories/docs and never leak cross-domain noise.
    if categories:
        catset = set(categories)
        chunks = [c for c in chunks if (c.get("category") or "default") in catset]

    if strategy == STRATEGY_PARENT_CHILD:
        candidates = [c for c in chunks if c.get("is_parent") is False]
        if not candidates:
            candidates = chunks
    else:
        candidates = [c for c in chunks if c.get("is_parent") is not False]
        if not candidates:
            candidates = chunks

    if not candidates:
        return []

    vector_available = bool(embed_model and embed_api_key and any(c.get("embedding") for c in candidates))

    # Cross-lingual RAG: BM25 AND vector both run on the Chinese retrieval query.
    # answer()/stream_answer() rewrite the question before calling retrieve();
    # translated_query lets a direct caller override while keeping `query` original.
    retrieve_query = translated_query or query

    if strategy == STRATEGY_NAIVE:
        if vector_available:
            return _vector_retrieve(embed_api_key, candidates, retrieve_query, embed_base_url, embed_model, top_k)
        return _keyword_retrieve(retrieve_query, candidates, top_k)

    # hybrid or hybrid_parent_child: BM25 + optional vector, fused by RRF
    bm25_hits = _bm25_retrieve(retrieve_query, candidates, top_k=top_k * 2)
    if vector_available:
        vector_hits = _vector_retrieve(embed_api_key, candidates, retrieve_query, embed_base_url, embed_model, top_k * 2)
        return _rrf_fuse([bm25_hits, vector_hits], top_k)
    return bm25_hits[:top_k]


def _refusal_message() -> str:
    return (
        "No relevant information was found in the knowledge base for this question. "
        "You can try rephrasing your question or uploading relevant documents."
    )


# ---- Cross-lingual query translation -----------------------------------------

_LANG_INSTRUCTION = (
    "\n\nIMPORTANT: Please answer in the exact same language as the user's original query. "
    "If the user writes in English, answer in English. If the user writes in Chinese, "
    "answer in Chinese. The language of the references must never override the question's "
    "language: Chinese references do NOT turn an English question into a Chinese answer. "
    "Do not switch or mix languages."
)


def _translate_query_if_needed(
    query: str,
    api_key: str = "",
    base_url: str = "",
    model: str = DEFAULT_CHAT_MODEL,
) -> tuple:
    """Rescue query translation: rewrite a non-Chinese question into Chinese.

    Called only after a retrieval on the original query is empty or below the
    refusal threshold. Chinese questions and every failure short-circuit back to
    the original query, so generation keeps running with a single LLM call.

    Returns:
        (original_query, retrieval_query, was_translated)
    """
    stripped = query.strip()
    if not stripped or _is_mostly_chinese(stripped) or not _translation_rescue_enabled():
        return (query, query, False)
    try:
        resp = _chat_create(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a precise translator. Rewrite the user's question "
                        "into Chinese (Simplified). Output ONLY the rewritten question, "
                        "no explanation, no quotes, no extra characters."
                    ),
                },
                {"role": "user", "content": stripped},
            ],
            api_key=api_key, base_url=base_url, model=model,
            temperature=0.0, max_tokens=256,
        )
        translated = (resp.choices[0].message.content or "").strip()
        if translated and translated != stripped:
            return (query, translated, True)
    except Exception:
        pass
    return (query, query, False)


def _is_mostly_chinese(text: str) -> bool:
    """True when >30% of the text is Han characters (the KB's primary language)."""
    s = text.strip()
    if not s:
        return False
    han = sum(1 for ch in s if "一" <= ch <= "鿿")
    return han / len(s) > 0.30


def _translation_rescue_enabled() -> bool:
    """Off-switch for the lazy translation rescue (default on)."""
    return (os.getenv("QUERY_TRANSLATION", "1").strip().lower()
            not in ("0", "false", "off", "no"))


# Zero-cost language anchor appended to the final user turn: the answer language
# follows the question, not the references. Keeps generation to a single LLM call.
_LANG_ANCHOR = "\n\nPlease answer in English if the user asked in English, or Chinese if asked in Chinese."


# ---- Answer generation ---------------------------------------------------------


def _system_content(preset: str | None = None) -> str:
    if preset and preset in PROMPT_TEMPLATES:
        return PROMPT_TEMPLATES[preset]["system"] + _LANG_INSTRUCTION
    return (
        "You are a senior AI product coach. Answer strictly from the references. "
        "Formatting rules: never stack citations (only cite the most direct single reference per point as [N]); "
        "avoid emoji in normal text; put conclusions in bold, technical fields in backticks, edge conditions in italics; "
        "say clearly when information is not present instead of guessing.\n\n"
        "References are numbered [1], [2], ... in the order provided."
    ) + _LANG_INSTRUCTION


def answer(
    api_key: str,
    question: str,
    kb: dict,
    history: list[dict] | None = None,
    base_url: str = "",
    model: str = DEFAULT_CHAT_MODEL,
    embed_model: str = "",
    embed_api_key: str = "",
    embed_base_url: str = "",
    strategy: str | None = None,
    categories: list[str] | None = None,
    doc_ids: list[int] | None = None,
) -> dict:
    chunks = kb.get("chunks", [])
    if not chunks:
        raise ValueError("Knowledge base is empty. Please upload and parse a document first.")

    # Lazy cross-lingual: try the original question first (a multilingual embedding
    # model can already recall Chinese chunks). Only when recall is empty/weak AND the
    # question is non-Chinese do we spend one extra lightweight rewrite + re-retrieve.
    hits = retrieve(
        question, kb, api_key, base_url,
        embed_model, embed_api_key, embed_base_url,
        doc_ids=doc_ids, categories=categories, strategy=strategy,
    )
    if not hits or max(h["score"] for h in hits) < DEFAULT_REFUSAL_THRESHOLD:
        _, retrieval_q, was = _translate_query_if_needed(question, api_key=api_key, base_url=base_url, model=model)
        if was:
            hits = retrieve(
                retrieval_q, kb, api_key, base_url,
                embed_model, embed_api_key, embed_base_url,
                doc_ids=doc_ids, categories=categories, strategy=strategy,
            )
    if not hits or max(h["score"] for h in hits) < DEFAULT_REFUSAL_THRESHOLD:
        raise ValueError(_refusal_message())

    context = "\n\n".join([f"[Source {i + 1}: {h['source']}]\n{h['text']}" for i, h in enumerate(hits)])
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior AI product coach. Answer strictly from the references. "
                "Cite [Source N]. If information is not present, say so clearly. "
                "Answer in the exact same language as the user's original query."
            ),
        }
    ]
    if history:
        messages.extend(history[-6:])
    messages.append(
        {
            "role": "user",
            "content": f"References:\n{context}\n\nQuestion: {question.strip()}{_LANG_ANCHOR}",
        }
    )
    completion = _chat_create(messages, api_key=api_key, base_url=base_url, model=model, temperature=0.2)
    result_text = completion.choices[0].message.content or ""
    return {
        "answer": result_text,
        "sources": [
            {"source": h["source"], "excerpt": h.get("excerpt") or h["text"][:180], "score": h["score"]}
            for h in hits
        ],
    }


def stream_answer(
    api_key: str,
    question: str,
    kb: dict,
    history: list[dict] | None = None,
    base_url: str = "",
    model: str = DEFAULT_CHAT_MODEL,
    embed_model: str = "",
    embed_api_key: str = "",
    embed_base_url: str = "",
    strategy: str | None = None,
    preset: str | None = None,
    categories: list[str] | None = None,
    doc_ids: list[int] | None = None,
):
    """Generator yielding SSE event dicts: sources, token, refusal/error, done."""
    chunks = kb.get("chunks", [])
    if not chunks:
        yield {"event": "error", "data": "Knowledge base is empty. Please upload and parse a document first."}
        return

    t0 = time.time()
    try:
        # Lazy cross-lingual: try the original question first (a multilingual embedding
        # model can already recall Chinese chunks). Only when recall is empty/weak AND
        # the question is non-Chinese do we spend one lightweight rewrite + re-retrieve.
        hits = retrieve(
            question, kb, api_key, base_url,
            embed_model, embed_api_key, embed_base_url,
            doc_ids=doc_ids, categories=categories, strategy=strategy,
        )
        if not hits or max(h["score"] for h in hits) < DEFAULT_REFUSAL_THRESHOLD:
            _, retrieval_q, was = _translate_query_if_needed(question, api_key=api_key, base_url=base_url, model=model)
            if was:
                hits = retrieve(
                    retrieval_q, kb, api_key, base_url,
                    embed_model, embed_api_key, embed_base_url,
                    strategy=strategy,
                )
    except Exception as exc:
        yield {"event": "error", "data": "Retrieval failed: " + str(exc)}
        return

    retrieve_time = time.time() - t0

    if not hits or max(h["score"] for h in hits) < DEFAULT_REFUSAL_THRESHOLD:
        yield {"event": "refusal", "data": json.dumps({"message": _refusal_message()}, ensure_ascii=False)}
        return

    sources_data = [
        {"source": h["source"], "excerpt": h.get("excerpt") or h["text"][:180], "score": h["score"]}
        for h in hits
    ]
    yield {"event": "sources", "data": json.dumps(sources_data, ensure_ascii=False)}

    context = "\n\n".join([f"[Source {i + 1}: {h['source']}]\n{h['text']}" for i, h in enumerate(hits)])
    system = _system_content(preset)
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": "References:\n" + context + "\n\nQuestion: " + question.strip() + _LANG_ANCHOR})

    total_tokens = 0
    try:
        stream = _chat_create(messages, api_key=api_key, base_url=base_url, model=model, stream=True, temperature=0.2)
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield {"event": "token", "data": delta.content}
            if chunk.usage:
                total_tokens = chunk.usage.total_tokens
    except Exception as exc:
        yield {"event": "error", "data": "Answer generation failed: " + str(exc)}
        return

    elapsed = time.time() - t0
    yield {
        "event": "done",
        "data": json.dumps({"total_tokens": total_tokens, "time_ms": round(elapsed * 1000), "retrieve_time_ms": round(retrieve_time * 1000)}, ensure_ascii=False),
    }


def get_document_content(data_dir: Path, user_id: int, doc_id: int) -> dict:
    from core.storage import get_all_chunks_for_user

    db_path = data_dir / "app.db"
    rows = get_all_chunks_for_user(db_path, user_id)
    doc_rows = [r for r in rows if r["doc_id"] == doc_id]
    if not doc_rows:
        raise ValueError(f"Document {doc_id} not found for user {user_id}")

    filename = doc_rows[0]["filename"]
    parents = sorted([r for r in doc_rows if r["parent_id"] is None], key=lambda r: r["seq"])
    if parents:
        content = "\n\n".join(p["text"] for p in parents)
    else:
        content = "\n\n".join(r["text"] for r in sorted(doc_rows, key=lambda r: r["seq"]))
    return {"id": doc_id, "filename": filename, "content": content, "chunk_count": len(doc_rows)}


def generate_suggestions(api_key: str, kb: dict, base_url: str = "", model: str = DEFAULT_CHAT_MODEL) -> str:
    chunks = kb.get("chunks", [])
    if not chunks:
        raise ValueError("Knowledge base is empty. Please upload and parse a document first.")
    corpus = "\n\n".join([c["text"] for c in chunks[:30]])
    completion = _chat_create(
        [
            {
                "role": "system",
                "content": (
                    "You are a senior AI product manager. Based on the uploaded documents, "
                    "produce a structured diagnostic report including: "
                    "1) Product positioning & highlights 2) Requirement clarity issues "
                    "3) Risks & omissions 4) Actionable improvement suggestions "
                    "5) Potential interview follow-up questions."
                ),
            },
            {"role": "user", "content": f"Document content:\n{corpus}"},
        ],
        api_key=api_key, base_url=base_url, model=model, temperature=0.3,
    )
    return completion.choices[0].message.content or ""
