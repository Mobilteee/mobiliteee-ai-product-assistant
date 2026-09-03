import json
import re
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI


DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"


def _client(api_key: str, base_url: str = "") -> OpenAI:
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


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


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    sections = re.split(r"(?m)^#{1,3}\s+.*$|\n\n", text)
    sections = [s.strip() for s in sections if s.strip()]

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


def embed_texts(
    api_key: str,
    texts: list[str],
    base_url: str = "",
    model: str = DEFAULT_EMBED_MODEL,
) -> list[list[float]]:
    client = _client(api_key, base_url)
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


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
    chunks_meta: list[dict] = []
    for uploaded in files:
        raw_bytes = uploaded.getvalue()
        text = extract_text(raw_bytes, uploaded.name)
        pieces = chunk_text(text)
        for idx, piece in enumerate(pieces):
            chunks_meta.append({"source": f"{uploaded.name} #{idx + 1}", "text": piece})
    if not chunks_meta:
        raise ValueError("未能从文档中提取有效文本")

    mode = "keyword"
    texts = [c["text"] for c in chunks_meta]
    if embed_model and embed_api_key:
        try:
            vectors = embed_texts(embed_api_key, texts, embed_base_url, embed_model)
            for meta, vector in zip(chunks_meta, vectors):
                meta["embedding"] = vector
            mode = "vector"
        except Exception as exc:
            # 若 Embedding 服务不可用，自动降级为关键词检索，不阻断用户
            pass

    user_dir = data_dir / "users" / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    kb_file = user_dir / "kb.json"
    kb_file.write_text(
        json.dumps({"mode": mode, "chunks": chunks_meta}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(chunks_meta), mode


def load_kb(data_dir: Path, user_id: int) -> dict:
    kb_file = data_dir / "users" / str(user_id) / "kb.json"
    if not kb_file.exists():
        return {"mode": "keyword", "chunks": []}
    payload = json.loads(kb_file.read_text(encoding="utf-8"))
    payload.setdefault("mode", "keyword")
    payload.setdefault("chunks", [])
    return payload


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


def _keyword_retrieve(query: str, chunks: list[dict], top_k: int = 4) -> list[dict]:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        query_tokens = set(query.lower().split())
    scored = []
    for chunk in chunks:
        text_tokens = set(_tokenize(chunk["text"]))
        hits = len(query_tokens & text_tokens)
        if hits == 0:
            continue
        score = hits / max(1, len(query_tokens))
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"source": c["source"], "text": c["text"], "score": round(s, 4)}
        for s, c in scored[:top_k]
    ]


def _vector_retrieve(
    api_key: str,
    chunks: list[dict],
    query: str,
    base_url: str,
    embed_model: str,
    top_k: int = 4,
) -> list[dict]:
    query_vector = embed_texts(api_key, [query], base_url, embed_model)[0]
    scored = []
    for chunk in chunks:
        if not chunk.get("embedding"):
            continue
        score = _cosine(query_vector, chunk["embedding"])
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"source": c["source"], "text": c["text"], "score": round(s, 4)}
        for s, c in scored[:top_k]
    ]


def retrieve(
    query: str,
    kb: dict,
    chat_api_key: str,
    chat_base_url: str = "",
    embed_model: str = "",
    embed_api_key: str = "",
    embed_base_url: str = "",
    top_k: int = 4,
) -> list[dict]:
    chunks = kb.get("chunks", [])
    if not chunks:
        return []
    if kb.get("mode") == "vector" and embed_model and embed_api_key:
        try:
            return _vector_retrieve(
                embed_api_key,
                chunks,
                query,
                embed_base_url,
                embed_model,
                top_k,
            )
        except Exception:
            # Embedding 服务异常时降级为关键词检索
            pass
    results = _keyword_retrieve(query, chunks, top_k)
    return results


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
) -> dict:
    chunks = kb.get("chunks", [])
    if not chunks:
        raise ValueError("知识库为空，请先上传并解析文档")

    hits = retrieve(
        question,
        kb,
        api_key,
        base_url,
        embed_model,
        embed_api_key,
        embed_base_url,
    )
    if not hits:
        raise ValueError("没有检索到相关内容，请换一种问法或补充文档")

    context = "\n\n".join(
        [f"【来源 {i + 1}：{h['source']}】\n{h['text']}" for i, h in enumerate(hits)]
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是一位资深的 AI 产品经理教练。回答必须严格基于参考资料，"
                "引用时标注【来源 N】。若资料中没有答案，请明确说明，不要编造。"
            ),
        }
    ]
    if history:
        messages.extend(history[-6:])
    messages.append(
        {
            "role": "user",
            "content": f"参考资料：\n{context}\n\n问题：{question}",
        }
    )
    client = _client(api_key, base_url)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
    )
    result_text = completion.choices[0].message.content or ""
    return {
        "answer": result_text,
        "sources": [
            {"source": h["source"], "excerpt": h["text"][:180], "score": h["score"]}
            for h in hits
        ],
    }


def generate_suggestions(
    api_key: str,
    kb: dict,
    base_url: str = "",
    model: str = DEFAULT_CHAT_MODEL,
) -> str:
    chunks = kb.get("chunks", [])
    if not chunks:
        raise ValueError("知识库为空，请先上传文档")
    corpus = "\n\n".join([c["text"] for c in chunks[:30]])
    client = _client(api_key, base_url)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是资深 AI 产品经理。请根据用户上传的产品文档输出结构化诊断报告，"
                    "包含：1) 产品定位与亮点 2) 需求清晰度问题 3) 风险与遗漏 "
                    "4) 可执行的改进建议 5) 面试官可能追问的问题。"
                ),
            },
            {"role": "user", "content": f"文档内容如下：\n{corpus}"},
        ],
        temperature=0.3,
    )
    return completion.choices[0].message.content or ""
