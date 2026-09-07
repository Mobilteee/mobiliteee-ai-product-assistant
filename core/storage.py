import hashlib
import hmac
import os
import sqlite3
import time
from pathlib import Path


def _connect(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                latency_meta TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                parent_id INTEGER,
                seq INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT,
                FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                conversation_id INTEGER,
                question TEXT,
                answer_excerpt TEXT,
                thumbs INTEGER NOT NULL,
                reasons TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS query_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                conversation_id INTEGER,
                question TEXT,
                strategy TEXT,
                preset TEXT,
                refusal INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                retrieve_ms REAL NOT NULL DEFAULT 0,
                first_token_ms REAL NOT NULL DEFAULT 0,
                total_ms REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            """
        )
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN updated_at REAL")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN latency_meta TEXT")
        except Exception:
            pass
    return db_path


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()


def register_user(db_path: Path, username: str, password: str) -> bool:
    if len(username.strip()) < 3 or len(password) < 6:
        return False
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if existing:
            return False
        salt = os.urandom(16).hex()
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username.strip(), hash_password(password, salt) + ":" + salt, time.time()),
        )
    return True


def authenticate_user(db_path: Path, username: str, password: str):
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    if not row:
        return None
    stored, salt = row["password_hash"].rsplit(":", 1)
    expected = hash_password(password, salt)
    if not hmac.compare_digest(stored, expected):
        return None
    return {"id": row["id"], "username": row["username"]}


def list_users(db_path: Path):
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT id, username FROM users ORDER BY id").fetchall()
    return [{"id": r["id"], "username": r["username"]} for r in rows]


def create_conversation(db_path: Path, user_id: int, title: str) -> int:
    with _connect(db_path) as conn:
        now = time.time()
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, title, now, now),
        )
        return cur.lastrowid

def list_conversations(db_path: Path, user_id: int):
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            WHERE c.user_id = ?
            ORDER BY COALESCE(c.updated_at, c.created_at) DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"] or r["created_at"],
            "message_count": r["message_count"],
        }
        for r in rows
    ]

def update_conversation_title(db_path: Path, conversation_id: int, title: str) -> None:
    """Update a conversation title and bump updated_at."""
    rename_conversation(db_path, conversation_id, title)


def rename_conversation(db_path: Path, conversation_id: int, title: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), conversation_id),
        )


def touch_conversation(db_path: Path, conversation_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (time.time(), conversation_id),
        )

def delete_conversation(db_path: Path, conversation_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def add_message(
    db_path: Path,
    conversation_id: int,
    role: str,
    content: str,
    sources: list | None = None,
    latency_meta: dict | None = None,
) -> int:
    import json

    sources_json = json.dumps(sources or [], ensure_ascii=False)
    latency_json = json.dumps(latency_meta or {}, ensure_ascii=False)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, sources, latency_meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, sources_json, latency_json, time.time()),
        )
        return cur.lastrowid



def list_messages(db_path: Path, conversation_id: int):
    import json

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, sources, latency_meta, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    out = []
    for r in rows:
        try:
            sources = json.loads(r["sources"]) if r["sources"] else []
        except json.JSONDecodeError:
            sources = []
        try:
            latency_meta = json.loads(r["latency_meta"]) if r["latency_meta"] else {}
        except json.JSONDecodeError:
            latency_meta = {}
        out.append(
            {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "sources": sources,
                "latency_meta": latency_meta,
                "created_at": r["created_at"],
            }
        )
    return out



def get_conversation_title(db_path: Path, conversation_id: int) -> str:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row["title"] if row else "未命名会话"


# -- Document & Chunk helpers -------------------------------------------------

import json as _json


def create_document(db_path: Path, user_id: int, filename: str) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO documents (user_id, filename, status, chunk_count, created_at) VALUES (?, ?, 'parsing', 0, ?)",
            (user_id, filename, time.time()),
        )
        return cur.lastrowid


def update_document_status(db_path: Path, doc_id: int, status: str, chunk_count: int = 0) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = ?, chunk_count = ? WHERE id = ?",
            (status, chunk_count, doc_id),
        )


def list_documents_by_user(db_path: Path, user_id: int) -> list[dict]:
    """List documents deduplicated by filename (keep newest per filename)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, user_id, filename, status, chunk_count, created_at FROM documents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    seen: dict[str, dict] = {}
    for r in rows:
        fn = r["filename"]
        if fn not in seen:
            seen[fn] = {
                "id": r["id"],
                "user_id": r["user_id"],
                "filename": fn,
                "status": r["status"],
                "chunk_count": r["chunk_count"],
                "created_at": r["created_at"],
            }
    return list(seen.values())


def delete_document(db_path: Path, doc_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def insert_chunks(db_path: Path, doc_id: int, chunks_data: list[dict]) -> None:
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO chunks (doc_id, parent_id, seq, text, embedding) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    doc_id,
                    None,
                    c["seq"],
                    c["text"],
                    _json.dumps(c["embedding"], ensure_ascii=False) if c.get("embedding") else None,
                )
                for c in chunks_data
            ],
        )


