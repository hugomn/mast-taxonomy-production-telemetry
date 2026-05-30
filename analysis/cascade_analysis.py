"""Failure cascade analysis over sampled production runs.

The brief asks whether failure mode X triggers mode Y downstream. The LLM-judge
gives a run-level label; this script works at the STEP level on the raw
trajectories to find concrete, observable cascade primitives that don't need a
model:

  * error -> retry chains: a failed tool_call followed by repeated calls to the
    same tool (step repetition, MAST 1.3 / 2.6 signature).
  * error -> stuck: a failed/odd tool result followed by a terminal hang
    (the run never completes — MAST 1.5 / 3.1).
  * runaway loops: the same (tool_name, action) repeated N+ times in one run
    (inefficient reasoning / cost escalation, MAST 2.6 / 3.3).
  * recovery: a failed tool_call followed by a DIFFERENT successful call and a
    clean completion (NOT a run-level failure — the discipline that keeps the
    judge honest).

All counts are observable from status + tool_name sequences in
data/sampled_runs_full.jsonl. No model, fully reproducible.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict


def tool_name(step: dict) -> str | None:
    c = step.get("content")
    if isinstance(c, dict):
        return c.get("tool_name")
    return None


def analyze(path: str) -> dict:
    runs = defaultdict(list)
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            runs[r["run_id"]].append(r)

    error_then_retry_same = 0
    error_then_stuck = 0
    recovered = 0
    runaway_runs = 0
    runs_with_any_failed = 0
    repetition_runs = 0
    tool_failure_counts = Counter()

    for rid, steps in runs.items():
        steps = sorted(steps, key=lambda s: (s.get("created_at") or "", s.get("id") or ""))
        tool_seq = [(s["type"], s["status"], tool_name(s)) for s in steps]
        has_failed = any(st == "failed" for _, st, _ in tool_seq)
        if has_failed:
            runs_with_any_failed += 1

        # tool failure tallies
        for typ, st, name in tool_seq:
            if typ == "tool_call" and st == "failed" and name:
                tool_failure_counts[name] += 1

        # error -> retry same tool / error -> stuck / recovery
        for i, (typ, st, name) in enumerate(tool_seq):
            if typ == "tool_call" and st == "failed":
                later = tool_seq[i + 1:]
                same_after = any(t == "tool_call" and n == name for t, _, n in later)
                stuck_after = any(stt == "running" for _, stt, _ in later)
                diff_ok_after = any(
                    t == "tool_call" and stt == "completed" and n != name
                    for t, stt, n in later
                )
                ends_clean = tool_seq[-1][1] == "completed"
                if same_after:
                    error_then_retry_same += 1
                if stuck_after:
                    error_then_stuck += 1
                if diff_ok_after and ends_clean and not stuck_after:
                    recovered += 1

        # runaway: same (tool, action) >= 8 times
        action_counts = Counter()
        for s in steps:
            c = s.get("content")
            if isinstance(c, dict) and c.get("tool_name"):
                act = c.get("tool_input", {})
                act_key = act.get("action") or act.get("operation") if isinstance(act, dict) else None
                action_counts[(c["tool_name"], act_key)] += 1
        if action_counts and max(action_counts.values()) >= 8:
            runaway_runs += 1
        if action_counts and max(action_counts.values()) >= 4:
            repetition_runs += 1

    n = len(runs)
    return {
        "n_runs": n,
        "runs_with_any_failed_step": runs_with_any_failed,
        "cascade_primitives": {
            "error_then_retry_same_tool": error_then_retry_same,
            "error_then_stuck_terminal_hang": error_then_stuck,
            "recovered_after_error": recovered,
        },
        "runaway_runs_ge8_same_action": runaway_runs,
        "repetition_runs_ge4_same_action": repetition_runs,
        "top_failing_tools": dict(tool_failure_counts.most_common(10)),
        "interpretation": (
            "recovered_after_error counts runs where a tool error is followed by a "
            "different successful call and a clean finish — these are NOT run-level "
            "failures and explain why a naive 'any failed step = failure' classifier "
            "over-counts. error_then_stuck is the dangerous cascade: a tool problem "
            "followed by a terminal hang that never completes."
        ),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/sampled_runs_full.jsonl")
    ap.add_argument("--out", default="research/cascade_profile.json")
    args = ap.parse_args()
    prof = analyze(args.inp)
    print(json.dumps(prof, indent=2))
    with open(args.out, "w") as f:
        json.dump(prof, f, indent=2)
    print(f"\nWrote {args.out}")
