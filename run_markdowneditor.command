#!/bin/bash
set -euo pipefail

# Finder starts .command files in an arbitrary directory and with a reduced PATH.
PROJECT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export UV_CACHE_DIR="$PROJECT_ROOT/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PROJECT_ROOT/.uv-python"

if ! command -v uv >/dev/null 2>&1; then
  echo "[오류] uv를 찾을 수 없습니다. 터미널에서 brew install uv를 실행하세요."
  echo "설치 안내: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

# Forward paths unchanged: relative arguments are relative to the caller's directory.
uv sync --project "$PROJECT_ROOT" --locked --no-dev
exec uv run --project "$PROJECT_ROOT" --locked --no-dev markdowneditor "$@"
