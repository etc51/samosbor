#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/.venv/bin/activate"
exec python -m samosbor.dashboard \
  --config configs/server_tbank_cnyrubf_premium.toml \
  --effective-config configs/server_tbank_cnyrubf_premium.effective.toml \
  --host 0.0.0.0 \
  --port 8790
