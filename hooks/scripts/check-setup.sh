#!/bin/bash
PLUGIN_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${PLUGIN_ROOT}/.venv"

if [ ! -f "${VENV}/bin/einblick" ]; then
  cat <<EOF
{"systemMessage": "Einblick is installed but Python dependencies are not set up yet. When the user invokes /einblick, run: bash ${PLUGIN_ROOT}/hooks/scripts/install.sh (takes about 30 seconds, creates a local venv at ${VENV}). Do not ask the user to run pip or python commands manually."}
EOF
fi
