#!/usr/bin/env bash
# Launch Open Interpreter OS mode with Gemini (Google AI Studio key).
#
# Do NOT use `interpreter --os`: in open-interpreter 0.4.3 that flag hard-codes
# Anthropic's Claude computer-use loop and ignores --model/--provider.
# Loading the os.py profile gives the same OS-control mode via litellm.
set -euo pipefail
cd "$(dirname "$0")"

# Load .env (GEMINI_API_KEY, etc) if present, without overriding vars already
# exported in the shell.
if [ -f .env ]; then
    while IFS='=' read -r key val; do
        case "$key" in ''|'#'*) continue ;; esac
        if [ -z "${!key:-}" ]; then
            export "$key=$val"
        fi
    done < <(grep -vE '^\s*(#|$)' .env)
fi

# litellm reads GEMINI_API_KEY; accept GOOGLE_API_KEY too.
export GEMINI_API_KEY="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}"
if [ -z "$GEMINI_API_KEY" ]; then
    echo "Set GEMINI_API_KEY in .env (or export it) first." >&2
    exit 1
fi

MODEL="${MODEL:-gemini/gemini-3.8-flash}"

exec .venv/bin/interpreter \
    --profile "$(pwd)/os_gemini_profile.py" \
    --model "$MODEL" \
    --context_window 1000000 \
    --max_tokens 8192 \
    "$@"
