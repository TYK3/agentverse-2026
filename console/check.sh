#!/usr/bin/env bash
# console lane check, run by CI (.github/workflows/ci.yml) and locally: bash console/check.sh
set -euo pipefail
cd "$(dirname "$0")"

npm install --no-audit --no-fund
npm run build
node test_smoke.js
npm test
