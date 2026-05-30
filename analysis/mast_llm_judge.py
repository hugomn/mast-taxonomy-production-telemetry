"""LLM-judge MAST failure-mode classifier over sampled production runs.

Packages each run's trajectory (reasoning + tool calls + errors + observations)
into a compact prompt and asks Claude to assign MAST failure mode(s) WITH
evidence, or to mark the run as no-failure. Output is one verdict per run.

This is an LLM-judge, not ground truth. Its agreement is measured against a
small hand-labeled gold set (research/gold_labels.json) by
research/score_judge.py. Report the agreement honestly; do not present judge
output as accuracy.

Requires ANTHROPIC_API_KEY. Reads data/sampled_runs_full.jsonl (raw content,
gitignored). Writes research/judge_verdicts.jsonl.

    export ANTHROPIC_API_KEY=...
    python research/mast_llm_judge.py --limit 20   # small batch first
    python research/mast_llm_judge.py              # full sample
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

MODEL = "claude-opus-4-8"

# The 14 MAST modes (Cemri et al. 2025). Definitions are the judge's rubric.
MAST_MODES = {
    "1.1": "Disobey task specification / task incompleteness",
    "1.2": "Disobey role specification",
    "1.3": "Step repetition / goal or step conflicts",
    "1.4": "Loss of conversation history / incomplete specs",
    "1.5": "Unaware of termination conditions / unclear requirements",
    "2.1": "Conversation reset / agent incompetence",
    "2.2": "Fail to ask for clarification / overconfidence",
    "2.3": "Task derailment / coordination failure",
    "2.4": "Information withholding / communication failure",
    "2.5": "Ignored other agent's input / tool misuse",
    "2.6": "Action-reasoning mismatch / inefficient reasoning",
    "3.1": "Premature termination / hallucination",
    "3.2": "No or incomplete verification / context-window limits",
    "3.3": "Incorrect verification / cost escalation",
    "none": "No failure — the run completed its work without a failure mode",
}

SYSTEM = (
    "You are an expert annotator applying the MAST taxonomy (Multi-Agent System "
    "failure modes, Cemri et al. 2025) to execution traces from a production "
    "autonomous-agent platform. You assign the PRIMARY failure mode actually "
    "evidenced in the trace, plus any secondary modes, and you cite the specific "
    "step(s) that justify each. If the run shows no genuine failure, return "
    "mode 'none'. Be conservative: a single tool error that the agent recovers "
    "from is not necessarily a run-level failure. Judge the run, not isolated "
    "steps. Output strict JSON only."
)


def pack_trajectory(steps: list[dict], max_chars: int = 14000) -> str:
    """Render a run's steps into a compact, judge-readable trajectory."""
    steps = sorted(steps, key=lambda s: (s.get("created_at") or "", s.get("id") or ""))
    lines = []
    for i, s in enumerate(steps):
        c = s.get("content") or {}
        t = s["type"]
        st = s["status"]
        if t == "reasoning":
            out = c.get("output", "") if isinstance(c, dict) else ""
            body = (out or "").strip().replace("\n", " ")[:400]
            lines.append(f"[{i}] REASONING: {body}")
        elif t == "tool_call":
            name = c.get("tool_name", "?") if isinstance(c, dict) else "?"
            if st == "failed":
                err = c.get("error") if isinstance(c, dict) else None
                err_s = json.dumps(err)[:300] if err else ""
                lines.append(f"[{i}] TOOL {name} FAILED: {err_s}")
            elif st == "running":
                lines.append(f"[{i}] TOOL {name} STUCK (never completed)")
            else:
                inp = json.dumps(c.get("tool_input", {}))[:160] if isinstance(c, dict) else ""
                lines.append(f"[{i}] TOOL {name} ok input={inp}")
        elif t == "observation":
            msg = c.get("message", "") if isinstance(c, dict) else ""
            lines.append(f"[{i}] OBSERVE: {str(msg)[:200]}")
        elif t in ("pause_event", "resume_event"):
            lines.append(f"[{i}] {t.upper()}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        head = text[: max_chars // 2]
        tail = text[-max_chars // 2:]
        text = head + "\n... [trajectory truncated] ...\n" + tail
    return text


def build_prompt(run_id: str, stratum: str, traj: str) -> str:
    rubric = "\n".join(f"  {k}: {v}" for k, v in MAST_MODES.items())
    return (
        f"MAST failure modes:\n{rubric}\n\n"
        f"Run {run_id} (sampling stratum: {stratum}).\n"
        f"Trajectory ({traj.count(chr(10)) + 1} steps shown):\n\n{traj}\n\n"
        "Return strict JSON:\n"
        '{"primary_mode": "<code or none>", "secondary_modes": ["<code>", ...], '
        '"confidence": <0..1>, "evidence": "<short, cite step indices>", '
        '"is_failure": <true|false>}'
    )


def classify_run(client, run_id: str, stratum: str, steps: list[dict]) -> dict:
    traj = pack_trajectory(steps)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(run_id, stratum, traj)}],
    )
    raw = msg.content[0].text.strip()
    # Tolerate fenced JSON.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError:
        verdict = {"primary_mode": "parse_error", "raw": raw[:500]}
    verdict["run_id"] = run_id
    verdict["stratum"] = stratum
    verdict["n_steps"] = len(steps)
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/sampled_runs_full.jsonl")
    ap.add_argument("--out", default="research/judge_verdicts.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="classify only first N runs (smoke test)")
    ap.add_argument("--resume", action="store_true", help="skip runs already in --out and append the rest")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY to run the LLM-judge.")
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")

    runs: dict[str, list[dict]] = defaultdict(list)
    strat: dict[str, str] = {}
    with open(args.inp) as f:
        for line in f:
            r = json.loads(line)
            runs[r["run_id"]].append(r)
            strat[r["run_id"]] = r.get("_stratum")

    run_ids = sorted(runs)
    if args.limit:
        run_ids = run_ids[: args.limit]

    already: set[str] = set()
    file_mode = "w"
    if args.resume and os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    already.add(json.loads(line)["run_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
        file_mode = "a"
        print(f"resume: {len(already)} runs already judged; skipping them")

    todo = [r for r in run_ids if r not in already]
    client = anthropic.Anthropic()
    done = 0
    with open(args.out, file_mode) as fh:
        for rid in todo:
            verdict = classify_run(client, rid, strat[rid], runs[rid])
            fh.write(json.dumps(verdict) + "\n")
            fh.flush()
            done += 1
            print(f"  judged {done}/{len(todo)} — {rid[:8]} -> {verdict.get('primary_mode')}", flush=True)

    print(f"wrote {done} new verdicts to {args.out} ({len(already) + done} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
