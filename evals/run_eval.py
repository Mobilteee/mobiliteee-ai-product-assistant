#!/usr/bin/env python
"""Retrieval and generation eval for the AI Product Knowledge Assistant.

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
    .venv\\Scripts\\python.exe evals/run_eval.py --judge          # + cited generation eval

Outputs:
    evals/EVAL_RESULTS.json / EVAL_RESULTS.md  (dashboard data source)
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs without adding a dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")

from core import rag  # noqa: E402


def _load_creds():
    return {
        "api_key": os.getenv("DEMO_CHAT_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("DEMO_CHAT_BASE_URL") or os.getenv("OPENAI_BASE_URL", ""),
        "model": os.getenv("DEMO_CHAT_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }


def _load_judge(model_override: str = ""):
    return {
        "api_key": (
            os.getenv("EVAL_JUDGE_API_KEY")
            or os.getenv("DEMO_CHAT_API_KEY")
            or os.getenv("OPENAI_API_KEY", "")
        ),
        "base_url": (
            os.getenv("EVAL_JUDGE_BASE_URL")
            or os.getenv("DEMO_CHAT_BASE_URL")
            or os.getenv("OPENAI_BASE_URL", "")
        ),
        "model": (
            model_override
            or os.getenv("EVAL_JUDGE_MODEL")
            or os.getenv("DEMO_CHAT_MODEL")
            or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        ),
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


def _score_generation(client, model, question, answer, context, expected_points):
    """Ask the judge model for groundedness, relevance and answer coverage."""
    points = "\n".join(f"- {point}" for point in expected_points)
    prompt = (
        "你是一个严格的 RAG 评测员。下面给出来源片段、问题与回答。\n"
        "请只返回 JSON："
        "{\"faithfulness\": 0.0-1.0, \"answer_relevance\": 0.0-1.0, "
        "\"answer_correctness\": 0.0-1.0}\n"
        "评分规则：faithfulness 只惩罚无证据支持、编造或与证据冲突的事实性陈述；"
        "不要因为回答更长、包含委婉表达、补充“资料未提及”的边界说明而扣分。"
        "核心事实有依据但含少量次要无依据细节记 0.5，核心事实无依据记 0。"
        "answer_relevance 衡量是否切题；answer_correctness 衡量是否覆盖期望要点且没有关键事实错误。\n\n"
        f"期望要点：\n{points}\n\n"
        f"证据：\n{context[:1800]}\n\n问题：{question}\n\n回答：{answer[:900]}\n"
    )
    text = ""
    for _ in range(3):
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        if text.strip():
            break
    if not text.strip():
        raise ValueError("judge returned empty content after 3 attempts")
    try:
        start = text.find("{")
        end = text.rfind("}")
        data = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        return {
            "faithfulness": max(0.0, min(1.0, float(data.get("faithfulness", 0)))),
            "answer_relevance": max(0.0, min(1.0, float(data.get("answer_relevance", 0)))),
            "answer_correctness": max(0.0, min(1.0, float(data.get("answer_correctness", 0)))),
        }
    except Exception:
        return {
            "faithfulness": 0.0,
            "answer_relevance": 0.0,
            "answer_correctness": 0.0,
        }


_CITATION_RE = re.compile(r"\[\s*(?:(?:source|来源)\s*[:：]?\s*)?(\d+)\s*\]", re.IGNORECASE)


def _parse_citations(answer: str) -> list[int]:
    """Return one-based source numbers cited in an answer."""
    return [int(match) for match in _CITATION_RE.findall(answer or "")]


def _filename_from_source(source: str) -> str:
    """Normalise ``filename.md #3.2`` back to ``filename.md``."""
    return (source or "").rsplit(" #", 1)[0]


_REFUSAL_RE = re.compile(
    r"(?:材料|资料|参考(?:文献|资料|片段)|知识库).{0,80}"
    r"(?:没有|不存在|不包含|未包含|未(?:能)?给出|未提及).{0,90}"
    r"(?:信息|内容|数据|无法|不能)"
    r"|(?:无法|不能).{0,10}(?:回答|作答|给出答案|据此回答)",
    re.DOTALL,
)


