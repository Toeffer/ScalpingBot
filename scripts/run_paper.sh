#!/usr/bin/env bash
set -euo pipefail

export TRADING_ENV=paper
exec uv run trading-cli --environment-config config/paper.example.yaml

