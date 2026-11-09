#!/usr/bin/env bash
# VideoDoc 的外部 whisper 客户端。
#
# 由 VIDEODOC_WHISPER_BIN 指向本脚本时启用，替代进程内的 pywhispercpp。
# 调用契约见 videodoc/integrations/transcribe.py::_run_cli：
#   whisper-remote <audio> -of <prefix>
# 只要求退出码为 0，并且写出 <prefix>.srt。
#
# 环境变量：
#   WHISPER_REMOTE_URL      默认 http://whisper-gpu:8080/inference
#   WHISPER_REMOTE_LANG     默认 auto（上游默认 en，中文视频必须显式 auto/zh）
#   WHISPER_REMOTE_TIMEOUT  默认 1800 秒
set -Eeuo pipefail

audio=""
prefix=""

while [ $# -gt 0 ]; do
  case "$1" in
    -of)
      [ $# -ge 2 ] || { echo "缺少 -of 的参数" >&2; exit 2; }
      prefix="$2"
      shift 2
      ;;
    *)
      audio="$1"
      shift
      ;;
  esac
done

: "${WHISPER_REMOTE_URL:=http://whisper-gpu:8080/inference}"
: "${WHISPER_REMOTE_LANG:=auto}"
: "${WHISPER_REMOTE_TIMEOUT:=1800}"

if [ -z "$audio" ] || [ ! -f "$audio" ]; then
  echo "音频文件不存在: ${audio:-<空>}" >&2
  exit 2
fi
if [ -z "$prefix" ]; then
  echo "缺少 -of 输出前缀" >&2
  exit 2
fi

tmp="$(mktemp "${prefix}.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

# response_format=srt 让服务端直接返回 SRT；
# 漏掉这个字段会拿到 JSON，VideoDoc 会判定「没有生成 transcript.srt」。
curl -sS --fail --max-time "$WHISPER_REMOTE_TIMEOUT" \
  -X POST "$WHISPER_REMOTE_URL" \
  -F "file=@${audio}" \
  -F "response_format=srt" \
  -F "language=${WHISPER_REMOTE_LANG}" \
  -o "$tmp" || {
    echo "调用 whisper 服务失败: ${WHISPER_REMOTE_URL}" >&2
    exit 3
  }

if [ ! -s "$tmp" ]; then
  echo "whisper 服务返回空内容" >&2
  exit 4
fi

mv -f "$tmp" "${prefix}.srt"
