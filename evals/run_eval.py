#!/usr/bin/env python
"""Retrieval (+ optional generation) eval for the AI Product Knowledge Assistant.

Gold target is computed per item from the human-written ``keywords`` in
``evals/goldset.json``: we locate the gold document's *parent chunks* whose
text best covers those keywords, then score each retrieval strategy on whether
its top results land on that anchor — reported as hit@1 / hit@4 / MRR@4.

The old doc-level "any of top-4 from the gold doc" test saturates on small
corpora and cannot tell strategies apart; chunk-anchored, rank-aware metrics
can. Two views are emitted:

- ``metrics``       — over the whole goldset;
- ``metrics_block`` — over items whose anchor is a *proper subset* of the gold
  document's parent chunks (i.e. real block-level targets). Items pointing at
  single-parent documents are excluded so they can't mask strategy gaps.

Embeddings (optional): if DEMO_EMBED_MODEL/API_KEY are set, the KB is built
with real vectors and hybrid/naive get a vector path; otherwise the run is
labeled ``lexical-only``.

Usage:
    .venv\\Scripts\\python.exe evals/run_eval.py                 # lexical hit@1/@4/MRR + latency
    .venv\\Scripts\\python.exe evals/run_eval.py --judge          # + LLM answer & faithfulness/relevance

Outputs:
    evals/EVAL_RESULTS.json / EVAL_RESULTS.md  (dashboard data source)
"""
import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import rag  # noqa: E402


