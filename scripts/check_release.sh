#!/usr/bin/env bash
# Same read-only validation and isolated artifact build locally, in PRs and in Pages.
set -euo pipefail
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python scripts/release_preflight.py --mode release
python -m pytest -q \
  tests/test_actions_pinning.py \
  tests/test_release_preflight.py \
  tests/test_actions_outcome.py \
  tests/test_actions_source_race.py \
  tests/test_watchdog_publication_recovery.py \
  tests/test_config.py \
  tests/test_dashboard_freshness.py \
  tests/test_dashboard_monotonic.py \
  tests/test_docs_contract.py \
  tests/test_publication_security.py \
  tests/test_automation_admission.py \
  tests/test_latest_session_repair.py \
  tests/test_index_history_repair.py \
  tests/test_scheduled_recovery.py
python scripts/validate_integrated_publication.py site
python -m factor_lab.publication_security site
python -m pytest -q tests/test_integrated*.py
npm ci --ignore-scripts
node --test scripts/test_integrated_web.cjs
for test in scripts/test_integrated*dom.cjs; do
  node "$test" site/data/integrated-result.json
done
python -m factor_lab.publication_security docs
python scripts/build_integrated_publication.py --output "${1:-public}"
python -m factor_lab.publication_security "${1:-public}"
node --check docs/assets/dashboard.js
MFL_TEST_PAYLOAD=docs/data/grid/v1/latest.json node scripts/test_web_contract.mjs
MFL_TEST_PAYLOAD=docs/data/grid/v1/latest.json node scripts/test_common_design_v1_dom.mjs
MFL_TEST_PAYLOAD=docs/data/grid/v1/latest.json node scripts/test_static_web_loader_contract.mjs
