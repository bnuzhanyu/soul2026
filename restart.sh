#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"

API_PORT="${API_PORT:-4174}"
FE_PORTS=("${FE_PORT:-5173}" 5174)
API_RELOAD="${API_RELOAD:-0}"

mkdir -p "$LOG_DIR"

stop_pid_file() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    return
  fi

  if kill -0 "$pid" 2>/dev/null; then
    echo "Stopping $name pid $pid"
    kill "$pid" 2>/dev/null || true

    for _ in {1..20}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "Force stopping $name pid $pid"
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi

  rm -f "$pid_file"
}

kill_port() {
  local port="$1"
  local pids

  pids="$(lsof -ti "tcp:$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  echo "Clearing port $port: $pids"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done <<< "$pids"

  sleep 0.5

  pids="$(lsof -ti "tcp:$port" 2>/dev/null || true)"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true
  done <<< "$pids"
}

wait_for_port() {
  local name="$1"
  local port="$2"

  for _ in {1..40}; do
    if nc -z 127.0.0.1 "$port" >/dev/null 2>&1; then
      echo "$name is listening on http://127.0.0.1:$port"
      return
    fi
    sleep 0.25
  done

  echo "$name did not open port $port yet. Check logs in $LOG_DIR."
  return 1
}

restart_backend() {
  local mode="${1:-foreground}"
  stop_pid_file "backend" "$RUN_DIR/backend.pid"
  kill_port "$API_PORT"

  echo "Starting backend..."
  cd "$ROOT_DIR"
  api_cmd=(uv run uvicorn backend.jomo_backend.app:app --host 127.0.0.1 --port "$API_PORT")
  if [[ "$API_RELOAD" == "1" || "$API_RELOAD" == "true" ]]; then
    api_cmd+=(--reload)
  fi

  if [[ "$mode" == "background" ]]; then
    nohup env UV_CACHE_DIR=.uv-cache "${api_cmd[@]}" > "$LOG_DIR/backend.log" 2>&1 &
    echo "$!" > "$RUN_DIR/backend.pid"
    wait_for_port "Backend" "$API_PORT"
    return
  fi

  echo "Backend will run in the foreground. Logs stream below."
  exec env UV_CACHE_DIR=.uv-cache "${api_cmd[@]}"
}

restart_frontend() {
  local mode="${1:-foreground}"
  stop_pid_file "frontend" "$RUN_DIR/frontend.pid"
  for port in "${FE_PORTS[@]}"; do
    kill_port "$port"
  done

  echo "Starting frontend..."
  cd "$ROOT_DIR"
  if [[ "$mode" == "background" ]]; then
    nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
    echo "$!" > "$RUN_DIR/frontend.pid"
    wait_for_port "Frontend" "${FE_PORTS[0]}"
    return
  fi

  echo "Frontend will run in the foreground. Logs stream below."
  exec npm run dev
}

usage() {
  cat <<EOF
Usage:
  ./restart.sh       Restart backend only, then run it in the foreground
  ./restart.sh fe    Restart backend in the background, then run frontend in the foreground

Environment overrides:
  API_PORT=4174
  API_RELOAD=0
  FE_PORT=5173
EOF
}

case "${1:-}" in
  "" | api | backend)
    restart_backend
    ;;
  fe | frontend | all)
    restart_backend background
    restart_frontend
    ;;
  -h | --help | help)
    usage
    ;;
  *)
    echo "Unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac
