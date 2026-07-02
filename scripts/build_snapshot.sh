#!/usr/bin/env bash
set -euo pipefail

# Build and publish the Daytona snapshot.
# Requires the Daytona CLI installed and authenticated:
#   https://www.daytona.io/docs/getting-started/installation/

cd "$(dirname "$0")/.."

echo "Building stock-agent image..."
docker build -t stock-agent:v1 ./agent

echo "Publishing snapshot to Daytona..."
daytona snapshot push stock-agent:v1 --name stock-agent:v1

echo "Done."
