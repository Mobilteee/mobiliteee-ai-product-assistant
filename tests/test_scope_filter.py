# -*- coding: utf-8 -*-
"""Scope-filter (topic category / doc_ids) regression tests.

Run:  .venv\\Scripts\\python.exe tests/test_scope_filter.py

Verifies the metadata + pre-filtering changes without touching the network:
  1. add_documents persists a category per document.
  2. init_db upgrades an older documents table with the category column.
  3. retrieve(doc_ids=...) only ever returns hits from the requested docs.
  4. retrieve(categories=...) pre-filters the candidate pool so cross-domain
     chunks can never surface (for naive / hybrid / hybrid_parent_child).
"""
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import rag  # noqa: E402
from core import storage  # noqa: E402

TMP = ROOT / "evals" / ".tmp_scope_test"
CAT_FRUIT = "水果客服"
CAT_MEMBER = "会员积分"
A_NAME = "a-mango.md"
B_NAME = "b-star-member.md"
A_TEXT = (
    "关于芒果售后的说明：芒果属于易损耗生鲜，运输应采用冷链并尽快发出。"
    "若芒果到货挤压腐烂，请在签收后两小时内拍照提交退款申请，我们将快速理赔。"
    "芒果的催熟与存放请参照随箱说明。"
)
B_TEXT = (
    "星尘会员积分兑换规则：星尘会员在本平台消费后按金额累计积分。"
    "积分可在星尘积分商城兑换运费券、优惠券与周边礼品。"
    "星尘高级会员积分加倍，有效期一年，逾期自动清零，请及时兑换。"
)


def _reset():
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)


def _seed():
    rag.add_documents(TMP, 1, [(A_NAME, A_TEXT.encode("utf-8"))], category=CAT_FRUIT)
    rag.add_documents(TMP, 1, [(B_NAME, B_TEXT.encode("utf-8"))], category=CAT_MEMBER)


def _doc_id(name: str) -> int:
    docs = storage.list_documents_by_user(storage.init_db(TMP), 1)
    return next(d["id"] for d in docs if d["filename"] == name)


def test_category_persisted():
    docs = storage.list_documents_by_user(storage.init_db(TMP), 1)
    cat_by_name = {d["filename"]: d["category"] for d in docs}
    assert cat_by_name[A_NAME] == CAT_FRUIT, cat_by_name
    assert cat_by_name[B_NAME] == CAT_MEMBER, cat_by_name
    kb = rag.load_kb(TMP, 1)
    chunks_cats = {c["filename"]: c["category"] for c in kb["chunks"]}
    assert set(chunks_cats.values()) == {CAT_FRUIT, CAT_MEMBER}
    print("PASS test_category_persisted")


def test_legacy_db_migrated():
    # Build a DB with the OLD documents schema (no category), then init_db upgrades it.
    old = ROOT / "evals" / ".tmp_legacy"
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    old.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(old / "app.db"))
    conn.execute(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " user_id INTEGER NOT NULL, filename TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'pending', chunk_count INTEGER NOT NULL DEFAULT 0,"
        " created_at REAL NOT NULL)"
    )
    conn.commit()
    conn.close()
    legacy_db = storage.init_db(old)
    doc_id = storage.create_document(legacy_db, 1, "legacy.md", category="履约结算")
    rows = storage.list_documents_by_user(legacy_db, 1)
    assert any(d["id"] == doc_id and d["category"] == "履约结算" for d in rows), rows
    shutil.rmtree(old, ignore_errors=True)
    print("PASS test_legacy_db_migrated")


def test_doc_ids_scope():
    kb = rag.load_kb(TMP, 1)
    id_b = _doc_id(B_NAME)
    for strategy in ("naive", "hybrid", "hybrid_parent_child"):
        # Query that only matches B; doc_ids restricted to A => strictly nothing.
        hits = rag.retrieve("星尘会员积分如何兑换", kb, top_k=4, strategy=strategy, doc_ids=[_doc_id(A_NAME)])
        assert hits == [], (strategy, hits)
        # Query matching B, restricted to B => every hit belongs to B.
        hits = rag.retrieve("星尘会员积分如何兑换", kb, top_k=4, strategy=strategy, doc_ids=[id_b])
        assert hits and all(h["doc_id"] == id_b for h in hits), (strategy, hits)
    print("PASS test_doc_ids_scope")


def test_categories_scope():
    kb = rag.load_kb(TMP, 1)
    fruit_id = _doc_id(A_NAME)
    member_id = _doc_id(B_NAME)
    for strategy in ("naive", "hybrid", "hybrid_parent_child"):
        # 芒果 only lives in the fruit category -> member-only scope must return nothing.
        assert rag.retrieve("芒果到货腐烂怎么处理", kb, top_k=4, strategy=strategy,
                            categories=[CAT_MEMBER]) == [], strategy
        # Star-member question scoped to fruit -> nothing.
        assert rag.retrieve("星尘会员积分兑换规则是什么", kb, top_k=4, strategy=strategy,
                            categories=[CAT_FRUIT]) == [], strategy
        # Same question scoped to the member category -> hits only from member docs.
        hits = rag.retrieve("星尘会员积分兑换规则是什么", kb, top_k=4, strategy=strategy,
                            categories=[CAT_MEMBER])
        assert hits and all(h["doc_id"] == member_id for h in hits), (strategy, hits)
        # Unfiltered run should still recall across the whole KB (no over-tightening).
        all_hits = rag.retrieve("芒果到货腐烂怎么处理", kb, top_k=4, strategy=strategy)
        assert all_hits and all(h["doc_id"] == fruit_id for h in all_hits), strategy
    print("PASS test_categories_scope")


if __name__ == "__main__":
    _reset()
    _seed()
    test_category_persisted()
    test_legacy_db_migrated()
    test_doc_ids_scope()
    test_categories_scope()
    shutil.rmtree(TMP, ignore_errors=True)
    print("ALL SCOPE-FILTER TESTS PASSED")
