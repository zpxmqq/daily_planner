"""Offline evaluation runner for daily-planner.

Why this file exists
--------------------
Every previous iteration of this project claimed "AI 闭环"、"tracking 准确"、
"降级可见" with zero numbers to back it up. That is the single biggest
credibility gap. This runner loads hand-labelled fixtures and produces a
simple JSON report a reviewer can `cat` or display in the UI.

What this is NOT
----------------
- Not a benchmark. Fixtures are small (≤ 30 items per suite), curated by
  the author. Absolute numbers should be read as "do the rules basically
  work on representative cases" rather than "beats X%".
- Not a replacement for user testing. It catches regressions in the
  deterministic layer (rules, normalizers, keyword matcher). It does NOT
  call the LLM — no flaky online tests.

Usage
-----
    python -m evaluation.run_evals                  # print + write JSON
    python -m evaluation.run_evals --suite tracking # run only one suite
    python -m evaluation.run_evals --quiet          # JSON only, no pretty

The report lands at ``evaluation/last_report.json`` so ``pages/profile.py``
(or any review surface) can read and display it without re-running.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Ensure the project root is on sys.path so ``python evaluation/run_evals.py``
# works the same as ``python -m evaluation.run_evals``.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.llm_schemas import normalize_plan_feedback, normalize_review_feedback  # noqa: E402
from services.tracking_service import auto_track_suggestion  # noqa: E402
from services.classification_service import classify_task_tag  # noqa: E402


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPORT_PATH = Path(__file__).resolve().parent / "last_report.json"


@dataclass
class CaseResult:
    id: str
    passed: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "passed": self.passed,
            "detail": self.detail,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class SuiteReport:
    name: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total": self.total,
            "passed": self.passed,
            "accuracy": round(self.accuracy, 3),
            "failures": [r.to_dict() for r in self.results if not r.passed],
            "all_results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Suite · tracking
# ---------------------------------------------------------------------------


def _eval_tracking(cases: list[dict]) -> SuiteReport:
    """Rule-based tracking: exact label match with a small tolerance clause.

    A case can set ``allow_partial: true`` to accept either ``done`` or
    ``partial`` — this is for hard synonym cases where we don't want to be
    strict about the rule engine picking the stronger label.
    """
    report = SuiteReport(name="tracking")
    for case in cases:
        expected = case["expected_status"]
        allow_partial = bool(case.get("allow_partial"))

        result = auto_track_suggestion(
            case["yesterday_rec"],
            case["today_tasks"],
            case["today_extra"],
        )
        actual = result["status"] if isinstance(result, dict) else None

        if expected is None:
            passed = result is None
            detail = "expected None (no suggestion); " + ("matched." if passed else f"got {actual!r}.")
        elif allow_partial and expected == "done":
            passed = actual in ("done", "partial")
            detail = f"accepted {{done, partial}} for hard synonym case; got {actual!r}."
        else:
            passed = actual == expected
            detail = f"expected {expected!r}; got {actual!r}."

        report.results.append(
            CaseResult(
                id=case["id"],
                passed=passed,
                detail=detail,
                expected=expected,
                actual=actual,
            )
        )
    return report


# ---------------------------------------------------------------------------
# Suite · schema normalizers
# ---------------------------------------------------------------------------


def _eval_schemas(cases: list[dict]) -> SuiteReport:
    """Plan / review normalizers — degraded flag + field shape invariants."""
    report = SuiteReport(name="schemas")
    for case in cases:
        kind = case["kind"]
        fn: Callable[[Any, str], dict]
        if kind == "plan":
            fn = normalize_plan_feedback
        elif kind == "review":
            fn = normalize_review_feedback
        else:
            report.results.append(
                CaseResult(id=case["id"], passed=False, detail=f"unknown kind {kind!r}")
            )
            continue

        output = fn(case.get("raw_data"), case.get("raw_text", ""))
        reasons: list[str] = []
        ok = True

        if "expect_degraded" in case:
            expected = bool(case["expect_degraded"])
            actual = bool(output.get("degraded"))
            if expected != actual:
                ok = False
                reasons.append(f"degraded: expected {expected}, got {actual}")

        if case.get("expect_has_field"):
            field_name = case["expect_has_field"]
            if not output.get(field_name):
                ok = False
                reasons.append(f"field {field_name!r} expected non-empty, got empty")

        if case.get("expect_empty_field"):
            field_name = case["expect_empty_field"]
            value = output.get(field_name)
            if value:  # a non-empty string or non-empty list is wrong
                ok = False
                reasons.append(f"field {field_name!r} expected empty, got {value!r}")

        if case.get("expect_list_field"):
            field_name = case["expect_list_field"]
            value = output.get(field_name)
            if not isinstance(value, list):
                ok = False
                reasons.append(f"field {field_name!r} expected list, got {type(value).__name__}")
            elif "expect_list_len" in case and len(value) != case["expect_list_len"]:
                ok = False
                reasons.append(
                    f"field {field_name!r} expected len {case['expect_list_len']}, got {len(value)}"
                )

        report.results.append(
            CaseResult(
                id=case["id"],
                passed=ok,
                detail="ok" if ok else " | ".join(reasons),
                expected={
                    k: case[k]
                    for k in (
                        "expect_degraded",
                        "expect_has_field",
                        "expect_empty_field",
                        "expect_list_field",
                        "expect_list_len",
                    )
                    if k in case
                },
                actual={
                    "degraded": output.get("degraded"),
                    "keys": sorted(output.keys()),
                },
            )
        )
    return report


# ---------------------------------------------------------------------------
# Suite · classification (keyword tier only — embedding needs live history)
# ---------------------------------------------------------------------------


def _eval_classification(cases: list[dict]) -> SuiteReport:
    report = SuiteReport(name="classification")
    for case in cases:
        result = classify_task_tag(
            task_text=case["task_text"],
            user_tag=case.get("user_tag", ""),
            historical_tasks=[],  # no embedding tier — tests rule engine only
            known_tags=[],
            is_unplanned=bool(case.get("is_unplanned")),
        )
        tag_ok = result["tag"] == case["expected_tag"]
        source_ok = result["auto_source"] == case["expected_source"]
        passed = tag_ok and source_ok
        detail = (
            f"tag={result['tag']!r}(expect {case['expected_tag']!r}) "
            f"source={result['auto_source']!r}(expect {case['expected_source']!r})"
        )
        report.results.append(
            CaseResult(
                id=case["id"],
                passed=passed,
                detail=detail,
                expected={"tag": case["expected_tag"], "source": case["expected_source"]},
                actual={"tag": result["tag"], "source": result["auto_source"]},
            )
        )
    return report


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


SUITES: dict[str, tuple[str, Callable[[list[dict]], SuiteReport]]] = {
    "tracking": ("tracking_cases.json", _eval_tracking),
    "schemas": ("schema_cases.json", _eval_schemas),
    "classification": ("classification_cases.json", _eval_classification),
}


def _load_cases(filename: str) -> list[dict]:
    path = FIXTURES_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def run(selected: list[str] | None = None) -> dict:
    reports: list[SuiteReport] = []
    target = selected or list(SUITES.keys())
    for name in target:
        if name not in SUITES:
            raise SystemExit(f"unknown suite: {name!r}; choose from {list(SUITES)}")
        filename, fn = SUITES[name]
        reports.append(fn(_load_cases(filename)))

    total = sum(r.total for r in reports)
    passed = sum(r.passed for r in reports)
    overall_accuracy = passed / total if total else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overall": {
            "total": total,
            "passed": passed,
            "accuracy": round(overall_accuracy, 3),
        },
        "suites": [r.to_dict() for r in reports],
    }


def _print_pretty(report: dict) -> None:
    print(f"== daily-planner eval · {report['generated_at']} ==")
    overall = report["overall"]
    print(
        f"overall: {overall['passed']}/{overall['total']} "
        f"= {overall['accuracy']:.1%}"
    )
    for suite in report["suites"]:
        print(
            f"  [{suite['name']}] {suite['passed']}/{suite['total']} "
            f"= {suite['accuracy']:.1%}"
        )
        for failure in suite["failures"]:
            print(f"    FAIL {failure['id']}: {failure['detail']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run daily-planner offline evaluations.")
    parser.add_argument(
        "--suite",
        action="append",
        help="Run only this suite (can be passed multiple times). Default: all.",
    )
    parser.add_argument("--quiet", action="store_true", help="Skip pretty-printed output.")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write last_report.json.",
    )
    args = parser.parse_args(argv)

    report = run(args.suite)

    if not args.no_write:
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not args.quiet:
        _print_pretty(report)

    # Non-zero exit only if a failure shows up — handy for CI or a git hook.
    return 0 if report["overall"]["passed"] == report["overall"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
