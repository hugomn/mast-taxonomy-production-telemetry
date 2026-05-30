"""Score the LLM-judge against a hand-labeled gold set.

Honesty mechanism for the headline result: the judge is NOT ground truth. This
measures its agreement with human labels on a small gold set so the writeup can
state the judge's reliability instead of assuming it.

Reports:
  * exact-match accuracy on primary mode (gold vs judge)
  * is_failure binary agreement (did they agree the run failed at all?)
  * Cohen's kappa on is_failure
  * a confusion list for the misses

gold_labels.json format: {"<run_id>": {"primary_mode": "<code|none>", "is_failure": bool}}

Usage:
    python research/score_judge.py \
        --gold research/gold_labels.json \
        --verdicts research/judge_verdicts.jsonl
"""

from __future__ import annotations

import argparse
import json


def cohen_kappa_binary(pairs: list[tuple[bool, bool]]) -> float:
    n = len(pairs)
    if n == 0:
        return 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    pa_true = sum(1 for a, _ in pairs if a) / n
    pb_true = sum(1 for _, b in pairs if b) / n
    pe = pa_true * pb_true + (1 - pa_true) * (1 - pb_true)
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="research/gold_labels.json")
    ap.add_argument("--verdicts", default="research/judge_verdicts.jsonl")
    args = ap.parse_args()

    gold = json.load(open(args.gold))
    verdicts = {}
    with open(args.verdicts) as f:
        for line in f:
            v = json.loads(line)
            verdicts[v["run_id"]] = v

    scored = [(rid, g, verdicts[rid]) for rid, g in gold.items() if rid in verdicts]
    if not scored:
        print("No overlap between gold and verdicts.")
        return

    primary_hits = 0
    fail_pairs = []
    misses = []
    for rid, g, v in scored:
        gp = g.get("primary_mode")
        vp = v.get("primary_mode")
        if gp == vp:
            primary_hits += 1
        else:
            misses.append((rid[:8], gp, vp))
        gf = bool(g.get("is_failure"))
        vf = bool(v.get("is_failure"))
        fail_pairs.append((gf, vf))

    n = len(scored)
    print(f"gold-labeled runs scored: {n}")
    print(f"primary-mode exact match: {primary_hits}/{n} = {primary_hits / n:.1%}")
    fa = sum(1 for a, b in fail_pairs if a == b) / n
    print(f"is_failure agreement:     {fa:.1%}")
    print(f"is_failure Cohen's kappa: {cohen_kappa_binary(fail_pairs):.3f}")
    if misses:
        print("\nprimary-mode misses (run, gold, judge):")
        for rid, gp, vp in misses:
            print(f"  {rid}  gold={gp}  judge={vp}")


if __name__ == "__main__":
    main()
