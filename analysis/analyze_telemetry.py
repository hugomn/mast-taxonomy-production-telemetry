"""Structural failure-profile analysis of the org's production execution_steps.

Runs over the REDACTED export (no raw content needed) and produces the
quantitative backbone of the headline result: what a real autonomous
multi-agent organization actually does and where it fails in production.

Every number here is derived from data/execution_steps_redacted.jsonl, which is
itself reproducible via tools/export_execution_steps.py. Nothing here is
synthetic and nothing requires the raw content payloads.

Usage:
    python research/analyze_telemetry.py \
        --in data/execution_steps_redacted.jsonl \
        --out research/telemetry_profile.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict


def num(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = int(round((len(sorted_vals) - 1) * p))
    return sorted_vals[k]


def analyze(path: str) -> dict:
    status = Counter()
    type_count = Counter()
    type_status = defaultdict(Counter)
    per_run_steps = defaultdict(int)
    per_run_failed = defaultdict(int)
    per_run_tool = defaultdict(int)
    tok_in = tok_out = 0.0
    cost_total = 0.0
    cost_rows = 0
    durations: list[float] = []
    failed_tool_durations: list[float] = []

    with open(path) as f:
        for line in f:
            r = json.loads(line)
            rid = r["run_id"]
            t = r["type"]
            s = r["status"]
            status[s] += 1
            type_count[t] += 1
            type_status[t][s] += 1
            per_run_steps[rid] += 1
            if s == "failed":
                per_run_failed[rid] += 1
            if t == "tool_call":
                per_run_tool[rid] += 1
            tok_in += num(r.get("input_tokens"))
            tok_out += num(r.get("output_tokens"))
            c = num(r.get("cost_usd"))
            if c:
                cost_total += c
                cost_rows += 1
            d = r.get("duration_ms")
            if d:
                durations.append(float(d))
                if t == "tool_call" and s == "failed":
                    failed_tool_durations.append(float(d))

    durations.sort()
    n_runs = len(per_run_steps)
    steps_sorted = sorted(per_run_steps.values())
    runs_with_failure = sum(1 for v in per_run_failed.values() if v > 0)

    # Cost concentration: how much spend sits in the most expensive runs?
    run_cost: dict[str, float] = defaultdict(float)
    # (recomputed in a light second pass to keep memory flat)

    tc = type_status["tool_call"]
    total_tool = sum(tc.values())

    return {
        "n_steps": int(sum(type_count.values())),
        "n_runs": n_runs,
        "status_distribution": dict(status.most_common()),
        "type_distribution": dict(type_count.most_common()),
        "tool_call_status": dict(tc),
        "tool_call_failure_rate": round(tc.get("failed", 0) / total_tool, 4) if total_tool else 0,
        "tool_call_stuck_running_rate": round(tc.get("running", 0) / total_tool, 4) if total_tool else 0,
        "reasoning_status": dict(type_status["reasoning"]),
        "steps_per_run": {
            "min": steps_sorted[0],
            "median": percentile(steps_sorted, 0.5),
            "p95": percentile(steps_sorted, 0.95),
            "p99": percentile(steps_sorted, 0.99),
            "max": steps_sorted[-1],
            "mean": round(sum(steps_sorted) / n_runs, 1),
        },
        "runs_with_at_least_one_failure": runs_with_failure,
        "run_failure_rate": round(runs_with_failure / n_runs, 4),
        "tokens": {"input_total": int(tok_in), "output_total": int(tok_out)},
        "cost_usd_total": round(cost_total, 2),
        "cost_rows": cost_rows,
        "duration_ms": {
            "count": len(durations),
            "median": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95),
            "p99": percentile(durations, 0.99),
            "max": durations[-1] if durations else 0,
        },
        "failed_tool_call_duration_ms": {
            "count": len(failed_tool_durations),
            "median": percentile(sorted(failed_tool_durations), 0.5),
            "p95": percentile(sorted(failed_tool_durations), 0.95),
        },
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/execution_steps_redacted.jsonl")
    ap.add_argument("--out", default="research/telemetry_profile.json")
    args = ap.parse_args()

    profile = analyze(args.inp)
    print(json.dumps(profile, indent=2))
    with open(args.out, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"\nWrote {args.out}")