def _looks_like_refusal(answer: str) -> bool:
    """Treat an explicit no-answer response as a semantic refusal."""
    text = (answer or "").replace("\n", " ").strip()
    opening = re.split(r"[。！？!?]", text, maxsplit=1)[0][:220]
    return bool(_REFUSAL_RE.search(opening))


def _citation_result(answer: str, sources: list[dict], expected_doc: str) -> dict:
    """Score deterministic citation validity and source-document accuracy."""
    cited = _parse_citations(answer)
    valid = []
    correct = []
    for source_no in cited:
        if 1 <= source_no <= len(sources):
            valid.append(source_no)
            source = sources[source_no - 1] or {}
            filename = source.get("filename") or _filename_from_source(source.get("source", ""))
            if filename == expected_doc:
                correct.append(source_no)
    return {
        "cited": cited,
        "valid": valid,
        "correct": correct,
        "citation_count": len(cited),
        "valid_count": len(valid),
        "correct_count": len(correct),
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _generation_cases() -> tuple[list[dict], list[dict]]:
    path = ROOT / "evals" / "generation_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    known = payload.get("known") or []
    negative = payload.get("negative") or []
    if not known:
        raise ValueError("evals/generation_cases.json has no known-answer cases")
    return known, negative


def _run_generation_eval(kb: dict, embed: dict, limit: int, negative_limit: int,
                         judge_model: str = "") -> dict:
    """Run the cited, bounded generation suite against the product generation path."""
    from openai import OpenAI

    generator = _load_creds()
    judge = _load_judge(judge_model)
    if not generator["api_key"]:
        raise RuntimeError("Generation eval requires DEMO_CHAT_API_KEY / OPENAI_API_KEY")
    if not judge["api_key"]:
        raise RuntimeError("Judge eval requires EVAL_JUDGE_API_KEY / DEMO_CHAT_API_KEY / OPENAI_API_KEY")

    known_cases, negative_cases = _generation_cases()
    known_cases = known_cases[:limit] if limit > 0 else known_cases
    negative_cases = negative_cases[:negative_limit] if negative_limit > 0 else negative_cases
    client = OpenAI(api_key=judge["api_key"], base_url=judge["base_url"] or None)
    all_results = []

    for case in known_cases + negative_cases:
        question = case["q"]
        expected_doc = case.get("doc") or ""
        expected_points = case.get("expected_points") or []
        should_refuse = bool(case.get("should_refuse"))
        t0 = time.time()
        answer_parts = []
        sources = []
        first_token_ms = None
        error = ""
        refused = False
        generation_attempts = 0

        for generation_attempts in range(1, 4):
            answer_parts = []
            sources = []
            refused = False
            error = ""
            attempt_t0 = time.time()
            try:
                for event in rag.stream_answer(
                    generator["api_key"],
                    question,
                    kb,
                    base_url=generator["base_url"],
                    model=generator["model"],
                    strategy="hybrid_parent_child",
                ):
                    if event["event"] == "sources":
                        sources = json.loads(event["data"])
                    elif event["event"] == "token":
                        if first_token_ms is None:
                            first_token_ms = (time.time() - attempt_t0) * 1000
                        answer_parts.append(event["data"])
                    elif event["event"] == "refusal":
                        refused = True
                    elif event["event"] == "error":
                        error = str(event.get("data") or "generation error")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if refused or answer_parts:
                error = ""
                break

        total_ms = (time.time() - t0) * 1000
        answer = "".join(answer_parts).strip()
        if not refused and not answer and not error:
            error = f"empty generation after {generation_attempts} attempts"
        engine_refused = refused
        if answer and _looks_like_refusal(answer):
            refused = True
        scores = None

        if not should_refuse and not refused and answer and not error:
            hits = rag.retrieve(
                question, kb, top_k=4, strategy="hybrid_parent_child",
                embed_model=embed["model"],
                embed_api_key=embed["api_key"],
                embed_base_url=embed["base_url"],
            )
            context = "\n\n".join(
                f"[Source {i + 1}: {hit['source']}]\n{hit['text']}"
                for i, hit in enumerate(hits)
            )
            if context:
                try:
                    scores = _score_generation(
                        client,
                        judge["model"],
                        question,
                        answer,
                        context,
                        expected_points,
                    )
                except Exception as exc:
                    error = f"judge: {type(exc).__name__}: {exc}"

        citations = (
            _citation_result(answer, sources, expected_doc)
            if not should_refuse
            else {"cited": [], "valid": [], "correct": [], "citation_count": 0,
                  "valid_count": 0, "correct_count": 0}
        )
        issues = []
        if should_refuse:
            if not refused:
                issues.append("failed_refusal")
        else:
            if error:
                issues.append("generation_error")
            if refused:
                issues.append("false_refusal")
            if not answer:
                issues.append("empty_answer")
            if citations["citation_count"] == 0:
                issues.append("missing_citation")
            elif citations["correct_count"] < citations["citation_count"]:
                issues.append("invalid_citation")
            if scores and scores["answer_correctness"] < 0.6:
                issues.append("low_answer_correctness")
            if scores and scores["faithfulness"] < 0.8:
                issues.append("low_faithfulness")

        result = {
            "id": case.get("id") or question,
            "kind": "negative" if should_refuse else "known",
            "question": question,
            "doc": expected_doc,
            "expected_points": expected_points,
            "answer": answer[:1200],
            "refused": refused,
            "engine_refused": engine_refused,
            "generation_attempts": generation_attempts,
            "error": error,
            "scores": scores,
            "citations": citations,
            "sources": sources,
            "ttft_ms": round(first_token_ms, 1) if first_token_ms is not None else None,
            "total_ms": round(total_ms, 1),
            "issues": issues,
        }
        all_results.append(result)
        status = "PASS" if not issues else ",".join(issues)
        print(f"[generation] {result['id'][:42]:42s} {status}")

    known_results = [item for item in all_results if item["kind"] == "known"]
    negative_results = [item for item in all_results if item["kind"] == "negative"]
    scored = [item for item in known_results if item["scores"] and not item["error"]]
    answered = [item for item in known_results if item["answer"] and not item["refused"] and not item["error"]]
    citation_count = sum(item["citations"]["citation_count"] for item in known_results)
    correct_citation_count = sum(item["citations"]["correct_count"] for item in known_results)
    ttft_values = [item["ttft_ms"] for item in answered if item["ttft_ms"] is not None]

    return {
        "sample_size": len(all_results),
        "known_sample_size": len(known_results),
        "negative_sample_size": len(negative_results),
        "scored_sample_size": len(scored),
        "faithfulness": _mean([item["scores"]["faithfulness"] for item in scored]),
        "answer_relevance": _mean([item["scores"]["answer_relevance"] for item in scored]),
        "answer_correctness": _mean([item["scores"]["answer_correctness"] for item in scored]),
        "citation_presence": round(
            sum(bool(item["citations"]["citation_count"]) for item in answered) / len(answered), 3
        ) if answered else 0.0,
        "citation_accuracy": round(correct_citation_count / citation_count, 3) if citation_count else 0.0,
        "citation_coverage": round(
            sum(bool(item["citations"]["correct_count"]) for item in known_results) / len(known_results), 3
        ) if known_results else 0.0,
        "refusal_recall": round(
            sum(item["refused"] for item in negative_results) / len(negative_results), 3
        ) if negative_results else 0.0,
        "false_refusal_rate": round(
            sum(item["refused"] for item in known_results) / len(known_results), 3
        ) if known_results else 0.0,
        "avg_ttft_ms": round(sum(ttft_values) / len(ttft_values), 1) if ttft_values else 0.0,
        "avg_e2e_ms": round(sum(item["total_ms"] for item in all_results) / len(all_results), 1),
        "generator_model": generator["model"],
        "judge_model": judge["model"],
        "cases": all_results,
        "failures": [item for item in all_results if item["issues"]],
    }


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
    parser.add_argument("--judge", "--generation", dest="judge", action="store_true",
                        help="generate cited answers and run the LLM judge")
    parser.add_argument("--limit", type=int, default=10000, help="max retrieval items to evaluate")
    parser.add_argument("--generation-limit", type=int, default=20, help="known-answer generation cases (0 = all)")
    parser.add_argument("--negative-limit", type=int, default=4, help="no-answer refusal cases (0 = all)")
    parser.add_argument("--judge-model", default="", help="override EVAL_JUDGE_MODEL for this run")
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
        try:
            gen_metrics = _run_generation_eval(
                kb, embed, args.generation_limit, args.negative_limit,
                judge_model=args.judge_model,
            )
            print("Generation metrics:", {
                key: gen_metrics[key]
                for key in (
                    "sample_size", "answer_correctness", "faithfulness",
                    "answer_relevance", "citation_accuracy", "refusal_recall",
                    "avg_ttft_ms",
                )
            })
        except RuntimeError as exc:
            print(f"--judge skipped: {exc}")

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
            "run mode: " + mode + ". generation metrics and citation accuracy need --judge."
        ),
    }
    _write_outputs(result)
    shutil.rmtree(tmp, ignore_errors=True)


