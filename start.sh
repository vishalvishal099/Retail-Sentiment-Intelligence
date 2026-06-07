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

# 1. Activate virtual environment
if [[ -d "$VENV_DIR" ]]; then
  source "$VENV_DIR/bin/activate"
  ok "Python venv activated ($VENV_DIR)"
else
  warn "No .venv found — using system Python"
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
  PORT=$API_PORT nohup python -m uvicorn src.dashboard.api:app \
    --host 0.0.0.0 --port "$API_PORT" --reload \
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

# 5. Summary
echo ""
log "All services running:"
echo -e "  ${GREEN}API:${NC}       http://localhost:$API_PORT"
echo -e "  ${GREEN}Dashboard:${NC} http://localhost:$FRONTEND_PORT"
echo ""
echo -e "  Logs:     $PROJECT_DIR/logs/"
echo -e "  Stop:     ${CYAN}./start.sh stop${NC}"
echo -e "  Status:   ${CYAN}./start.sh status${NC}"
