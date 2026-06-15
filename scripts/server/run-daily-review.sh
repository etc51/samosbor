#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR"
source .venv/bin/activate

python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml paper-report --days 1
python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml tune-entry-hours --days 45 --min-trades-per-hour 3
python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml tune-strategy
