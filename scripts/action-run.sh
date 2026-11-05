#!/usr/bin/env bash
set -euo pipefail
args=(--report "$RUNNER_TEMP/greenpr-report-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.json")
if [[ -n "${GREENPR_TEST_CMD:-}" ]]; then
  args+=(--test-cmd "$GREENPR_TEST_CMD")
fi
if [[ "${GREENPR_DRY_RUN:-true}" == true ]]; then
  args+=(--dry-run)
fi
if [[ "${GREENPR_ENABLE_HEALING:-false}" == true ]]; then
  args+=(--enable-healing)
fi
python "$GREENPR_ACTION_PATH/remediate.py" "${args[@]}"
