#!/usr/bin/env bash
set -euo pipefail

# End-to-end smoke: submits a ticker via the live NextJS dev server,
# waits for the row to complete, prints the result.

TICKER="${1:-AAPL}"
DEPTH="${2:-quick}"
BASE="${BASE:-http://localhost:3000}"

echo "Submitting $TICKER (depth: $DEPTH)..."
JOB=$(curl -s -X POST "$BASE/api/jobs" \
  -H 'content-type: application/json' \
  -d "{\"ticker\":\"$TICKER\",\"depth\":\"$DEPTH\"}" | jq -r .jobId)
echo "Job id: $JOB"

echo "Polling..."
for i in $(seq 1 60); do
  RESP=$(curl -s "$BASE/api/status/$JOB")
  STATUS=$(echo "$RESP" | jq -r .status)
  printf "  [%02d] status=%s\n" "$i" "$STATUS"
  if [[ "$STATUS" == "complete" || "$STATUS" == "failed" ]]; then
    echo "$RESP" | jq .
    exit 0
  fi
  sleep 3
done

echo "Timed out waiting for $JOB"
exit 1
