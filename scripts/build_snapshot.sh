#!/usr/bin/env bash
set -euo pipefail

# Build and publish the Daytona snapshot.
# Requires the Daytona CLI installed and authenticated:
#   https://www.daytona.io/docs/getting-started/installation/

cd "$(dirname "$0")/.."

echo "Building stock-agent image..."
docker build -t stock-agent:v1 ./agent

# Daytona snapshots are name-immutable within an org. Delete the existing
# one (if any) so the push below doesn't 409 on re-runs. `|| true` covers
# the first-run case where no snapshot exists yet.
echo "Removing any existing stock-agent:v1 snapshot..."
daytona snapshot delete stock-agent:v1 || true

echo "Publishing snapshot to Daytona..."
daytona snapshot push stock-agent:v1 --name stock-agent:v1

echo "Done."
