#!/usr/bin/env bash
# =============================================================
#  就业服务平台 · 校园版 — Linux 手动控制脚本
#  （不依赖 systemd 的场合使用；推荐优先用 install_linux.sh）
#  用法：
#    bash start.sh          # 前台启动（调试用，Ctrl+C 停止）
#    bash start.sh start    # 后台启动
#    bash start.sh stop     # 停止
#    bash start.sh restart  # 重启
#    bash start.sh status   # 状态
#    bash start.sh log      # 查看日志
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=${PORT:-8000}
PID_FILE="$SCRIPT_DIR/.jobboard.pid"
LOG_FILE="$SCRIPT_DIR/data/server.log"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"
SELF="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[OK]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[提示]${NC} $*"; }
error() { echo -e "${RED}[错误]${NC} $*"; }

# 选择 Python 解释器：优先虚拟环境
PY="$VENV_PY"
if [ ! -x "$PY" ]; then
  PY=$(command -v python3 || true)
fi
if [ -z "$PY" ]; then
  error "未找到 Python。请先运行: sudo bash install_linux.sh"
  exit 1
fi

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "$1" in
  start)
    if is_running; then
      warn "服务已在运行 (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    mkdir -p data
    PORT=$PORT nohup "$PY" serve.py --background >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    if is_running; then
      LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
      info "服务已启动 (PID $(cat "$PID_FILE"))"
      echo "  学生入口：http://${LAN_IP:-127.0.0.1}:$PORT/"
      echo "  管理后台：http://${LAN_IP:-127.0.0.1}:$PORT/admin.html"
    else
      error "启动失败，查看日志: tail -50 $LOG_FILE"
      rm -f "$PID_FILE"
      exit 1
    fi
    ;;
  stop)
    if is_running; then
      kill "$(cat "$PID_FILE")" && info "服务已停止"
      rm -f "$PID_FILE"
    else
      warn "服务未在运行"
    fi
    ;;
  restart)
    bash "$SELF" stop
    sleep 1
    bash "$SELF" start
    ;;
  status)
    if is_running; then
      info "运行中 (PID $(cat "$PID_FILE"))，端口 $PORT"
      curl -s -o /dev/null -w "  HTTP 探测: %{http_code}\n" "http://127.0.0.1:$PORT/" 2>/dev/null || true
    else
      warn "未运行"
    fi
    ;;
  log)
    tail -f "$LOG_FILE"
    ;;
  "")
    # 无参数：前台启动（调试用）
    echo "前台启动模式（Ctrl+C 停止）..."
    PORT=$PORT exec "$PY" serve.py
    ;;
  *)
    echo "用法: bash start.sh [start|stop|restart|status|log]"
    exit 1
    ;;
esac
