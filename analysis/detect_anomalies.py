"""Detect infra-bug-shaped anomalies in production tool failures.

No deploy/PR timeline is available, so the data is the ground truth. A genuine
infrastructure bug has a specific signature, and ALL THREE parts are required —
concentration alone is not enough (a single-agent tool used heavily for one week
also concentrates):

  1. TIME-CLUSTERED  — a large share of a tool's failures fall in one short window.
  2. MULTI-AGENT     — many distinct agents fail simultaneously in that window
                       (a bug hits everyone; behaviour concentrates in few agents).
  3. NON-TRIVIAL     — enough volume to matter.

Output ranks failing tools and flags the ones meeting all three. Confirmed
windows go in data_exclusions.json; the Jan complete_cycle bug is the only one
that met the bar unambiguously. Weaker signals are reported, not auto-excluded —
over-cleaning is its own dishonesty.

Read-only. Credentials from DB_* / PLATFORM_DB_* env.

    python research/detect_anomalies.py --min-fails 20 --peak-pct 50 --min-agents 4
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-fails", type=int, default=20, help="min total failures to consider a tool")
    ap.add_argument("--peak-pct", type=int, default=50, help="flag if >= this %% of fails are in one week")
    ap.add_argument("--min-agents", type=int, default=4, help="flag only if peak week hits >= this many agents")
    args = ap.parse_args()

    try:
        import psycopg
    except ImportError:
        sys.exit("psycopg required")

    user = os.environ.get("DB_USER") or os.environ.get("PLATFORM_DB_USER")
    pw = os.environ.get("DB_PASSWORD") or os.environ.get("PLATFORM_DB_PASSWORD")
    host = os.environ.get("DB_HOST") or os.environ.get("PLATFORM_DB_HOST")
    port = os.environ.get("DB_PORT") or os.environ.get("PLATFORM_DB_PORT")
    name = os.environ.get("DB_NAME") or os.environ.get("PLATFORM_DB_NAME")
    if not all([user, pw, host, port, name]):
        sys.exit("Set DB_* (or PLATFORM_DB_*) env vars.")
    dsn = f"postgresql://{user}:{pw}@{host}:{port}/{name}?sslmode=require"

    with psycopg.connect(dsn, autocommit=False, options="-c statement_timeout=120000") as c:
        with c.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                """
                WITH fails AS (
                  SELECT es.content->>'tool_name' AS tool,
                         date_trunc('week', es.created_at)::date AS wk,
                         es.run_id, r.agent_instance_id AS ai
                  FROM execution_steps es JOIN runs r ON r.id = es.run_id
                  WHERE es.type='tool_call' AND es.status IN ('failed','running')
                ),
                tot AS (SELECT tool, count(*) total FROM fails GROUP BY tool),
                wk  AS (SELECT tool, wk, count(*) n, count(DISTINCT ai) agents FROM fails GROUP BY tool, wk),
                peak AS (
                  SELECT DISTINCT ON (tool) tool, wk peak_wk, n peak_n, agents peak_agents
                  FROM wk ORDER BY tool, n DESC
                )
                SELECT t.tool, t.total, p.peak_wk, p.peak_n, p.peak_agents,
                       round(100.0*p.peak_n/t.total) pct
                FROM tot t JOIN peak p USING(tool)
                WHERE t.total >= %s
                ORDER BY pct DESC, t.total DESC
                """,
                (args.min_fails,),
            )
            rows = cur.fetchall()
        c.rollback()

    print(f"{'tool':22} {'fails':>6} {'peak_wk':>11} {'pk_n':>5} {'agents':>7} {'%pk':>4}  verdict")
    flagged = []
    for tool, total, wk, n, agents, pct in rows:
        if pct >= args.peak_pct and agents >= args.min_agents:
            verdict = "INFRA-BUG-SHAPED (cluster + multi-agent)"
            flagged.append((tool, str(wk), n, agents))
        elif pct >= args.peak_pct:
            verdict = f"concentrated but only {agents} agent(s) — likely single-project behaviour"
        else:
            verdict = "spread — behavioural"
        print(f"{(tool or '?')[:22]:22} {total:6} {str(wk):>11} {n:5} {agents:7} {int(pct):3}%  {verdict}")

    print()
    if flagged:
        print("FLAGGED windows (review before excluding — concentration + multi-agent):")
        for tool, wk, n, agents in flagged:
            print(f"  {tool}: week of {wk}, {n} fails across {agents} agents")
        print("\nExclude ONLY those confirmed by reading step content. Over-cleaning "
              "(dropping inconvenient data) is its own form of dishonesty.")
    else:
        print("No tool met both concentration and multi-agent thresholds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
