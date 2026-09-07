# -*- coding: utf-8 -*-
"""One-time script: backfill topic categories for the corpus documents.

1. Upserts every producttext/*.md into the user KB with rag.category_for_filename()
   (covers/overwrites same-named docs, adds the ones missing from the DB).
2. Reclassifies any remaining doc that still sits in 'default' when its filename
   matches a known bucket (user uploads included).

Usage:
    .venv\\Scripts\\python.exe scripts/assign_categories.py                # user 1, data/
    .venv\\Scripts\\python.exe scripts/assign_categories.py --user-id 1 --data-dir data
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import rag  # noqa: E402
from core import storage  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--user-id", type=int, default=1)
    ap.add_argument("--producttext-dir", default=str(ROOT / "producttext"))
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    src = Path(args.producttext_dir)
    user_id = args.user_id

    # 1) (Re)ingest the seed corpus with per-file categories.
    seed_names: set[str] = set()
    for p in sorted(src.glob("*.md")):
        if not p.is_file():
            continue
        seed_names.add(p.name)
        cat = rag.category_for_filename(p.name)
        result = rag.add_documents(
            data_dir, user_id, [(p.name, p.read_bytes())], category=cat
        )
        print(f"  seed   {p.name[:34]:<36} -> {cat}  ({result['total_chunks']} chunks)")

    # 2) Reclassify leftover 'default' docs that match a bucket by filename.
    db_path = storage.init_db(data_dir)
    docs = storage.list_documents_by_user(db_path, user_id)
    updates = 0
    for d in docs:
        if d["filename"] in seed_names:
            continue
        if d.get("category", "default") != "default":
            continue
        cat = rag.category_for_filename(d["filename"])
        if cat == "default":
            continue
        with storage._connect(db_path) as conn:
            conn.execute(
                "UPDATE documents SET category = ? WHERE id = ?",
                (cat, d["id"]),
            )
        updates += 1
        print(f"  relabel {d['filename'][:34]:<36} -> {cat}")

    # Summary grouped exactly as GET /documents/categories builds it.
    grouped: dict[str, list] = {}
    for d in storage.list_documents_by_user(db_path, user_id):
        grouped.setdefault(d.get("category") or "default", []).append(d)
    print("\nSummary (category -> count):")
    total = 0
    for cat in sorted(grouped):
        items = grouped[cat]
        total += len(items)
        print(f"  {cat:<8} {len(items):>2}  " + ", ".join(i["filename"][:26] for i in items))
    print(f"\nTotal docs: {total}  | leftover-default relabeled: {updates}")


if __name__ == "__main__":
    main()
