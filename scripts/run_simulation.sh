#!/usr/bin/env bash
set -euo pipefail

export TRADING_ENV=simulation
exec uv run trading-cli --environment-config config/simulation.example.yaml

