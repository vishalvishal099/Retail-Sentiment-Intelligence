#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Retail Sentiment Intelligence — Start All Services
# ─────────────────────────────────────────────────────────────────────────────
# Usage:  ./start.sh          Start API + Frontend
#         ./start.sh stop     Stop all background services
#         ./start.sh status   Show running services
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
API_PORT="${API_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
PID_DIR="$PROJECT_DIR/.pids"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

mkdir -p "$PID_DIR"

log()  { echo -e "${CYAN}[start.sh]${NC} $1"; }
ok()   { echo -e "${GREEN}  ✔ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
err()  { echo -e "${RED}  ✖ $1${NC}"; }

# ─── Stop all services ───────────────────────────────────────────────────────
stop_services() {
  log "Stopping services..."
  local stopped=0

  if [[ -f "$PID_DIR/api.pid" ]]; then
    local pid
    pid=$(cat "$PID_DIR/api.pid")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && ok "API server (PID $pid) stopped" && stopped=$((stopped+1))
    fi
    rm -f "$PID_DIR/api.pid"
  fi

  if [[ -f "$PID_DIR/frontend.pid" ]]; then
    local pid
    pid=$(cat "$PID_DIR/frontend.pid")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && ok "Frontend dev server (PID $pid) stopped" && stopped=$((stopped+1))
    fi
    rm -f "$PID_DIR/frontend.pid"
  fi

  if [[ -f "$PID_DIR/scheduler.pid" ]]; then
    local pid
    pid=$(cat "$PID_DIR/scheduler.pid")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && ok "Scheduler (PID $pid) stopped" && stopped=$((stopped+1))
    fi
    rm -f "$PID_DIR/scheduler.pid"
  fi

  if [[ $stopped -eq 0 ]]; then
    warn "No running services found"
  fi
}

# ─── Status check ────────────────────────────────────────────────────────────
show_status() {
  log "Service status:"
  if [[ -f "$PID_DIR/api.pid" ]] && kill -0 "$(cat "$PID_DIR/api.pid")" 2>/dev/null; then
    ok "API server running on port $API_PORT (PID $(cat "$PID_DIR/api.pid"))"
  else
    err "API server not running"
  fi

  if [[ -f "$PID_DIR/frontend.pid" ]] && kill -0 "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null; then
    ok "Frontend dev server running on port $FRONTEND_PORT (PID $(cat "$PID_DIR/frontend.pid"))"
  else
    err "Frontend dev server not running"
  fi

  if [[ -f "$PID_DIR/scheduler.pid" ]] && kill -0 "$(cat "$PID_DIR/scheduler.pid")" 2>/dev/null; then
    ok "Scheduler running (PID $(cat "$PID_DIR/scheduler.pid"))"
  else
    warn "Scheduler not running — data will not auto-refresh"
  fi
}

# ─── Handle subcommands ──────────────────────────────────────────────────────
case "${1:-start}" in
  stop)
    stop_services
    exit 0
    ;;
  status)
    show_status
    exit 0
    ;;
  start|"")
    ;; # fall through to start logic below
  *)
    echo "Usage: $0 [start|stop|status]"
    exit 1
    ;;
esac

# ─── Start services ──────────────────────────────────────────────────────────
log "Starting Retail Sentiment Intelligence services..."
echo ""

# 1. Activate virtual environment (prefer .venv, fall back to conda/system)
if [[ -d "$VENV_DIR" ]] && "$VENV_DIR/bin/python" -c "import fastapi" 2>/dev/null; then
  source "$VENV_DIR/bin/activate"
  ok "Python venv activated ($VENV_DIR)"
else
  # Use whatever python is on PATH (e.g. conda base)
  ok "Using system Python ($(which python))"
fi

# 1b. Pick a Python for the pipeline subprocess. The API runs in .venv (fastapi
#     only); the pipeline needs transformers/torch. If PIPELINE_PYTHON is set,
#     honor it; else prefer /opt/miniconda3 if it has the ML stack; else fall
#     back to the active interpreter.
if [[ -z "${PIPELINE_PYTHON:-}" ]]; then
  if [[ -x "/opt/miniconda3/bin/python" ]] && /opt/miniconda3/bin/python -c "import transformers, torch" 2>/dev/null; then
    export PIPELINE_PYTHON="/opt/miniconda3/bin/python"
    ok "Pipeline interpreter → $PIPELINE_PYTHON (has transformers + torch)"
  else
    export PIPELINE_PYTHON="$(command -v python)"
    warn "PIPELINE_PYTHON not set and miniconda ML stack not found — using $PIPELINE_PYTHON"
  fi
else
  ok "Pipeline interpreter (override) → $PIPELINE_PYTHON"
fi

# 1c. HuggingFace offline mode. All models we use are already cached at
#     ~/.cache/huggingface/hub; skip Hub freshness HEAD checks so we don't
#     stall ~40s per model load whenever huggingface.co is unreachable
#     (off VPN, corp WiFi with DPI, etc.). To re-enable freshness checks
#     temporarily, `HF_HUB_OFFLINE=0 ./start.sh`.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
ok "HF offline mode: HF_HUB_OFFLINE=$HF_HUB_OFFLINE TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE"

