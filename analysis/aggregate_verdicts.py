"""Aggregate LLM-judge verdicts into the headline MAST distribution.

Turns research/judge_verdicts.jsonl into:
  * the production MAST failure-mode distribution (primary mode), per stratum
  * failure rate by stratum (sanity: does the judge call 'healthy' runs clean?)
  * mode co-occurrence (primary + secondary) — the cascade signal
  * a comparison hook against the original MAST paper's benchmark distribution

Because the sample is STRATIFIED (failure regions over-sampled), the raw mode
counts are NOT population rates. This script also reports a re-weighted estimate
that maps each stratum back to its true share of the 23,624-run population, so
the headline distribution reflects production reality, not the sampling design.

Usage:
    python research/aggregate_verdicts.py \
        --verdicts research/judge_verdicts.jsonl \
        --summaries research/run_summaries.json \
        --out research/mast_distribution.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

# True population size per stratum (from the full 23,624-run telemetry).
POPULATION = {"failed": 1810, "stuck": 1843, "long": 237, "healthy": 18415}
# "long" overlaps failed/stuck in the raw data; sample_runs.py assigns each run
# to exactly one stratum (failed > stuck > long > healthy priority), so for
# re-weighting we use the disjoint population the sampler actually drew from.
# healthy here means "neither failed nor stuck and 5..76 steps"; the remaining
# ~1300 runs (short/odd) are outside all strata and are reported as uncovered.
TOTAL_RUNS = 23624


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", default="research/judge_verdicts_enriched.jsonl")
    ap.add_argument("--out", default="research/mast_distribution.json")
    ap.add_argument("--include-excluded", action="store_true",
                    help="keep infra-bug-window runs (default: drop them for clean numbers)")
    args = ap.parse_args()

    verdicts = []
    dropped = 0
    with open(args.verdicts) as f:
        for line in f:
            v = json.loads(line)
            if v.get("excluded") and not args.include_excluded:
                dropped += 1
                continue
            verdicts.append(v)
    if dropped:
        print(f"# dropped {dropped} runs in documented infra-bug windows "
              f"(see data_exclusions.json); use --include-excluded to keep them")

    by_stratum = defaultdict(list)
    for v in verdicts:
        by_stratum[v.get("stratum")].append(v)

    # Primary-mode distribution overall and per stratum.
    primary_overall = Counter(v.get("primary_mode") for v in verdicts)
    primary_by_stratum = {
        s: dict(Counter(v.get("primary_mode") for v in vs).most_common())
        for s, vs in by_stratum.items()
    }

    # Failure rate the judge assigns per stratum (sanity check).
    fail_rate = {}
    for s, vs in by_stratum.items():
        n = len(vs)
        fails = sum(1 for v in vs if v.get("is_failure"))
        fail_rate[s] = {"n": n, "is_failure": fails, "rate": round(fails / n, 3) if n else 0}

    # Co-occurrence: primary + each secondary, counted as unordered pairs.
    pair_counts = Counter()
    for v in verdicts:
        modes = [v.get("primary_mode")] + (v.get("secondary_modes") or [])
        modes = [m for m in modes if m and m != "none"]
        for i in range(len(modes)):
            for j in range(i + 1, len(modes)):
                pair = tuple(sorted((modes[i], modes[j])))
                pair_counts[pair] += 1

    # Population-reweighted failure-mode estimate. For each stratum, the judged
    # sample's mode shares scale to that stratum's population, then sum.
    reweighted = Counter()
    covered_pop = 0
    for s, vs in by_stratum.items():
        if s not in POPULATION or not vs:
            continue
        covered_pop += POPULATION[s]
        share = POPULATION[s] / len(vs)
        for v in vs:
            reweighted[v.get("primary_mode")] += share
    reweighted_pct = {
        m: round(c / covered_pop, 4) for m, c in reweighted.most_common()
    } if covered_pop else {}

    out = {
        "n_runs_judged": len(verdicts),
        "primary_mode_overall_RAW_stratified": dict(primary_overall.most_common()),
        "primary_mode_by_stratum": primary_by_stratum,
        "judge_failure_rate_by_stratum": fail_rate,
        "mode_cooccurrence_pairs": {f"{a}+{b}": c for (a, b), c in pair_counts.most_common(20)},
        "population_reweighted_primary_share": reweighted_pct,
        "reweighting_note": (
            "RAW counts over-represent failures by design (stratified sample). "
            "population_reweighted_primary_share maps each stratum's judged mode "
            f"shares back onto its true population (covered {covered_pop}/{TOTAL_RUNS} "
            "runs) for a production-realistic estimate. The ~1300 runs outside all "
            "strata (very short / odd-length) are not covered and not extrapolated."
        ),
    }
    print(json.dumps(out, indent=2))
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
