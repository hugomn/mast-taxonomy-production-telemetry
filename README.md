# Applying MAST to a real closed-alpha agent platform

An honest failure-mode analysis of **639,381 execution steps** from **23,624
runs** on a closed-alpha autonomous-agent platform, over five months — applying
the **MAST** failure taxonomy (Cemri et al. 2025) to deployed agents rather than
benchmark tasks.

This repo contains the aggregate results and the analysis code. It deliberately
contains **no trajectory text** — only de-identified aggregates.

> **MAST** — *Multi-Agent System Failure Taxonomy*, 14 failure modes in 3
> categories, from Cemri et al. 2025 ([arXiv:2503.13657](https://arxiv.org/abs/2503.13657)),
> built from 1,600+ annotated **benchmark** traces (human inter-annotator kappa
> 0.88). The taxonomy and dataset are theirs. This work applies their taxonomy to
> a new subject: a deployed platform's production logs.

## Scope & data provenance (read this)

The dataset is the telemetry of a **closed-alpha agent platform**, spanning all
of its workspaces (the operating lab's own agents and early-alpha workspaces) —
not a single team's agents. The operating lab's own roster is the **largest
single cohort** and the **heaviest user of agent-to-agent coordination** (a
slight majority of all A2A runs), but the platform-wide totals include other
early-alpha workspaces. Numbers are reported at the **platform** level except
where explicitly noted.

Everything published here is **aggregate** (counts, rates, distributions) — no
trajectory text, no identifiers, no per-workspace breakdowns. The analysis was
run by the platform operator over its own closed-alpha system.

**Privacy.** The raw telemetry contains real content (it is production data) and
**never leaves the operator's environment** — it is not in this repository or its
history. What's published is strictly derived aggregates: integer counts, rates,
percentages, MAST mode codes, and the analysis code. There are **no names, email
addresses, repository paths, dollar figures, or any personal data** in any
committed file (verified by exhaustive scan of every file and the full git
history). If you find anything that looks like it shouldn't be here, please open
an issue.

---

## Why this is worth doing

Almost all public agent-failure research studies *benchmark tasks* — artificial
problems run in a harness. Very little studies what happens when agents are
*deployed* and doing real work for months. This analysis does the latter, and the
failure profile turns out to be meaningfully different.

## Headline findings (all reproducible from this repo)

**1. The platform got more reliable as it matured.**
The share of runs with a failure fell from **~14% (Feb-Mar) to 0.4% (May)** while
run volume grew roughly **4×** (1,900 → 7,200 runs/month). See
[`data/reliability_trends.json`](data/reliability_trends.json).

**2. Failures cluster in task completion and verification — not coordination.**
After cleaning (below), the leading failure modes are **task incompleteness
(1.1)** and **verification gaps (3.2/3.3)** — agents that don't fully finish, or
mark work done without checking it. The inter-agent modes MAST emphasizes for
benchmark multi-agent systems (2.3/2.4/2.5) are nearly absent, partly because
this platform's runs are predominantly single-agent-per-cycle. See
[`data/mast_distribution.json`](data/mast_distribution.json).

**3. We caught an infrastructure bug masquerading as an agent failure.**
An early read had *termination hangs* dominating. Investigation showed this was
an **infrastructure bug** confined to a two-week window (88% of all such hangs,
hitting 15 agents simultaneously, then vanishing) — not agent behavior. It
inflated the failure rate ~2.5×. Excluding it is the difference between a real
finding and an artifact. See [`data/reliability_trends.json`](data/reliability_trends.json)
(the spike is one month) and the method note below.

**4. Failures waste effort more than money.**
14.2% of total spend went to runs that hit a failure, but failing runs cost about
the *same per run* as clean ones despite using **2.4× the steps** — they fail on
cheap tool calls, not expensive tokens. See [`data/judge_cost_opus.json`](data/judge_cost_opus.json)
and the trends file.

## Method (and why it's honest)

- **Sampling.** A stratified sample of runs (over-sampling the failure regions),
  classified against the 14 MAST modes.
- **Classifier.** An LLM-judge reads each run's trajectory and assigns a primary
  MAST mode with cited evidence — judging the *run*, not isolated steps. It is a
  calibrated annotator, **not ground truth**.
- **Reliability measured, not assumed.** The judge was scored against a
  hand-labeled gold set (39 runs): **is_failure Cohen's kappa 0.797**,
  primary-mode exact match 71.8%. Disagreements are mostly between adjacent
  termination modes. This is disclosed, not hidden.
- **Data cleaning.** Outliers were identified by statistical signature
  (time-clustering **and** multi-agent simultaneous spread **and** volume —
  concentration alone is insufficient) and confirmed by reading step content.
  Only one window met the bar unambiguously and was excluded; weaker candidates
  were documented but **retained**, with a sensitivity check showing the headline
  is robust either way. Over-cleaning is its own form of dishonesty.
- **Re-weighting.** Because the sample over-represents failures by design, the
  distribution is reweighted to the run population before reporting rates.

## What this is NOT

- Not a claim about agents in general — it is **one platform**, a case study.
- Not authorship of MAST — the taxonomy and dataset are Cemri et al.'s.
- Not a precise distribution to three decimals — the judge is validated to
  "reasonable annotator" (kappa ~0.8), not to a paper's gold standard.

## Contents

```
data/      de-identified aggregate results (no trajectory text)
analysis/  the analysis code (DB export, classifier, scoring, anomaly detection)
```

Numbers are reproducible from the committed aggregates; the raw production
telemetry is not included and never leaves the operator's environment.

---

*Failure taxonomy: Cemri et al. 2025 (arXiv:2503.13657). This work applies and
extends it to production telemetry; it claims authorship of neither the taxonomy
nor the upstream benchmark dataset.*
