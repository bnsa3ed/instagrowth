#!/usr/bin/env bash
# Run Instagrowth jobs locally without Docker (uses ./ .venv).
#
# Usage:
#   ./scripts/run-all-locally.sh              # full daily cycle (capture→anomaly→token→trends→topics)
#   ./scripts/run-all-locally.sh weekly       # weekly cycle (report + digest)
#   ./scripts/run-all-locally.sh content      # content engine (auto_draft + repurpose)
#   ./scripts/run-all-locally.sh <job_name>   # one job, e.g. daily_sync / cost_guard / token_health
#   ./scripts/run-all-locally.sh all          # everything
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || { echo "✗ $PY not found. Run: python3 -m venv .venv && .venv/bin/pip install -e ."; exit 1; }

run() { echo; echo "▶ app.jobs.$1"; "$PY" -m "app.jobs.$1"; }

case "${1:-daily}" in
  daily)
    run daily_sync
    run anomaly_detect
    run token_health
    run trend_scan
    run topic_ideation
    ;;
  weekly)
    run weekly_report      # also runs weekly_media_sync first
    run weekly_digest
    ;;
  content)
    run auto_draft
    run repurpose
    ;;
  all)
    run daily_sync
    run anomaly_detect
    run token_health
    run trend_scan
    run topic_ideation
    run weekly_report
    run weekly_digest
    run auto_draft
    run repurpose
    run cost_guard
    ;;
  *)
    run "$1"
    ;;
esac

echo; echo "✓ done"
