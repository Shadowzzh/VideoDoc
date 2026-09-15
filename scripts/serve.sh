#!/bin/bash
# 启动 VideoDoc；用法：./scripts/serve.sh [端口]
#
# 依赖：Python 3.11+、Node 20.19+、pnpm。前端是主界面，必须先构建。
#
# 配置来源（后载入的不覆盖已存在的变量）：
#   1. 真实环境变量 / shell 导出
#   2. $VIDEODOC_ENV_FILE（默认 <项目根>/.env）
#   3. $VIDEODOC_SECRETS_FILE（可选，集中存放密钥的文件）
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# ---- 1. 先载入配置，后面的变量解析才能被环境文件覆盖 ----
ENV_FILE="${VIDEODOC_ENV_FILE:-$PROJECT_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
if [ -n "${VIDEODOC_SECRETS_FILE:-}" ] && [ -f "$VIDEODOC_SECRETS_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$VIDEODOC_SECRETS_FILE"
  set +a
fi

# ---- 2. 解析路径与端口 ----
PORT="${1:-${VIDEODOC_PORT:-8765}}"
HOST="${VIDEODOC_HOST:-0.0.0.0}"
VENV="${VIDEODOC_VENV:-$PROJECT_ROOT/.venv}"
PYTHON_BIN="${VIDEODOC_PYTHON:-$(command -v python3 || true)}"
PNPM_BIN="${VIDEODOC_PNPM:-$(command -v pnpm || true)}"

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "VideoDoc 需要 Python 3.11+，请先安装 python3。" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "VideoDoc 需要 Python 3.11+，当前为: $("$PYTHON_BIN" --version)" >&2
  exit 1
fi

# ---- 3. Python 环境 ----
if [ ! -x "$VENV/bin/python" ]; then
  echo "创建 venv: $VENV" >&2
  "$PYTHON_BIN" -m venv "$VENV"
fi
if ! "$VENV/bin/python" -c 'import flask, markdown, yt_dlp, claude_real_video, pywhispercpp' >/dev/null 2>&1; then
  echo "安装 Python 依赖 ..." >&2
  "$VENV/bin/pip" install -q -e "$PROJECT_ROOT"
fi

# ---- 4. 前端构建（主界面，必需）----
if [ -z "$PNPM_BIN" ]; then
  echo "VideoDoc 需要 pnpm 构建前端，请先安装 Node 20.19+ 与 pnpm。" >&2
  exit 1
fi
"$PNPM_BIN" --dir frontend install --frozen-lockfile --prefer-offline
"$PNPM_BIN" --dir frontend build

# ---- 5. 提示缺失的 LLM Key（不阻止启动，已完成的阶段仍可查看）----
if [ -z "${VIDEODOC_LLM_API_KEY:-}" ] && [ -z "${OPENCODE_GO_API_KEY:-}" ]; then
  echo "提示：未检测到 LLM API Key（VIDEODOC_LLM_API_KEY），大纲与正文生成会失败。" >&2
fi

exec "$VENV/bin/python" -m videodoc.server --port "$PORT" --host "$HOST"