def get_chunks_by_doc_ids(db_path: Path, doc_ids: list[int]) -> list[dict]:
    if not doc_ids:
        return []
    placeholders = ",".join("?" for _ in doc_ids)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT c.id, c.doc_id, c.parent_id, c.seq, c.text, c.embedding, d.filename "
            "FROM chunks c JOIN documents d ON c.doc_id = d.id "
            f"WHERE c.doc_id IN ({placeholders}) ORDER BY c.doc_id, c.seq",
            doc_ids,
        ).fetchall()
    return [
        {
            "id": r["id"],
            "doc_id": r["doc_id"],
            "parent_id": r["parent_id"],
            "seq": r["seq"],
            "text": r["text"],
            "embedding": _json.loads(r["embedding"]) if r["embedding"] else None,
            "filename": r["filename"],
        }
        for r in rows
    ]


def get_all_chunks_for_user(db_path: Path, user_id: int) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT c.id, c.doc_id, c.parent_id, c.seq, c.text, c.embedding, d.filename "
            "FROM chunks c JOIN documents d ON c.doc_id = d.id "
            "WHERE d.user_id = ? ORDER BY c.doc_id, c.seq",
            (user_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "doc_id": r["doc_id"],
            "parent_id": r["parent_id"],
            "seq": r["seq"],
            "text": r["text"],
            "embedding": _json.loads(r["embedding"]) if r["embedding"] else None,
            "filename": r["filename"],
        }
        for r in rows
    ]


def delete_chunks_by_doc_id(db_path: Path, doc_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

# -- P2 parent-child ingestion helpers --------------------------------------


def insert_chunk_tree(db_path: Path, doc_id: int, tree: list[dict]) -> None:
    """Insert parent-child chunks in a single transaction.

    tree: [{"seq": int, "text": parent_text, "embedding": optional,
            "children": [{"text": str, "embedding": optional}, ...]}]
    """
    with _connect(db_path) as conn:
        for parent in tree:
            cur = conn.execute(
                "INSERT INTO chunks (doc_id, parent_id, seq, text, embedding) VALUES (?, ?, ?, ?, ?)",
                (
                    doc_id,
                    None,
                    parent["seq"],
                    parent["text"],
                    _json.dumps(parent["embedding"], ensure_ascii=False) if parent.get("embedding") else None,
                ),
            )
            parent_id = cur.lastrowid
            for child_seq, child in enumerate(parent.get("children", []), start=1):
                conn.execute(
                    "INSERT INTO chunks (doc_id, parent_id, seq, text, embedding) VALUES (?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        parent_id,
                        child_seq,
                        child["text"],
                        _json.dumps(child["embedding"], ensure_ascii=False) if child.get("embedding") else None,
                    ),
                )


