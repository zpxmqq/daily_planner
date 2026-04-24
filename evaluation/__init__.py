"""Offline evaluation harness for daily-planner.

The harness exists for one reason: without it, every claim in the README
about "closed-loop AI" is self-attested. A reviewer has to read code to
believe anything. The fixtures below are small (≤ 30 items each) and
hand-labelled — not a benchmark, but enough that a number like
"tracking accuracy 0.82 / 25" on the metrics panel is real evidence
instead of vibes.

Run ``python -m evaluation.run_evals`` to produce a fresh report.
"""
