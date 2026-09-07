#!/usr/bin/env python
"""Migrate existing kb.json to SQLite documents + chunks tables.

Usage:
    python scripts/migrate_kb.py [--user-id 1] [--data-dir data]

Migrates kb.json for each user found under data/users/ into the
new SQLite app.db schema.  Backs up kb.json to kb.json.bak after
a successful migration.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional


def _connect(db_path: Path):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(db_path: Path):
    """Ensure documents + chunks tables exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
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
        """)


def _create_doc(db_path: Path, user_id: int, filename: str) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO documents (user_id, filename, status, chunk_count, created_at) VALUES (?, ?, 'parsing', 0, ?)",
            (user_id, filename, time.time()),
        )
        return cur.lastrowid


def _update_doc_status(db_path: Path, doc_id: int, status: str, chunk_count: int = 0) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = ?, chunk_count = ? WHERE id = ?",
            (status, chunk_count, doc_id),
        )


def _insert_chunks(db_path: Path, doc_id: int, chunks_data: List[Dict]) -> None:
    import json as _json
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO chunks (doc_id, parent_id, seq, text, embedding) VALUES (?, ?, ?, ?, ?)",
            [
                (doc_id, None, c["seq"], c["text"],
                 _json.dumps(c["embedding"], ensure_ascii=False) if c.get("embedding") else None)
                for c in chunks_data
            ],
        )


def migrate_user(data_dir: Path, user_id: int) -> Dict:
    kb_file = data_dir / "users" / str(user_id) / "kb.json"
    if not kb_file.exists():
        return {"user_id": user_id, "status": "no-kb-file", "chunks": 0}

    with open(kb_file, "r", encoding="utf-8") as f:
        kb = json.load(f)
    chunks = kb.get("chunks", [])
    if not chunks:
        return {"user_id": user_id, "status": "empty-kb", "chunks": 0}

    db_path = data_dir / "app.db"
    _init_db(db_path)

    doc_chunks: Dict[str, List[Dict]] = {}
    for c in chunks:
        source = c.get("source", "")
        if " #" in source:
            doc_name = source.rsplit(" #", 1)[0]
        else:
            doc_name = source
        doc_chunks.setdefault(doc_name, []).append(c)

    total = 0
    for doc_name in sorted(doc_chunks.keys()):
        pieces = doc_chunks[doc_name]
        doc_id = _create_doc(db_path, user_id, doc_name)
        chunk_data = []
        for idx, p in enumerate(pieces):
            chunk_data.append({
                "text": p.get("text", ""),
                "embedding": p.get("embedding"),
                "seq": idx + 1,
            })
        _insert_chunks(db_path, doc_id, chunk_data)
        _update_doc_status(db_path, doc_id, "ready", len(chunk_data))
        total += len(chunk_data)

    bak = kb_file.with_suffix(".json.bak")
    kb_file.rename(bak)

    return {"user_id": user_id, "status": "migrated", "chunks": total}


def main():
    parser = argparse.ArgumentParser(description="Migrate kb.json to SQLite")
    parser.add_argument("--data-dir", default="data", help="Data directory (default: data)")
    parser.add_argument("--user-id", type=int, default=None, help="Migrate only this user (default: all users)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    users_dir = data_dir / "users"
    if not users_dir.exists():
        print("No users directory found at", users_dir)
        sys.exit(1)

    user_ids = []
    if args.user_id is not None:
        user_ids.append(args.user_id)
    else:
        for p in sorted(users_dir.iterdir()):
            if p.is_dir() and p.name.isdigit():
                user_ids.append(int(p.name))

    if not user_ids:
        print("No users found to migrate")
        sys.exit(0)

    for uid in user_ids:
        result = migrate_user(data_dir, uid)
        print(f"  User {uid}: {result['status']} ({result['chunks']} chunks)")

    print("Migration complete.")


if __name__ == "__main__":
    main()