def delete_documents_by_filename(db_path: Path, user_id: int, filename: str) -> None:
    """Remove every copy of a filename for a user (used on re-upload)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM documents WHERE user_id = ? AND filename = ?",
            (user_id, filename),
        ).fetchall()
        for row in rows:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (row["id"],))
            conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))

# -- Feedback & query metrics (P3) -------------------------------------------


def add_feedback(
    db_path: Path,
    user_id: int,
    thumbs: int,
    question: str = "",
    answer_excerpt: str = "",
    reasons: list | None = None,
    conversation_id: int | None = None,
) -> int:
    import json as _fb_json

    reasons_json = _fb_json.dumps(reasons or [], ensure_ascii=False)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO feedback (user_id, conversation_id, question, answer_excerpt, thumbs, reasons, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, conversation_id, question, answer_excerpt, thumbs, reasons_json, time.time()),
        )
        return cur.lastrowid


def list_feedback(db_path: Path, user_id: int | None = None) -> list[dict]:
    import json as _fb_json

    sql = "SELECT * FROM feedback"
    params: tuple = ()
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params = (user_id,)
    sql += " ORDER BY created_at DESC"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        try:
            reasons = _fb_json.loads(r["reasons"]) if r["reasons"] else []
        except Exception:
            reasons = []
        out.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "conversation_id": r["conversation_id"],
            "question": r["question"],
            "answer_excerpt": r["answer_excerpt"],
            "thumbs": r["thumbs"],
            "reasons": reasons,
            "created_at": r["created_at"],
        })
    return out


def add_query_metric(
    db_path: Path,
    user_id: int,
    question: str = "",
    strategy: str = "",
    preset: str = "",
    refusal: int = 0,
    total_tokens: int = 0,
    retrieve_ms: float = 0.0,
    first_token_ms: float = 0.0,
    total_ms: float = 0.0,
    conversation_id: int | None = None,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO query_metrics
            (user_id, conversation_id, question, strategy, preset, refusal,
             total_tokens, retrieve_ms, first_token_ms, total_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, conversation_id, question, strategy, preset, refusal,
                total_tokens, retrieve_ms, first_token_ms, total_ms, time.time(),
            ),
        )
        return cur.lastrowid


def list_query_metrics(db_path: Path, user_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM query_metrics"
    params: tuple = ()
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params = (user_id,)
    sql += " ORDER BY created_at DESC LIMIT 200"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "conversation_id": r["conversation_id"],
            "question": r["question"],
            "strategy": r["strategy"],
            "preset": r["preset"],
            "refusal": r["refusal"],
            "total_tokens": r["total_tokens"],
            "retrieve_ms": r["retrieve_ms"],
            "first_token_ms": r["first_token_ms"],
            "total_ms": r["total_ms"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def metrics_overview(db_path: Path, user_id: int | None = None) -> dict:
    """Aggregate feedback + query_metrics for the dashboard."""
    feedback = list_feedback(db_path, user_id)
    metrics = list_query_metrics(db_path, user_id)

    thumbs_counts = {"up": 0, "down": 0}
    reason_counts: dict[str, int] = {}
    for item in feedback:
        if item["thumbs"] >= 1:
            thumbs_counts["up"] += 1
        else:
            thumbs_counts["down"] += 1
            for reason in item["reasons"]:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    by_strategy: dict[str, dict] = {}
    for m in metrics:
        agg = by_strategy.setdefault(
            m["strategy"] or "unknown",
            {"count": 0, "retrieve_ms": 0.0, "first_token_ms": 0.0, "total_ms": 0.0, "total_tokens": 0, "refusals": 0},
        )
        agg["count"] += 1
        agg["retrieve_ms"] += m["retrieve_ms"]
        agg["first_token_ms"] += m["first_token_ms"]
        agg["total_ms"] += m["total_ms"]
        agg["total_tokens"] += m["total_tokens"]
        agg["refusals"] += int(m["refusal"])
    for agg in by_strategy.values():
        if agg["count"]:
            for key in ("retrieve_ms", "first_token_ms", "total_ms"):
                agg[key] = round(agg[key] / agg["count"], 1)

    return {
        "feedback": {"total": len(feedback), **thumbs_counts},
        "reason_distribution": reason_counts,
        "query_metrics": {"total": len(metrics), "by_strategy": by_strategy},
        "recent_metrics": metrics[:20],
    }
