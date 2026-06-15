#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR"
source .venv/bin/activate

BASE_CONFIG="configs/server_tbank_cnyrubf_premium.toml"
EFFECTIVE_CONFIG="configs/server_tbank_cnyrubf_premium.effective.toml"
ACTIVE_CONFIG="$EFFECTIVE_CONFIG"

if [[ ! -f "$ROOT_DIR/$ACTIVE_CONFIG" ]]; then
  python -m samosbor.cli --config "$BASE_CONFIG" refresh-effective-config --output "$EFFECTIVE_CONFIG"
fi

python -m samosbor.cli --config "$ACTIVE_CONFIG" paper-report --days 1
python -m samosbor.cli --config "$ACTIVE_CONFIG" tune-entry-hours --days 45 --min-trades-per-hour 3
python -m samosbor.cli --config "$ACTIVE_CONFIG" bootstrap-entry-feedback
python -m samosbor.cli --config "$ACTIVE_CONFIG" tune-entry-quality --lookback-trades 40 --min-trades 8
python -m samosbor.cli --config "$ACTIVE_CONFIG" tune-strategy
python -m samosbor.cli --config "$ACTIVE_CONFIG" tune-exits
python -m samosbor.cli --config "$ACTIVE_CONFIG" refresh-effective-config --output "$EFFECTIVE_CONFIG"
