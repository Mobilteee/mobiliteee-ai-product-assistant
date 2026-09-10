# -*- coding: utf-8 -*-
r"""Deterministic evaluator regression tests.

Run: .venv\Scripts\python.exe tests/test_eval_metrics.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.run_eval import (  # noqa: E402
    _citation_result,
    _filename_from_source,
    _looks_like_refusal,
    _parse_citations,
)


def test_citations():
    answer = "结论来自 [Source 1]，补充见 [2] 与 [来源 3]。"
    assert _parse_citations(answer) == [1, 2, 3]
    assert _filename_from_source("docs/foo.md #3.2") == "docs/foo.md"
    result = _citation_result(answer, [{"source": "docs/foo.md #1.1"}], "docs/foo.md")
    assert result["citation_count"] == 3
    assert result["valid_count"] == 1
    assert result["correct_count"] == 1
    print("PASS test_citations")


def test_semantic_refusal():
    assert _looks_like_refusal("参考资料中不存在该问题的信息，因此无法回答。")
    assert _looks_like_refusal("参考资料中没有相关内容，不能给出结论。")
    assert not _looks_like_refusal(
        "Faithfulness 衡量回答是否基于检索上下文。参考资料未进一步说明具体计算阈值。"
    )
    print("PASS test_semantic_refusal")


if __name__ == "__main__":
    test_citations()
    test_semantic_refusal()
    print("ALL EVAL METRIC TESTS PASSED")