def _load_creds():
    return {
        "api_key": os.getenv("DEMO_CHAT_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("DEMO_CHAT_BASE_URL") or os.getenv("OPENAI_BASE_URL", ""),
        "model": os.getenv("DEMO_CHAT_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }


def _load_embed():
    return {
        "api_key": os.getenv("DEMO_EMBED_API_KEY", ""),
        "base_url": os.getenv("DEMO_EMBED_BASE_URL", ""),
        "model": os.getenv("DEMO_EMBED_MODEL", ""),
    }


def _parent_anchor_ids(item: dict, kb: dict) -> set[int]:
    """Parent chunk ids of the gold doc that best cover the item's keywords.

    A parent is a "cover" of a keyword when >=50% of that keyword's tokens
    appear in the parent text. The anchor is the parent(s) with the highest
    cover count — i.e. the passage a human would cite as the answer location.
    """
    doc = item.get("doc") or ""
    kws = item.get("keywords") or []
    parents = [
        c for c in kb["chunks"]
        if c.get("is_parent") is True
        and (c.get("filename") or (c.get("source") or "").rsplit(" #", 1)[0]) == doc
    ]
    if not parents:
        return set()
    if not kws:
        return {c["id"] for c in parents}
    scored = []
    for p in parents:
        ptoks = set(rag._tokenize(p.get("text") or ""))
        cov = 0
        for kw in kws:
            kt = set(rag._tokenize(kw))
            if kt and len(kt & ptoks) / len(kt) >= 0.5:
                cov += 1
        scored.append((cov, p["id"]))
    mx = max(c for c, _ in scored)
    if mx <= 0:
        return {c["id"] for c in parents}
    return {pid for cov, pid in scored if cov == mx}


def _anchor_of_hit(h: dict):
    """Normalise a hit to the parent-level anchor it belongs to.

    naive/hybrid retrieve parent chunks (chunk_id is the anchor); the
    hybrid_parent_child strategy retrieves child chunks, so we map each child
    back to its parent via parent_id — making all three strategies comparable.
    """
    return h.get("chunk_id") if h.get("is_parent") else h.get("parent_id")


def _score_generation(client, question, answer, context):
    """Ask the judge model for faithfulness + relevance scores (0..1)."""
    prompt = (
        "你是一个严格的 RAG 评测员。下面给出来源片段、问题与回答。\n"
        "请只返回 JSON：{\"faithfulness\": 0.0-1.0, \"answer_relevance\": 0.0-1.0}\n"
        "faithfulness 衡量回答是否完全基于来源片段且无幻觉；answer_relevance 衡量是否切题。\n\n"
        f"来源片段：\n{context[:2500]}\n\n问题：{question}\n\n回答：{answer[:1200]}\n"
    )
    resp = client.chat.completions.create(
        model=_load_creds()["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=80,
    )
    text = resp.choices[0].message.content or "{}"
    try:
        start = text.find("{")
        end = text.rfind("}")
        data = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        return {
            "faithfulness": max(0.0, min(1.0, float(data.get("faithfulness", 0)))),
            "answer_relevance": max(0.0, min(1.0, float(data.get("answer_relevance", 0)))),
        }
    except Exception:
        return {"faithfulness": 0.0, "answer_relevance": 0.0}


def _aggregate(triples: list[tuple]) -> dict:
    """triples: (is_hit_1, is_hit_4, reciprocal_rank, top_score, ms) per item."""
    n = len(triples)
    if n == 0:
        return {"n": 0, "hit_at_1": 0.0, "hit_at_4": 0.0, "mrr": 0.0,
                "avg_top_score": 0.0, "avg_retrieve_ms": 0.0}
    h1 = sum(t[0] for t in triples)
    h4 = sum(t[1] for t in triples)
    mrr = sum(t[2] for t in triples)
    top = sum(t[3] for t in triples)
    ms = sum(t[4] for t in triples)
    return {
        "n": n,
        "hit_at_1": round(h1 / n, 4),
        "hit_at_4": round(h4 / n, 4),
        "mrr": round(mrr / n, 4),
        "avg_top_score": round(top / n, 4),
        "avg_retrieve_ms": round(ms / n, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge", action="store_true", help="generate answers and run LLM scoring")
    parser.add_argument("--limit", type=int, default=10000, help="max items to evaluate")
    args = parser.parse_args()

    goldset = json.loads((ROOT / "evals" / "goldset.json").read_text(encoding="utf-8"))[: args.limit]
    embed = _load_embed()
    embed_on = bool(embed["api_key"] and embed["model"])

    tmp = ROOT / "evals" / ".tmp_eval"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    doc_files = sorted((ROOT / "producttext").glob("*.md"))
    if embed_on:
        rag.add_documents(
            tmp, 1, [(p.name, p.read_bytes()) for p in doc_files],
            embed_model=embed["model"], embed_api_key=embed["api_key"], embed_base_url=embed["base_url"],
        )
    else:
        rag.ensure_seed_kb(tmp, 1, ROOT / "producttext")
    kb = rag.load_kb(tmp, 1)

    parents_per_doc = Counter(c.get("filename") for c in kb["chunks"] if c.get("is_parent") is True)
    anchors = []
    unanchored = 0
    for item in goldset:
        a = _parent_anchor_ids(item, kb)
        anchors.append(a)
        unanchored += int(not a)
    if unanchored:
        print(f"[warn] {unanchored} items have no keyword-anchor in the KB (doc mismatch?)")

    strategies = ["naive", "hybrid", "hybrid_parent_child"]
    metrics = []
    metrics_block = []
    for strategy in strategies:
        triples_all = []
        triples_block = []
        for item, gold in zip(goldset, anchors):
            t0 = time.time()
            hits = rag.retrieve(
                item["q"], kb, top_k=4, strategy=strategy,
                embed_model=embed["model"], embed_api_key=embed["api_key"], embed_base_url=embed["base_url"],
            )
            ms = (time.time() - t0) * 1000
            top_score = max((h.get("score") for h in hits), default=0.0)
            h1 = h4 = 0
            rr = 0.0
            if gold:
                for i, h in enumerate(hits[:4]):
                    if _anchor_of_hit(h) in gold:
                        if i == 0:
                            h1 = 1
                        h4 = 1
                        rr = 1.0 / (i + 1)
                        break
            triples_all.append((h1, h4, rr, top_score, ms))
            if gold and len(gold) < parents_per_doc.get(item.get("doc"), 0):
                triples_block.append((h1, h4, rr, top_score, ms))
        row = {"strategy": strategy, **_aggregate(triples_all)}
        block = {"strategy": strategy, **_aggregate(triples_block)}
        metrics.append(row)
        metrics_block.append(block)
        print(
            f"{strategy:20s} hit@1={row['hit_at_1']:.1%} hit@4={row['hit_at_4']:.1%} "
            f"MRR={row['mrr']:.3f} ms={row['avg_retrieve_ms']:.2f}"
            f"   [block n={block['n']}] hit@1={block['hit_at_1']:.1%} MRR={block['mrr']:.3f}"
        )

    gen_metrics = None
    if args.judge:
        creds = _load_creds()
        if not creds["api_key"]:
            print("--judge requires DEMO_CHAT_API_KEY / OPENAI_API_KEY; skipped generation eval.")
        else:
            from openai import OpenAI
            client = OpenAI(api_key=creds["api_key"], base_url=creds["base_url"] or None)
            eval_items = goldset[: min(len(goldset), 10)]
            fidelity_sum = relevance_sum = 0.0
            ttft_list = []
            context_examples = []
            for item in eval_items:
                hits = rag.retrieve(
                    item["q"], kb, top_k=4, strategy="hybrid_parent_child",
                    embed_model=embed["model"], embed_api_key=embed["api_key"], embed_base_url=embed["base_url"],
                )
                context = "\n\n".join(h["text"] for h in hits)
                answer_parts = []
                t0 = time.time()
                first_token_ms = None
                for event in rag.stream_answer(
                    creds["api_key"],
                    item["q"],
                    kb,
                    base_url=creds["base_url"],
                    model=creds["model"],
                    strategy="hybrid_parent_child",
                ):
                    if event["event"] == "token":
                        if first_token_ms is None:
                            first_token_ms = (time.time() - t0) * 1000
                        answer_parts.append(event["data"])
                    elif event["event"] == "refusal":
                        break
                ttft_list.append(first_token_ms or 0.0)
                answer = "".join(answer_parts)
                if answer and context:
                    scores = _score_generation(client, item["q"], answer, context)
                    fidelity_sum += scores["faithfulness"]
                    relevance_sum += scores["answer_relevance"]
                    context_examples.append({"question": item["q"], "answer": answer[:180]})
            if eval_items:
                gen_metrics = {
                    "sample_size": len(eval_items),
                    "faithfulness": round(fidelity_sum / len(eval_items), 3),
                    "answer_relevance": round(relevance_sum / len(eval_items), 3),
                    "avg_ttft_ms": round(sum(ttft_list) / len(ttft_list), 1),
                }
            print("LLM metrics:", gen_metrics)

    mode = "embedding" if embed_on else "lexical-only"
    block_total = metrics_block[0]["n"] if metrics_block else 0
    result = {
        "goldset_items": len(goldset),
        "mode": mode,
        "unanchored_items": unanchored,
        "block_items": block_total,
        "metrics": metrics,
        "metrics_block": metrics_block,
        "generation": gen_metrics,
        "note": (
            "hit@1/hit@4/MRR are chunk-level: a hit is a top-K result landing on the "
            "keyword-anchored parent of the gold doc. metrics_block covers only items "
            "whose anchor is a proper subset of the doc's parents (true block-level targets). "
            "run mode: " + mode + ". faithfulness/relevance/ttft need --judge."
        ),
    }
    _write_outputs(result)
    shutil.rmtree(tmp, ignore_errors=True)


def _write_outputs(result: dict):
    rows = result["metrics"]
    block_rows = result.get("metrics_block") or []
    mode = result["mode"]
    with (ROOT / "evals" / "EVAL_RESULTS.md").open("w", encoding="utf-8") as fh:
        fh.write("# Retrieval Eval Results\n\n")
        fh.write(f"- Goldset: {result['goldset_items']} items · mode: {mode}\n")
        fh.write(f"- Block-anchored subset: {result.get('block_items', 0)} items\n")
        fh.write(f"- Generation eval: {result['generation'] or 'disabled (run with --judge)'}\n\n")
        fh.write("## Full goldset\n\n")
        fh.write("| strategy | n | hit@1 | hit@4 | MRR | avg top score | avg retrieve ms |\n")
        fh.write("|---|---|---|---|---|---|---|\n")
        for r in rows:
            fh.write(
                f"| {r['strategy']} | {r['n']} | {r['hit_at_1']:.1%} | {r['hit_at_4']:.1%} "
                f"| {r['mrr']:.3f} | {r['avg_top_score']:.3f} | {r['avg_retrieve_ms']:.2f} |\n"
            )
        if block_rows and any(r["n"] for r in block_rows):
            fh.write("\n## Block-anchored subset (strategy differences only show here)\n\n")
            fh.write("| strategy | n | hit@1 | hit@4 | MRR | avg retrieve ms |\n")
            fh.write("|---|---|---|---|---|---|\n")
            for r in block_rows:
                fh.write(
                    f"| {r['strategy']} | {r['n']} | {r['hit_at_1']:.1%} | {r['hit_at_4']:.1%} "
                    f"| {r['mrr']:.3f} | {r['avg_retrieve_ms']:.2f} |\n"
                )
    (ROOT / "evals" / "EVAL_RESULTS.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nWrote evals/EVAL_RESULTS.md + EVAL_RESULTS.json")


if __name__ == "__main__":
    main()
