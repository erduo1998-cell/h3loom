#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly STACK_ROOT=/root/autodl-tmp/h3-stack
readonly ENV_ROOT="$STACK_ROOT/env"
readonly COMFY_ROOT="$STACK_ROOT/ComfyUI"
readonly RUN_ROOT="$STACK_ROOT/run"
readonly LOG_ROOT="$STACK_ROOT/logs"

export PATH="$ENV_ROOT/bin:$PATH"

mkdir -p "$RUN_ROOT" "$LOG_ROOT"

if [[ -f "$RUN_ROOT/comfy.pid" ]]; then
  old_pid=$(cat "$RUN_ROOT/comfy.pid")
  if kill -0 "$old_pid" 2>/dev/null; then
    printf 'ComfyUI already running as PID %s\n' "$old_pid"
    exit 0
  fi
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
cd "$COMFY_ROOT"
nohup "$ENV_ROOT/bin/python" main.py \
  --listen 127.0.0.1 \
  --port 8188 \
  --cache-none \
  --mmap-torch-files \
  --disable-pinned-memory \
  > "$LOG_ROOT/comfy-$stamp.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$RUN_ROOT/comfy.pid"
printf '%s\n' "$LOG_ROOT/comfy-$stamp.log" > "$RUN_ROOT/comfy.log.path"

for _ in $(seq 1 120); do
  if curl --fail --silent --max-time 5 http://127.0.0.1:8188/system_stats >/dev/null; then
    printf 'ComfyUI ready as PID %s\n' "$pid"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    tail -n 120 "$LOG_ROOT/comfy-$stamp.log" >&2
    exit 1
  fi
  sleep 2
done

tail -n 120 "$LOG_ROOT/comfy-$stamp.log" >&2
kill "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
rm -f "$RUN_ROOT/comfy.pid"
exit 1
