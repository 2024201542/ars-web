#!/usr/bin/env bash
# ============================================================
# ARS Web 部署脚本 (无需 Docker / nginx)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"
LOG_DIR="$SCRIPT_DIR/logs"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-80}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# -------- 环境检查 ----------
check_prereqs() {
  info "检查运行环境..."
  if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    error "Python 未安装"; exit 1
  fi
  PYTHON=$(command -v python3 || command -v python)
  info "Python: $($PYTHON --version)"

  if ! command -v node &>/dev/null; then
    error "Node.js 未安装"; exit 1
  fi
  info "Node.js: $(node --version)"

  if ! command -v claude &>/dev/null; then
    warn "claude CLI 未安装 (非 Anthropic 模型需要)"
  else
    info "Claude CLI: $(claude --version 2>&1 | head -1 || echo '已安装')"
  fi

  if ! command -v npm &>/dev/null; then
    error "npm 未安装"; exit 1
  fi
}

# -------- 安装依赖 ----------
install_deps() {
  info "安装后端依赖..."
  cd "$SCRIPT_DIR/backend"
  $PYTHON -m pip install -r requirements.txt -q 2>/dev/null || {
    warn "pip install 失败，尝试使用虚拟环境..."
    if [ ! -d ".venv" ]; then
      $PYTHON -m venv .venv
    fi
    source .venv/bin/activate
    pip install -r requirements.txt -q
  }

  info "安装前端依赖 + 构建..."
  cd "$SCRIPT_DIR/frontend"
  npm install --silent 2>/dev/null || npm install
  npm run build
}

# -------- 启动服务 ----------
start_backend() {
  info "启动后端 (端口 $BACKEND_PORT)..."
  mkdir -p "$PID_DIR" "$LOG_DIR"

  cd "$SCRIPT_DIR/backend"
  if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
  fi

  # 强杀旧进程
  if [ -f "$PID_DIR/backend.pid" ]; then
    kill "$(cat "$PID_DIR/backend.pid")" 2>/dev/null || true
    sleep 1
  fi

  nohup $PYTHON -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --workers 2 \
    --log-level info \
    > "$LOG_DIR/backend.log" 2>&1 &

  echo $! > "$PID_DIR/backend.pid"
  sleep 2

  # 健康检查
  if curl -sf "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
    info "后端启动成功"
  else
    warn "后端可能未就绪，查看日志: tail -f $LOG_DIR/backend.log"
  fi
}

start_frontend() {
  info "启动前端 (端口 $FRONTEND_PORT)..."

  if [ -f "$PID_DIR/frontend.pid" ]; then
    local old_pid
    old_pid=$(cat "$PID_DIR/frontend.pid")
    # 尝试用 Python 的 http.server 的进程
    kill "$old_pid" 2>/dev/null || true
    sleep 1
  fi

  cd "$SCRIPT_DIR/frontend/dist"

  # 使用 Python 内置 HTTP 服务器作为简易前端服务器
  # 支持 SPA 回退 (所有路径返回 index.html)
  nohup $PYTHON -c "
import http.server
import os
import urllib.parse

class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        # API 请求不处理
        if path.startswith('/api/') or path.startswith('/v1/'):
            self.send_error(404, 'Not Found')
            return
        # 静态文件
        file_path = '.' + path
        if path != '/' and os.path.isfile(file_path):
            return super().do_GET()
        # SPA fallback
        self.path = '/index.html'
        return super().do_GET()

    def log_message(self, fmt, *args):
        pass  # 静默日志

http.server.HTTPServer(('0.0.0.0', $FRONTEND_PORT), SPAHandler).serve_forever()
" > "$LOG_DIR/frontend.log" 2>&1 &

  echo $! > "$PID_DIR/frontend.pid"
  sleep 1

  if curl -sf "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1; then
    info "前端启动成功"
  else
    warn "前端可能未就绪"
  fi
}

# -------- 停止服务 ----------
stop_all() {
  info "停止所有服务..."
  for svc in backend frontend; do
    if [ -f "$PID_DIR/$svc.pid" ]; then
      local pid
      pid=$(cat "$PID_DIR/$svc.pid")
      kill "$pid" 2>/dev/null && info "已停止 $svc (PID $pid)" || true
      rm -f "$PID_DIR/$svc.pid"
    fi
  done
}

# -------- 状态查看 ----------
status_all() {
  echo "============ ARS Web 服务状态 ============"
  for svc in backend frontend; do
    if [ -f "$PID_DIR/$svc.pid" ]; then
      local pid
      pid=$(cat "$PID_DIR/$svc.pid")
      if kill -0 "$pid" 2>/dev/null; then
        echo -e "  $svc: ${GREEN}运行中${NC} (PID $pid)"
      else
        echo -e "  $svc: ${RED}已停止${NC} (PID 文件残留)"
      fi
    else
      echo -e "  $svc: ${YELLOW}未启动${NC}"
    fi
  done
  echo "=========================================="
}

# -------- 日志 ----------
tail_logs() {
  tail -f "$LOG_DIR/${1:-backend}.log" 2>/dev/null || warn "日志文件不存在"
}

# -------- 帮助信息 ----------
usage() {
  cat << 'EOF'
用法: ./deploy.sh <命令>

命令:
  start       安装依赖 + 构建 + 启动全部服务
  stop        停止全部服务
  restart     重启全部服务
  status      查看服务状态
  build       仅构建前端
  logs [名称] 查看日志 (backend / frontend)
  install     仅安装依赖 (不启动)

端口 (环境变量):
  BACKEND_PORT  后端端口 (默认 8000)
  FRONTEND_PORT 前端端口 (默认 80)

示例:
  ./deploy.sh start
  FRONTEND_PORT=3000 ./deploy.sh start
  ./deploy.sh logs backend
EOF
}

# -------- 入口 ----------
case "${1:-}" in
  start)
    check_prereqs
    install_deps
    start_backend
    start_frontend
    status_all
    echo ""
    info "部署完成!"
    echo "  前端: http://localhost:$FRONTEND_PORT"
    echo "  后端: http://localhost:$BACKEND_PORT"
    echo "  日志: tail -f $LOG_DIR/backend.log"
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    check_prereqs
    start_backend
    start_frontend
    status_all
    ;;
  status)
    status_all
    ;;
  build)
    info "构建前端..."
    cd "$SCRIPT_DIR/frontend"
    npm run build
    info "构建完成"
    ;;
  logs)
    tail_logs "${2:-backend}"
    ;;
  install)
    check_prereqs
    install_deps
    info "依赖安装完成"
    ;;
  *)
    usage
    ;;
esac