def _write_outputs(result: dict):
    rows = result["metrics"]
    block_rows = result.get("metrics_block") or []
    mode = result["mode"]
    generation = result.get("generation")
    with (ROOT / "evals" / "EVAL_RESULTS.md").open("w", encoding="utf-8") as fh:
        fh.write("# RAG Evaluation Results\n\n")
        fh.write(f"- Goldset: {result['goldset_items']} items · retrieval mode: {mode}\n")
        fh.write(f"- Block-anchored subset: {result.get('block_items', 0)} items\n")
        if generation:
            fh.write(
                f"- Generation eval: {generation['sample_size']} cases "
                f"({generation['known_sample_size']} known + {generation['negative_sample_size']} no-answer) "
                f"· generator: {generation['generator_model']} · judge: {generation['judge_model']}\n"
            )
        else:
            fh.write("- Generation eval: disabled (run with --judge)\n")
        fh.write("\n## Full goldset\n\n")
        fh.write("| strategy | n | hit@1 | hit@4 | MRR | avg top score | avg retrieve ms |\n")
        fh.write("|---|---|---|---|---|---|---|\n")
        for row in rows:
            fh.write(
                f"| {row['strategy']} | {row['n']} | {row['hit_at_1']:.1%} | {row['hit_at_4']:.1%} "
                f"| {row['mrr']:.3f} | {row['avg_top_score']:.3f} | {row['avg_retrieve_ms']:.2f} |\n"
            )
        if block_rows and any(row["n"] for row in block_rows):
            fh.write("\n## Block-anchored subset (strategy differences only show here)\n\n")
            fh.write("| strategy | n | hit@1 | hit@4 | MRR | avg retrieve ms |\n")
            fh.write("|---|---|---|---|---|---|\n")
            for row in block_rows:
                fh.write(
                    f"| {row['strategy']} | {row['n']} | {row['hit_at_1']:.1%} | {row['hit_at_4']:.1%} "
                    f"| {row['mrr']:.3f} | {row['avg_retrieve_ms']:.2f} |\n"
                )
        if generation:
            fh.write("\n## Generation eval (hybrid_parent_child)\n\n")
            fh.write("| metric | value |\n")
            fh.write("|---|---:|\n")
            fh.write(f"| answer correctness | {generation['answer_correctness']:.1%} |\n")
            fh.write(f"| faithfulness | {generation['faithfulness']:.1%} |\n")
            fh.write(f"| answer relevance | {generation['answer_relevance']:.1%} |\n")
            fh.write(f"| citation presence | {generation['citation_presence']:.1%} |\n")
            fh.write(f"| citation accuracy | {generation['citation_accuracy']:.1%} |\n")
            fh.write(f"| citation coverage | {generation['citation_coverage']:.1%} |\n")
            fh.write(f"| refusal recall | {generation['refusal_recall']:.1%} |\n")
            fh.write(f"| false refusal rate | {generation['false_refusal_rate']:.1%} |\n")
            fh.write(f"| avg TTFT | {generation['avg_ttft_ms']:.1f} ms |\n")
            fh.write(f"| avg end-to-end | {generation['avg_e2e_ms']:.1f} ms |\n")
            failures = generation.get("failures") or []
            if failures:
                fh.write("\n### Failure cases\n\n")
                fh.write("| case | issues | answer excerpt |\n")
                fh.write("|---|---|---|\n")
                for item in failures[:10]:
                    answer = (item.get("answer") or item.get("error") or "").replace("|", "\\|").replace("\n", " ")
                    fh.write(
                        f"| {item['id']} | {', '.join(item['issues'])} | {answer[:180]} |\n"
                    )
    (ROOT / "evals" / "EVAL_RESULTS.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nWrote evals/EVAL_RESULTS.md + EVAL_RESULTS.json")


if __name__ == "__main__":
    main()
