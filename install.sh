#!/usr/bin/env bash
# =============================================================
#  就业服务平台 · 校园版 — Linux 离线安装脚本
#  所有运行时已内置，无需联网下载任何东西。
#  用法：sudo bash install.sh
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
PY="$SCRIPT_DIR/runtime/python/bin/python3"
CHROME="$SCRIPT_DIR/runtime/chrome/chrome"

if [ "$EUID" -ne 0 ]; then
  error "请用管理员权限运行：sudo bash install.sh"
  exit 1
fi

echo "=================================================="
echo "  就业服务平台 · 校园版 — 离线安装"
echo "  目录: $SCRIPT_DIR"
echo "=================================================="

# ── 1. 环境自检 ─────────────────────────────────────────────
section "1/5 环境自检"

[ -x "$PY" ] || { error "未找到内置 Python：$PY（请确认完整解压了整个包）"; exit 1; }
info "内置 Python: $($PY --version)"

if [ -x "$CHROME" ]; then
  info "内置 Chrome: $($CHROME --version 2>/dev/null | head -1)"
else
  warn "未找到内置 Chrome，社招爬虫将不可用（公考采集不受影响）"
fi

# ── 2. Chrome 系统共享库（唯一可能需要 apt 的部分）───────────
section "2/5 检查 Chrome 运行库"
MISSING=$(ldd "$CHROME" 2>/dev/null | grep -c 'not found' || echo 99)
if [ "$MISSING" != "0" ]; then
  warn "Chrome 缺少 $MISSING 个共享库，尝试用系统包管理器安装（仅此一步需要联网）..."
  if command -v apt-get &>/dev/null; then
    apt-get update -qq 2>/dev/null || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      libnss3 libgbm1 libasound2t64 fonts-liberation \
      libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libpango-1.0-0 libcairo2 \
      >/dev/null 2>&1 || \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      libnss3 libgbm1 libasound2 fonts-liberation \
      libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libpango-1.0-0 libcairo2 \
      >/dev/null 2>&1 || true
  elif command -v dnf &>/dev/null; then
    dnf install -y -q nss libgbm alsa-lib atk at-spi2-atk cups-libs libdrm \
      libxkbcommon libXcomposite libXdamage libXfixes libXrandr pango cairo \
      >/dev/null 2>&1 || true
  fi
  MISSING=$(ldd "$CHROME" 2>/dev/null | grep -c 'not found' || echo 99)
fi
if [ "$MISSING" = "0" ]; then
  info "共享库已就绪"
else
  warn "仍缺共享库。社招爬虫无法启动 Chrome，公考采集不受影响。"
  warn "修复方法：ldd $CHROME | grep 'not found' 查看缺失项并安装"
fi

# ── 3. 离线安装 Python 依赖 ──────────────────────────────────
section "3/5 安装 Python 依赖（离线，约 1 分钟）"
"$PY" -m pip install -q --no-index --find-links="$SCRIPT_DIR/wheels" pip 2>/dev/null || true
"$PY" -m pip install -q --no-index --find-links="$SCRIPT_DIR/wheels" \
  fastapi uvicorn pydantic httpx PyPDF2 pdfplumber pymupdf python-docx \
  python-multipart "python-jose[cryptography]" bcrypt schedule requests \
  beautifulsoup4 lxml pandas openpyxl selenium
"$PY" -c "import fastapi, uvicorn, selenium, pandas; print('  依赖校验通过')"
info "依赖安装完成"

# ── 4. 首次初始化：设置管理员密码 ────────────────────────────
section "4/5 初始化"
if [ ! -f "data/.initialized" ]; then
  "$PY" init_admin.py
else
  info "已初始化过，跳过"
fi

# ── 5. systemd 服务 + 防火墙 ────────────────────────────────
section "5/5 配置服务与防火墙"

cat > /etc/systemd/system/jobboard.service <<EOF
[Unit]
Description=就业服务平台（校园版）
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PORT=$PORT
Environment=PYTHONIOENCODING=utf-8
ExecStart=$PY serve.py --background
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable jobboard >/dev/null 2>&1
systemctl restart jobboard
sleep 4

if systemctl is-active --quiet jobboard; then
  info "服务已启动并设置开机自启（崩溃自动重启）"
else
  error "服务启动失败，查看日志：journalctl -u jobboard -n 50 --no-pager"
  exit 1
fi

if command -v ufw &>/dev/null; then
  ufw allow $PORT/tcp >/dev/null 2>&1 && info "ufw 已放行 $PORT" || true
elif command -v firewall-cmd &>/dev/null; then
  firewall-cmd --permanent --add-port=$PORT/tcp >/dev/null 2>&1 && \
    firewall-cmd --reload >/dev/null 2>&1 && info "firewalld 已放行 $PORT" || true
fi

LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
LAN_IP=${LAN_IP:-127.0.0.1}

echo ""
echo "=================================================="
echo "  安装完成 🎉"
echo "=================================================="
cat <<EOF

  ┌────────────────────────────────────────────────┐
  │  学生入口：http://$LAN_IP:$PORT/
  │  管理后台：http://$LAN_IP:$PORT/admin.html
  └────────────────────────────────────────────────┘

  ☁️  云服务器注意：还需到云控制台「安全组」放行 $PORT 端口！

  运维命令：
    systemctl status jobboard     查看状态
    journalctl -u jobboard -f     查看日志
    systemctl restart jobboard    重启

  下一步（管理后台内完成）：
    1. 爬虫系统 → 社招爬虫：配置关键词，开启定时采集
    2. 系统设置：配置 SMTP 邮件服务
    3. 数据源健康：确认各数据源状态

EOF
