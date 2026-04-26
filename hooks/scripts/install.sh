#!/bin/bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${PLUGIN_ROOT}/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH. Install Python 3.10+ and re-run." >&2
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 10 ]; }; then
  echo "Python ${PY_VERSION} is too old. SqlScout needs 3.10+." >&2
  echo "Install a newer Python (e.g., 'brew install python@3.12') and re-run." >&2
  exit 1
fi

echo "Setting up SqlScout (Python ${PY_VERSION})..."

if [ ! -d "${VENV}" ]; then
  echo "  Creating virtualenv at ${VENV}"
  python3 -m venv "${VENV}"
fi

"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet -e "${PLUGIN_ROOT}/scripts[snowflake,databricks,llm]"

if ! "${VENV}/bin/sqlscout" --help >/dev/null 2>&1; then
  echo "Install completed but the 'sqlscout' CLI doesn't run. This usually means" >&2
  echo "a broken virtualenv. Try: rm -rf '${VENV}' && bash $0" >&2
  exit 1
fi

echo ""
echo "SqlScout installed."
echo ""
echo "Try it:"
echo "  ${VENV}/bin/sqlscout extract --sample --format markdown --output /tmp/out.md"
echo ""
echo "Wire up a real warehouse:"
echo "  ${VENV}/bin/sqlscout setup --platform snowflake     # also databricks, motherduck"
echo ""
echo "Schedule a weekly run with Slack delivery:"
echo "  export SQLSCOUT_ANTHROPIC_API_KEY=sk-ant-..."
echo "  export SQLSCOUT_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..."
echo "  ${VENV}/bin/sqlscout analyze --platform snowflake --days 7 --slack-mode alert --output /tmp/r.md"
