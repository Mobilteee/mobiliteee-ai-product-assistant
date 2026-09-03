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
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            """
        )
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
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at) VALUES (?, ?, ?)",
            (user_id, title, time.time()),
        )
        return cur.lastrowid


def list_conversations(db_path: Path, user_id: int):
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            WHERE c.user_id = ?
            ORDER BY c.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "message_count": r["message_count"],
        }
        for r in rows
    ]


def rename_conversation(db_path: Path, conversation_id: int, title: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
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
) -> int:
    import json

    sources_json = json.dumps(sources or [], ensure_ascii=False)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, sources, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, sources_json, time.time()),
        )
        return cur.lastrowid


def list_messages(db_path: Path, conversation_id: int):
    import json

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT role, content, sources, created_at
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
        out.append(
            {
                "role": r["role"],
                "content": r["content"],
                "sources": sources,
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
