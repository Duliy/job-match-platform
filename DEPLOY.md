# 招聘信息采集平台 - 部署文档

> 适用环境：学校局域网服务器（Linux / Windows）
> 访问范围：局域网内任意设备，无需公网

---

## 快速开始（3 分钟部署）

### 方式一：Linux 服务器

```bash
# 1. 把项目文件夹上传到服务器
scp -r job-board/ ubuntu@192.168.x.x:/opt/job-board

# 2. 登录服务器，进入目录
ssh ubuntu@192.168.x.x
cd /opt/job-board

# 3. 给脚本加执行权限
chmod +x start.sh upload_cookies.sh

# 4. 一键启动
bash start.sh
```

启动后终端会显示访问地址，例如：
```
前端界面：http://192.168.1.100:8765
管理后台：http://192.168.1.100:8765/admin.html
```

**把这个地址发给同学，直接浏览器打开即可。**

---

### 方式二：Windows 服务器

1. 把 `job-board` 文件夹复制到服务器
2. 双击 `一键启动.bat`
3. 窗口会显示局域网 IP 和访问地址
4. 发给同学，浏览器打开

---

## 首次使用：完成平台登录（可选）

> 前程无忧 + 实习僧 **不需要登录**，匿名直接采集。
> 猎聘网、智联招聘需要 Cookie 才能采集完整数据。

**在你的 Windows 本地机器上操作：**

1. 双击 `手动登录采集.bat`
2. 浏览器会依次打开各平台，在浏览器里完成登录
3. 登录后按 Enter，Cookie 自动保存到 `cookies/` 目录
4. 把 Cookie 传到服务器：

```powershell
# PowerShell 里执行
scp -r cookies/ ubuntu@192.168.x.x:/opt/job-board/
```

5. 在服务器验证：
```bash
bash upload_cookies.sh check
```

---

## 开机自启（Linux，可选）

```bash
# 修改服务文件里的路径（默认是 /opt/job-board）
sudo nano job-board-api.service
sudo nano job-board-web.service

# 安装到 systemd
sudo cp job-board-api.service /etc/systemd/system/
sudo cp job-board-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable job-board-api job-board-web
sudo systemctl start  job-board-api job-board-web

# 验证
sudo systemctl status job-board-api
```

---

## 日常操作命令（Linux）

| 操作 | 命令 |
|------|------|
| 启动 | `bash start.sh` |
| 停止 | `bash start.sh stop` |
| 重启 | `bash start.sh restart` |
| 查看日志 | `bash start.sh log` |
| 检查 Cookie | `bash upload_cookies.sh check` |

---

## 系统要求

| 组件 | 要求 |
|------|------|
| Python | 3.8 或以上（`python3 --version`） |
| Chrome/Chromium | 社招爬虫需要（考公爬虫不需要） |
| 内存 | 建议 1GB 以上 |
| 磁盘 | 100MB 以上 |
| 网络 | 能访问 51job、猎聘、实习僧等招聘网站 |

**Linux 安装 Chrome：**
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y chromium-browser

# 或 Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt-get -f install
```

---

## 端口说明

| 端口 | 用途 |
|------|------|
| `8765` | 前端页面（用户访问这个） |
| `5000` | Flask API（前端自动连接，不用手动访问） |

如果端口被占用，脚本会自动释放。也可以手动修改 `start.sh` / `一键启动.bat` 里的 `WEB_PORT` 和 `API_PORT` 变量。

---

## 管理员密码

默认密码：`admin123`

修改方法（推荐）：
```bash
# Linux - 在 start.sh 里加一行，或启动时指定
ADMIN_PASSWORD=你的新密码 bash start.sh

# Windows - 在 一键启动.bat 里 python schedule_api.py 前加：
set ADMIN_PASSWORD=你的新密码
```

---

## 目录结构

```
job-board/
├── 一键启动.bat          ← Windows 双击启动
├── start.sh              ← Linux 一键启动
├── upload_cookies.sh     ← Cookie 上传/验证
├── 手动登录采集.bat       ← 本地登录获取 Cookie
├── schedule_api.py       ← Flask 后端（定时调度）
├── login_helper.py       ← 社招爬虫主程序
├── gongkao_crawler.py    ← 考公考编爬虫
├── requirements.txt      ← Python 依赖
├── index.html            ← 前端主页面
├── admin.html            ← 管理后台
├── job-board-api.service ← Linux systemd 服务（API）
├── job-board-web.service ← Linux systemd 服务（前端）
├── data/                 ← 采集数据（自动生成）
│   ├── jobs_latest.json
│   └── gk_jobs_latest.json
└── cookies/              ← 登录 Cookie（从本地上传）
    ├── 51job.json
    └── liepin.json
```

---

## 常见问题

**Q：其他同学打开页面显示空白/没数据？**
A：说明还没采集过。去管理后台 → 配置关键词 → 点"立即采集一次"。

**Q：社招爬虫报错"Chrome 未找到"？**
A：安装 chromium：`sudo apt install chromium-browser`

**Q：考公爬虫不需要 Chrome**，HTTP 直接请求，在任何服务器都能跑。

**Q：Cookie 失效了？**
A：Cookie 一般 7 天有效。在 Windows 本地重新运行`手动登录采集.bat`，再 `scp` 传上去。

**Q：停止服务后数据还在吗？**
A：在。数据保存在 `data/` 目录的 JSON 和 Excel 文件里，重启服务后自动读取。

**Q：想换端口？**
A：Linux 修改 `start.sh` 头部的 `API_PORT` 和 `WEB_PORT`；Windows 修改 `一键启动.bat` 里对应行。