# 1d. Ollama vision server. Required for image captioning (gemma3:4b). If it's
#     not already running, launch it in the background. Ollama itself skips
#     starting if it detects an existing instance, so this is idempotent.
if command -v ollama >/dev/null 2>&1; then
  if curl -s -o /dev/null --max-time 2 http://localhost:11434/api/tags; then
    ok "Ollama already running on http://localhost:11434"
  else
    log "Starting Ollama server in the background..."
    nohup ollama serve > "$PROJECT_DIR/logs/ollama.log" 2>&1 &
    disown
    # Give it a moment to bind the port
    for i in 1 2 3 4 5; do
      sleep 1
      if curl -s -o /dev/null --max-time 1 http://localhost:11434/api/tags; then
        ok "Ollama started (log: logs/ollama.log)"
        break
      fi
      [[ $i -eq 5 ]] && warn "Ollama did not respond in 5s — image captioning will fall back until it's up"
    done
  fi
else
  warn "ollama CLI not found — vision captioning will be skipped. Install: brew install ollama"
fi

# 2. Check port availability
check_port() {
  if lsof -ti:"$1" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

# 3. Start API server (FastAPI + Uvicorn)
log "Starting API server on port $API_PORT..."
if ! check_port "$API_PORT"; then
  warn "Port $API_PORT already in use — checking if it's our API..."
  if curl -s "http://localhost:$API_PORT/" | grep -q "retail_sentiment"; then
    ok "API already running on port $API_PORT (reusing)"
    if lsof -ti:"$API_PORT" >/dev/null 2>&1; then
      lsof -ti:"$API_PORT" | head -1 > "$PID_DIR/api.pid"
    fi
  else
    err "Port $API_PORT occupied by another process. Set API_PORT=<port> or free it."
    exit 1
  fi
else
  cd "$PROJECT_DIR"
  DASHBOARD_PORT=$API_PORT nohup python -m src.dashboard.api \
    > "$PROJECT_DIR/logs/api.log" 2>&1 &
  echo $! > "$PID_DIR/api.pid"
  sleep 2
  if kill -0 "$(cat "$PID_DIR/api.pid")" 2>/dev/null; then
    ok "API server started (PID $(cat "$PID_DIR/api.pid")) → http://localhost:$API_PORT"
  else
    err "API server failed to start. Check logs/api.log"
    exit 1
  fi
fi

# 4. Start Frontend dev server (Vite)
log "Starting frontend dev server on port $FRONTEND_PORT..."
if ! check_port "$FRONTEND_PORT"; then
  warn "Port $FRONTEND_PORT already in use — checking if it's Vite..."
  if curl -s "http://localhost:$FRONTEND_PORT/" | grep -q "vite"; then
    ok "Frontend already running on port $FRONTEND_PORT (reusing)"
    if lsof -ti:"$FRONTEND_PORT" >/dev/null 2>&1; then
      lsof -ti:"$FRONTEND_PORT" | head -1 > "$PID_DIR/frontend.pid"
    fi
  else
    err "Port $FRONTEND_PORT occupied by another process. Set FRONTEND_PORT=<port> or free it."
    exit 1
  fi
else
  cd "$PROJECT_DIR/frontend"
  nohup npx vite --port "$FRONTEND_PORT" \
    > "$PROJECT_DIR/logs/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  sleep 3
  if kill -0 "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null; then
    ok "Frontend dev server started (PID $(cat "$PID_DIR/frontend.pid")) → http://localhost:$FRONTEND_PORT"
  else
    err "Frontend server failed to start. Check logs/frontend.log"
    exit 1
  fi
fi

# 5. Start APScheduler (auto-ingest every N minutes). Uses PIPELINE_PYTHON
#    (miniconda) so it has transformers/torch. Set SKIP_SCHEDULER=1 to skip.
cd "$PROJECT_DIR"
if [[ "${SKIP_SCHEDULER:-0}" == "1" ]]; then
  warn "SKIP_SCHEDULER=1 — scheduler not started; data will only refresh via manual runs"
elif [[ -f "$PID_DIR/scheduler.pid" ]] && kill -0 "$(cat "$PID_DIR/scheduler.pid" 2>/dev/null)" 2>/dev/null; then
  ok "Scheduler already running (PID $(cat "$PID_DIR/scheduler.pid"))"
else
  log "Starting APScheduler (auto-ingest on interval)..."
  nohup "$PIPELINE_PYTHON" -u scripts/scheduler.py \
    > "$PROJECT_DIR/logs/scheduler.log" 2>&1 &
  echo $! > "$PID_DIR/scheduler.pid"
  sleep 2
  if kill -0 "$(cat "$PID_DIR/scheduler.pid")" 2>/dev/null; then
    ok "Scheduler started (PID $(cat "$PID_DIR/scheduler.pid")) → logs/scheduler.log"
  else
    err "Scheduler failed to start. Check logs/scheduler.log"
    # Non-fatal: dashboard still works for manual runs.
  fi
fi

# 6. Summary
echo ""
log "All services running:"
echo -e "  ${GREEN}API:${NC}       http://localhost:$API_PORT"
echo -e "  ${GREEN}Dashboard:${NC} http://localhost:$FRONTEND_PORT"
echo -e "  ${GREEN}Scheduler:${NC} ${SKIP_SCHEDULER:+skipped}${SKIP_SCHEDULER:-auto-ingest running}"
echo ""
echo -e "  Logs:     $PROJECT_DIR/logs/"
echo -e "  Stop:     ${CYAN}./start.sh stop${NC}"
echo -e "  Status:   ${CYAN}./start.sh status${NC}"
