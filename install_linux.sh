#!/usr/bin/env bash
# =============================================================
#  就业服务平台 · 校园版 — Linux 一键安装脚本
#  适用：Ubuntu 18.04+ / Debian 10+ / CentOS 8+ / Rocky / Alma
#  用法：sudo bash install_linux.sh
# =============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[OK]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[提示]${NC} $*"; }
error()   { echo -e "${RED}[错误]${NC} $*"; }
section() { echo -e "\n${CYAN}>>> $*${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8000

if [ "$EUID" -ne 0 ]; then
  error "请用管理员权限运行：sudo bash install_linux.sh"
  exit 1
fi

echo "=================================================="
echo "  就业服务平台 · 校园版 — Linux 一键安装"
echo "  目录: $SCRIPT_DIR"
echo "=================================================="

# ── 1. 系统依赖 ─────────────────────────────────────────────
section "1/6 安装系统依赖（Python / Chromium）"

if command -v apt-get &>/dev/null; then
  PKG="apt-get"
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip curl >/dev/null
  # Chromium（社招爬虫需要；公考爬虫不需要）
  if ! command -v chromium &>/dev/null && ! command -v chromium-browser &>/dev/null && ! command -v google-chrome &>/dev/null; then
    apt-get install -y -qq chromium-browser >/dev/null 2>&1 || \
    apt-get install -y -qq chromium >/dev/null 2>&1 || \
    warn "Chromium 自动安装失败，社招爬虫将不可用（公考采集不受影响）。可稍后手动安装：sudo apt install chromium"
  fi
  # chromedriver（与 chromium 配套）
  command -v chromedriver &>/dev/null || \
    apt-get install -y -qq chromium-driver >/dev/null 2>&1 || true
elif command -v dnf &>/dev/null; then
  PKG="dnf"
  dnf install -y -q python3 python3-pip curl >/dev/null
  command -v chromium &>/dev/null || dnf install -y -q chromium >/dev/null 2>&1 || \
    warn "Chromium 自动安装失败，社招爬虫将不可用（公考采集不受影响）"
  command -v chromedriver &>/dev/null || dnf install -y -q chromedriver >/dev/null 2>&1 || true
elif command -v yum &>/dev/null; then
  PKG="yum"
  yum install -y -q python3 python3-pip curl >/dev/null
  command -v chromium &>/dev/null || yum install -y -q chromium >/dev/null 2>&1 || \
    warn "Chromium 自动安装失败，社招爬虫将不可用（公考采集不受影响）"
else
  error "无法识别的包管理器，请手动安装 python3 和 chromium 后重试"
  exit 1
fi

PY=$(command -v python3)
info "Python: $($PY --version)"
if command -v chromium &>/dev/null; then info "Chromium: $(chromium --version 2>/dev/null | head -1)"
elif command -v chromium-browser &>/dev/null; then info "Chromium: $(chromium-browser --version 2>/dev/null | head -1)"
elif command -v google-chrome &>/dev/null; then info "Chrome: $(google-chrome --version 2>/dev/null | head -1)"
fi

# ── 2. Python 虚拟环境 + 依赖 ────────────────────────────────
section "2/6 创建虚拟环境并安装依赖（约 2-5 分钟）"

if [ ! -d ".venv" ]; then
  $PY -m venv .venv
fi
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

# 清华镜像加速（国内服务器）；失败时自动回退官方源
$VENV_PY -m pip install -q --upgrade pip \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || \
  $VENV_PY -m pip install -q --upgrade pip

$VENV_PY -m pip install -q -r requirements-portable.txt \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || \
  $VENV_PY -m pip install -q -r requirements-portable.txt

info "依赖安装完成"

# ── 3. 首次初始化：设置管理员密码 ────────────────────────────
section "3/6 初始化"
if [ ! -f "data/.initialized" ]; then
  $VENV_PY init_admin.py
else
  info "已初始化过，跳过（如需重置管理员密码，删除 data/.initialized 后重启安装）"
fi

# ── 4. systemd 服务 ─────────────────────────────────────────
section "4/6 配置 systemd 开机自启服务"

cat > /etc/systemd/system/jobboard.service <<EOF
[Unit]
Description=就业服务平台（校园版）
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PORT=$PORT
ExecStart=$VENV_PY serve.py --background
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable jobboard >/dev/null 2>&1
systemctl restart jobboard
sleep 3

if systemctl is-active --quiet jobboard; then
  info "服务已启动并设置开机自启"
else
  error "服务启动失败，查看日志：journalctl -u jobboard -n 50"
  exit 1
fi

# ── 5. 防火墙放行 ────────────────────────────────────────────
section "5/6 防火墙放行端口 $PORT"
if command -v ufw &>/dev/null; then
  ufw allow $PORT/tcp >/dev/null 2>&1 && info "ufw 已放行 $PORT" || warn "ufw 配置失败，请手动执行: ufw allow $PORT/tcp"
elif command -v firewall-cmd &>/dev/null; then
  firewall-cmd --permanent --add-port=$PORT/tcp >/dev/null 2>&1 && firewall-cmd --reload >/dev/null 2>&1 && \
    info "firewalld 已放行 $PORT" || warn "firewalld 配置失败，请手动执行: firewall-cmd --permanent --add-port=$PORT/tcp && firewall-cmd --reload"
else
  warn "未检测到 ufw/firewalld，如有防火墙请手动放行 $PORT 端口"
fi

# ── 6. 完成 ─────────────────────────────────────────────────
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
LAN_IP=${LAN_IP:-127.0.0.1}

section "6/6 安装完成 🎉"
cat <<EOF

  ┌────────────────────────────────────────────────┐
  │  学生入口：http://$LAN_IP:$PORT/
  │  管理后台：http://$LAN_IP:$PORT/admin.html
  └────────────────────────────────────────────────┘

  把「学生入口」地址发给同学即可。

  日常运维命令：
    查看状态   systemctl status jobboard
    查看日志   journalctl -u jobboard -f
    重启服务   systemctl restart jobboard
    停止服务   systemctl stop jobboard

  下一步（在管理后台完成）：
    1. 爬虫系统 → 社招爬虫：配置关键词，开启定时采集
    2. 系统设置：配置 SMTP 邮件服务（用于订阅推送）
    3. 数据源健康：随时查看各数据源状态

EOF
