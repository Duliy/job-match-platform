#!/usr/bin/env bash
# =============================================================
#  招聘信息采集平台 - Linux 一键启动脚本
#  用法：bash start.sh
#  停止：bash start.sh stop
#  查看日志：bash start.sh log
# =============================================================

# 注意：不用 set -e，因为 lsof / kill 等命令在找不到进程时返回非零
# 改为在关键步骤手动判断

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

API_PORT=5000
WEB_PORT=8765
PID_FILE="$SCRIPT_DIR/.pids"
LOG_FILE="$SCRIPT_DIR/server.log"

# ---------- 颜色输出 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[OK]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[!!]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC} $*"; }
section() { echo -e "\n${CYAN}>>> $*${NC}"; }

# ============================================================
#  stop / log 子命令
# ============================================================
if [ "$1" = "stop" ]; then
    section "停止服务"
    if [ -f "$PID_FILE" ]; then
        while IFS= read -r pid; do
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" && info "已停止进程 $pid"
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    else
        warn "没有找到运行中的服务（.pids 文件不存在）"
    fi
    # 也尝试按端口杀掉
    for port in $API_PORT $WEB_PORT; do
        pid=$(lsof -ti tcp:"$port" 2>/dev/null) || pid=""
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
            info "已释放端口 $port (pid=$pid)"
        fi
    done
    echo "服务已停止。"
    exit 0
fi

if [ "$1" = "log" ]; then
    tail -f "$LOG_FILE"
    exit 0
fi

if [ "$1" = "restart" ]; then
    bash "$0" stop
    sleep 1
    exec bash "$0"
fi

# ============================================================
#  启动流程
# ============================================================
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║    西南大学商贸学院学生就业服务平台       ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ---------- 1. 检查 Python ----------
section "1/5  检查 Python 环境"
if ! command -v python3 &>/dev/null; then
    error "未找到 python3，请先安装：sudo apt install python3 python3-pip"
    exit 1
fi
PY=$(command -v python3)
info "Python: $($PY --version)"

# ---------- 2. 检查/安装依赖 ----------
section "2/5  检查 Python 依赖"
if ! $PY -c "import flask, schedule, selenium" 2>/dev/null; then
    warn "缺少依赖，正在安装（需要网络）..."
    $PY -m pip install -r "$SCRIPT_DIR/requirements.txt" -q \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        || $PY -m pip install -r "$SCRIPT_DIR/requirements.txt" -q
    info "依赖安装完成"
else
    info "依赖已就绪"
fi

# ---------- 3. 检查 Chrome ----------
section "3/5  检查 Chrome / Chromium"
CHROME_BIN=""
for bin in google-chrome chromium-browser chromium chrome; do
    if command -v "$bin" &>/dev/null; then
        CHROME_BIN="$bin"
        break
    fi
done

if [ -z "$CHROME_BIN" ]; then
    warn "未检测到 Chrome/Chromium，社招爬虫需要它。"
    warn "安装方法（Ubuntu/Debian）："
    warn "  sudo apt update && sudo apt install -y chromium-browser"
    warn "  或者：sudo apt install -y google-chrome-stable"
    warn "考公爬虫（HTTP采集）不需要 Chrome，现在继续启动..."
else
    info "Chrome: $($CHROME_BIN --version 2>/dev/null || echo '已找到')"
fi

# ---------- 4. 检查端口 ----------
section "4/5  检查端口占用"
check_port() {
    local port=$1
    local pid
    pid=$(lsof -ti tcp:"$port" 2>/dev/null) || pid=""
    if [ -n "$pid" ]; then
        warn "端口 $port 已被进程 $pid 占用，尝试释放..."
        kill "$pid" 2>/dev/null || true
        sleep 1
        info "端口 $port 已释放"
    fi
}
check_port $API_PORT
check_port $WEB_PORT

# ---------- 5. 启动服务 ----------
section "5/5  启动服务"

# 创建 data 目录
mkdir -p "$SCRIPT_DIR/data" "$SCRIPT_DIR/cookies"

# 启动 Flask API（后台，日志追加到 server.log）
echo "" > "$PID_FILE"
nohup $PY "$SCRIPT_DIR/schedule_api.py" >> "$LOG_FILE" 2>&1 &
API_PID=$!
echo $API_PID >> "$PID_FILE"
info "Flask API 已启动（PID=$API_PID，端口=$API_PORT）"
sleep 1

# 验证 Flask 是否真的跑起来了
if ! kill -0 $API_PID 2>/dev/null; then
    error "Flask 启动失败，查看日志：tail $LOG_FILE"
    exit 1
fi

# 启动静态文件服务器（--bind 0.0.0.0 强制 IPv4，避免只监听 IPv6）
nohup $PY -m http.server $WEB_PORT --bind 0.0.0.0 --directory "$SCRIPT_DIR" >> "$LOG_FILE" 2>&1 &
WEB_PID=$!
echo $WEB_PID >> "$PID_FILE"
info "前端服务已启动（PID=$WEB_PID，端口=$WEB_PORT）"

# ---------- 输出访问地址 ----------
echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  服务已启动！局域网访问地址：                    ║"

# 取局域网 IP
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

printf "  ║  前端界面：http://%-28s  ║\n" "${LAN_IP}:${WEB_PORT}"
printf "  ║  管理后台：http://%-28s  ║\n" "${LAN_IP}:${WEB_PORT}/admin.html"
printf "  ║  API状态：  http://%-28s  ║\n" "${LAN_IP}:${API_PORT}/api/status"
echo "  ╠══════════════════════════════════════════════════╣"
echo "  ║  查看日志：bash start.sh log                     ║"
echo "  ║  停止服务：bash start.sh stop                    ║"
echo "  ║  重新启动：bash start.sh restart                 ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# 提示 Cookie
if [ ! -f "$SCRIPT_DIR/cookies/51job.json" ]; then
    echo -e "  ${YELLOW}[提示]${NC} 首次部署：请运行 bash upload_cookies.sh 上传登录 Cookie"
    echo ""
fi

echo "  服务在后台运行，关闭此窗口不影响服务。"
echo "  进程 ID 已保存到 .pids 文件。"
echo ""
