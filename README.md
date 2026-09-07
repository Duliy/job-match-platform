# 学院就业服务平台 · 校园交付版

> 西南大学商贸学院就业服务平台 —— 非商业化校园版
> 岗位采集 + AI 简历匹配 + 订阅推送，一条命令部署，辅导员零代码维护。

本分支（`delivery-campus`）是面向学院交付的非商业版本。
商业化版本（含 VIP/积分体系）保留在 `main` 分支与 `commercial-v1.0` 标签中。

---

## 与商业版的区别

| 维度 | 商业版 (main) | 校园版 (本分支) |
|---|---|---|
| 收费体系 | VIP / 积分 / CDK 充值 | **全部移除** |
| 岗位浏览 | 登录 + 积分 | **免登录免费** |
| AI 功能 | 平台统一 Key，扣积分 | **学生自带 DeepSeek Key**（存浏览器，服务器不留存） |
| 订阅推送 | VIP 专属 + AI 精排 | 全员可用，**SQL 粗筛免 Key** 邮件推送 |
| 架构 | FastAPI + Flask + Node 三进程 | **单 FastAPI 进程单端口** |
| 部署 | 手动装环境 | **Windows 便携包解压即用 / Linux 一键脚本** |

## 功能一览

- **岗位聚合**：前程无忧 / 实习僧（免登录）+ 智联 / 猎聘（Cookie）+ 31 省公考职位库（纯 HTTP）
- **AI 简历匹配**：SQL 粗筛 → LLM 精排，技能/经验/学历/薪资/地点五维评分 + 录用概率
- **简历深度分析**：优势/短板/修改建议/关键词优化
- **订阅推送**：学生上传简历绑定邮箱，系统定时扫描新岗位自动发邮件
- **管理后台**：数据源健康面板 / Cookie 网页上传 / 用户管理 / 爬虫调度 / 订阅推送配置

## 快速部署

### 方式一：Windows 便携包（零环境，推荐）

适合：学院 Windows 服务器，无人会装环境。

1. 从 Releases 或构建产物获取 `就业服务平台-校园版.zip`（内嵌 Python 3.8 + Chromium 109，兼容 Windows Server 2012 及以上）
2. 完整解压（**不要只拖出启动文件**）
3. 双击 `环境预检.bat` 自查
4. 双击 `启动系统.bat`，首次启动设置管理员密码
5. （建议）右键 `安装开机自启.bat` → 以管理员身份运行一次

详见包内《辅导员手册.md》。

**自行构建便携包**（需要 Linux 构建机 + 网络）：

```bash
python3 build_portable.py            # 完整构建（下载 Python/Chrome/vc_redist）
python3 build_portable.py --skip-downloads   # 仅刷新代码和种子数据
```

### 方式二：Linux 一键安装

适合：Ubuntu / Debian / CentOS / Rocky 服务器。

```bash
git clone -b delivery-campus https://github.com/Duliy/job-match-platform.git jobboard
cd jobboard
sudo bash install_linux.sh
```

脚本自动完成：系统依赖 → 虚拟环境 → 管理员密码向导 → systemd 自启 → 防火墙放行。

日常运维：`systemctl status|restart|stop jobboard`，日志 `journalctl -u jobboard -f`。
不用 systemd 可用手动脚本：`bash start.sh start|stop|restart|status|log`。

详见 [Linux部署.md](Linux部署.md)。

## 部署后必做

1. 管理后台 → 爬虫系统 → 社招爬虫：配置关键词，开启定时采集，点「立即采集一次」
2. 系统设置：配置 SMTP 邮件服务（订阅推送需要，推荐 QQ/163 邮箱授权码）
3. 数据源健康：确认各数据源状态正常

## 学生使用

- **浏览岗位**：打开网址即可，无需注册
- **AI 匹配/分析**：注册登录 →「API Key」页按图文教程填入自己的 DeepSeek Key → 上传简历
- **订阅推送**：「订阅推送」页上传简历 + 绑定邮箱

## 安全与隐私

- 学生的 DeepSeek API Key 只保存在其浏览器 localStorage，随请求直达 DeepSeek，**服务器不存储**
- 首次启动强制设置管理员密码（废弃默认密码）
- 管理员接口全部 JWT + 角色校验；数据库只读 SQL 查询接口有注入防护
- Cookie 与采集数据不进版本库（`.gitignore` 已排除 `cookies/`、`data/`、`.env*`）
- 数据每天自动备份 `data_backups/`，保留 7 份

## 目录结构

```
├── serve.py              # 一键启动器（自检/防火墙/局域网IP/uvicorn）
├── init_admin.py         # 首次运行管理员密码向导
├── scheduler.py          # 定时调度引擎（采集/订阅推送/每日备份）
├── match_api.py          # FastAPI 主应用（API + 静态页 + 启动钩子）
├── admin_api.py          # 管理后台 API（健康面板/Cookie上传/爬虫调度）
├── match_ai.py           # DeepSeek 调用（支持请求级用户 Key）
├── login_helper.py       # 社招爬虫（Selenium）
├── gongkao_crawler.py    # 公考爬虫（纯 HTTP）
├── cookie_collector.py   # Cookie 采集工具（辅导员在自己电脑运行）
├── 启动系统.bat           # Windows 入口（解压即用）
├── install_linux.sh      # Linux 一键安装
├── start.sh              # Linux 手动控制
├── build_portable.py     # Windows 便携包构建脚本
└── 辅导员手册.md          # 零代码使用文档（随包交付）
```

## 系统要求

| 环境 | 要求 |
|---|---|
| Windows | Server 2012 / Win8 及以上（便携包内嵌运行时，无需装任何环境） |
| Linux | Python 3.8+，内存 1GB+，磁盘 1GB+，可访问招聘网站与 DeepSeek |
| 浏览器 | 学生端 Chrome / Edge / Safari 均可（响应式，支持手机） |
