# 就业服务平台 · AGENTS 接手文档

> 写给接手的 agent：读完本文档你应该能无缝接手这个项目的开发、部署和运维。
> 本文档在仓库中持续更新，以 `delivery-campus` 分支最新版本为准。
> 最后更新：2026-10-28

---

## ⚠️ 阅读前必读：凭据不在本文件

本仓库为 **GitHub 公开仓库**，任何密钥/密码绝不入库：

- 服务器 SSH 密码、管理后台密码、DeepSeek Key 等，保存在维护者本机的私有文档
  `/home/qin-na/jobboard-handover.md`（仅在交接时通过安全渠道传递）。
- `.gitignore` 已排除：`data/`、`cookies/`、`.env*`、`dist/`、`dist_runtime_cache/`
  ——**不要把采集数据、Cookie、密钥提交上来**，提交前 `git status` 自查。

## 一、项目是什么

为**西南大学商贸学院**开发的就业服务平台（辅导员是交付对象，全院学生是用户）：

- **岗位采集**：前程无忧 51job / 实习僧（免登录 Selenium）+ 智联 / 猎聘（Cookie）+ 中公教育公考职位库（纯 HTTP）
- **AI 功能**：简历解析、AI 岗位匹配（SQL 粗筛 → LLM 精排）、简历深度分析
- **订阅推送**：学生绑定邮箱 + 上传简历，系统定时扫描新岗位发邮件（SQL 粗筛，不需要 AI Key）
- **管理后台**：数据源健康面板 / Cookie 网页上传 / 用户管理 / 爬虫调度 / 订阅配置 / 数据库浏览

### 两个版本（重要！）

| 版本 | 位置 | 说明 |
|---|---|---|
| 商业化版 | `main` 分支 + tag `commercial-v1.0` + 归档 `~/backups/job-match-platform-commercial-v1.0-20260903.tar.gz` | 含 VIP/积分/CDK 体系，**已冻结，不要动** |
| **校园交付版（当前工作分支）** | `delivery-campus` 分支 | 非商业化，全部开发在这个分支 |

校园版关键决策（用户已拍板，不要回退）：
- **无 VIP/积分/付费**，岗位浏览免登录
- **AI 功能 BYOK**：学生在自己浏览器 localStorage 存 DeepSeek Key，请求头 `X-User-Api-Key` 传给后端，**服务器绝不落库**；无 Key 时后端返回 402（detail 以 `NO_API_KEY:` 开头），前端引导到「API Key」页
- **订阅推送免 Key**：SQL 粗筛推送，AI 精排引导学生回站内用自己的 Key 完成
- 管理后台登录强制 admin 角色，首次部署强制改密码

## 二、GitHub

- 仓库：https://github.com/Duliy/job-match-platform
- 分支：`main`（商业版，勿推）、`delivery-campus`（校园版，工作分支）
- 维护者本机 clone：`/home/qin-na/github-portfolio/job-match-platform`
- 推送方式：`git push origin delivery-campus`（机器上 gh/git 已认证）
- **维护者本机代理（clash-verge）经常抖动**，push 偶发 TLS 错误，重试即可（曾连试 7 次成功）

## 三、技术架构（校园版）

**单进程架构**：一个 FastAPI 进程承担一切（API + 前端静态页 + 定时调度），单端口 8000。

```
match_api.py     # FastAPI 主应用：API + 静态页白名单服务 + 启动钩子
match_ai.py      # DeepSeek 调用（api_key 参数化：请求级 Key → env 兜底）
match_db.py      # SQLite 数据层（jobs/gk_jobs，WAL）
match_utils.py   # 薪资标准化解析 + 城市/学历字段归一化（见「关键约定」）
auth.py          # JWT + bcrypt + 邮件配置（VIP/CDK 函数保留但不再被调用）
admin_api.py     # 管理后台路由：健康面板/Cookie上传/爬虫调度/订阅/用户/DB
scheduler.py     # 定时调度引擎（社招采集/公考采集/订阅扫描/每日备份留7份）
db_schema_v2.py  # 建表 + schema 升级（含默认 admin 创建）
import_data.py   # 爬虫 JSON → SQLite 增量导入
clean_dirty_data.py # 存量数据清洗脚本（一次性，可随时重跑）
crawler_51job.py # 前程无忧：公开页批量读取、SPA全量翻页、限速/重试/逐页保存
login_helper.py  # 社招爬虫（Selenium，headless；driver.quit() 有15s看门狗防挂死）
gongkao_crawler.py # 公考爬虫（纯 HTTP，POST {province}.offcn.com/zw/search/）
cookie_collector.py # Cookie 采集工具（辅导员在自己电脑运行）
serve.py         # 一键启动器（自检/防火墙/局域网IP/uvicorn）
init_admin.py    # 首次运行管理员密码向导
portable_env.py  # Chrome/chromedriver 路径解析（内嵌 > 环境变量 > 系统）
```

前端（无构建、原生 HTML + Vue3 CDN）：
- `index.html`：落地页（苹果风重写，含实时统计 + `#tab=N` 直达）
- `resume_match.html`：学生端 SPA。**默认页 = 岗位搜索**。顶部是汉堡按钮 + 隐藏式侧边抽屉导航；AI 功能（简历匹配/简历分析/订阅推送/API Key）收在「AI 功能」折叠二级菜单
- `admin.html`：管理后台（Vue SPA，admin 角色才能登录）
- 苹果设计 token：`#f5f5f7` 底、`#1d1d1f` 文、`#0071e3` 蓝、毛玻璃、980px 胶囊按钮

数据库：`data/jobs.db`（SQLite）。关键表：`jobs`、`gk_jobs`、`users`（含 `notify_email`）、`member_resumes`、`hot_jobs`、`email_config`、`vip_match_results`。

### 关键约定

- 静态文件服务：`match_api.py` 的 `_STATIC_FILES` 白名单 + `/{filename}` catch-all + `/downloads/{filename}` 下载路由；HTML 带 `Cache-Control: no-cache`
- 邮件：`email_config` 表存 SMTP 配置（管理员在后台填）；`PUBLIC_BASE_URL` 环境变量用于邮件内链接（serve.py 自动按局域网 IP 设置）
- 所有 AI 调用走 `match_ai._call_deepseek(api_key=...)`，Key 解析走 `match_api.resolve_user_api_key(request)`
- 筛选下拉数据源：`GET /api/match/cities?job_type=` 返回**全库**去重城市/省份（2026-09-23 修复，之前前端只从当前页提取导致城市筛选形同虚设）
- 字段清洗（match_utils）：`extract_city` 内含 `normalize_city`（黑名单剔除"已上市"等公司标签 + 去"市"后缀 + >5字碎片守卫）；`normalize_education` 只保留学历词（实习僧的"4天/周，可转正"等不再写入学历字段，并入职位名展示）；存量清洗脚本 `clean_dirty_data.py`（生产已跑过，可随时重跑）
- 学历筛选：后端 `education` 参数宽松语义（空学历/不限不排除，与 pre_filter 一致）；社招老数据学历基本为空，靠新采集（51job/智联/猎聘都会提取）逐步填充
- **改前端页面后必须 bump `sw.js` 的 CACHE_NAME 版本号**（当前 v4），否则用户看到旧缓存页面

## 四、服务器（生产环境）

**SSH：`ssh root@163.7.6.226`**（密码见维护者本机私有文档，不在此仓库）

- 系统：Ubuntu 24.04（火山引擎），4GB 内存，40GB 盘
- apt 源已换阿里云（原火山源 DNS 解析失败；备份 `/etc/apt/sources.list.bak`）
- 部署目录：`/opt/jobboard`（**git checkout，更新 = `git pull + systemctl restart jobboard`**）
  - `runtime/`（Python 3.12 独立构建版 + Chrome for Testing 131 + chromedriver）和 `wheels/` 从旧 tar 部署迁移而来，**不在 git 里，别删**
  - `data/`（种子数据 + 用户数据）、`downloads/cookie-tool-windows.zip` 同理保留
  - 旧部署备份：`/opt/jobboard.old`
- 服务：`systemctl status|restart|stop jobboard`，日志 `journalctl -u jobboard -f`
  - `ExecStart=/opt/jobboard/runtime/python/bin/python3 serve.py --background`
- 管理员后台账号：admin（密码见私有文档；应建议辅导员尽快改）
- 火山云安全组已放行 TCP 8000（2026-09-23 验证外网 HTTP 200）；采集关键词 + SMTP 由维护者在后台配置
- 维护者本机 SSH 操作方式：无 sshpass，用 paramiko 脚本（连接不稳时加 `set_keepalive(15)` + 后台任务轮询模式；`pkill -f` 记得用 `[c]hrome` 技巧防自杀）

### 已知网络限制（实测）

| 源 | 云服务器 | 住宅/校园网 |
|---|---|---|
| 51job / 实习僧 | ✅ 可采 | ✅ |
| 中公教育（公考） | ❌ **403 封机房 IP** | ✅ |
| 智联 / 猎聘 | 未验证（需 Cookie） | 未验证 |

## 五、打包/构建（在维护者本机 NUC 上执行）

构建缓存：`dist_runtime_cache/`（Python embeddable、Chrome、wheels、vc_redist、cookie 工具）

| 产物 | 命令 | 输出 |
|---|---|---|
| Windows 便携包 | `python3 build_portable.py [--skip-downloads]` | `dist/就业服务平台-校园版.zip`（~334MB，Py3.8+Chrome109，按 Server 2012 最保守标准） |
| Linux 便携包 | `python3 build_portable_linux.py [--skip-downloads]` | `dist/就业服务平台-校园版-linux.tar.gz`（~369MB，Py3.12+CFT131，目标机零联网安装） |
| Cookie 采集工具 | `python3 build_cookie_tool.py` | 缓存后自动纳入两包的 `downloads/` |

依赖清单：Windows 用 `requirements-portable.txt`（py3.8 锁定版），Linux 用 `requirements-linux.txt`（py3.12 现代版）。**别混用**（pandas 等二进制包版本不兼容）。

**.bat 文件必须 GBK 编码保存**（中文 Windows cmd 按 ANSI 解析），改 bat 后注意别存成 UTF-8。

## 六、本机开发环境（维护者 NUC）

- 项目目录：`/home/qin-na/github-portfolio/job-match-platform`（delivery-campus 分支）
- 测试 venv：`/tmp/jbvenv`（Python 3.12 + 全依赖，重建：`python3 -m venv /tmp/jbvenv && /tmp/jbvenv/bin/pip install fastapi "uvicorn[standard]" httpx PyPDF2 pdfplumber pymupdf python-docx pydantic python-multipart "python-jose[cryptography]" bcrypt schedule requests beautifulsoup4 lxml pandas openpyxl selenium paramiko`）
- 本地跑服务：`/tmp/jbvenv/bin/python -m uvicorn match_api:app --host 127.0.0.1 --port 8000`（后台进程用 `setsid -f` 或 nohup；**维护者要求：测试完必须杀掉进程，不要长期在本地挂着浪费资源**；起服务前先 `pgrep -f '[u]vicorn match_api'` 检查端口残留）
- 本机无 Chrome，有 Edge + 手动下载的 msedgedriver（`/tmp/edgedriver_pkg/msedgedriver`），测试爬虫用 monkeypatch 方式（参考 `/tmp/test_crawl.py`）；无 playwright，浏览器截图自审用 selenium + Edge headless

## 七、踩过的坑（别再踩）

1. `driver.quit()` 在异常会话上永久挂起 → login_helper 已加 15s 看门狗 `os._exit(0)`；scheduler 超时先 kill 再抛
2. `sqlite3` 同一 cursor 迭代中执行新语句会重置迭代 → 先 `fetchall()`
3. FastAPI `StaticFiles(directory=不存在的目录)` 启动即崩 → 已改白名单路由
4. `pkill -f 'xxx'` 会匹配自身命令行自杀 → 用 `'[x]xx'`
5. paramiko 长任务/大文件传输易断 → 后台任务 + 轮询；大文件分块（32MB）传输 + 服务端 cat 合并
6. Ubuntu 24.04 的 `chromium-browser` 是 snap 过渡包会卡死 apt → 用 Chrome for Testing zip
7. Service Worker 旧缓存会让用户看到过期页面 → **sw.js 版本号要 bump**；HTML 一律 no-cache
8. Windows zip 打包曾误吞 dist/ 内其他产物（linux tar.gz）→ 只打包 PKG_DIR
9. 爬虫用「含"市"/"区"」识别城市会把公司标签"已上市"误当城市 → 已加 `_is_company_tag` 排除 + `normalize_city` 黑名单/归一化兜底，写新解析逻辑时复用
10. 城市下拉只从当前页提取导致筛选形同虚设 → 筛选类下拉一律走全库接口（`/api/match/cities`），不要从分页结果里凑

## 八、待办 / backlog

1. ~~火山云安全组放行 8000~~ ✅ 已放行（2026-09-23 验证外网 HTTP 200）；采集关键词 + SMTP 由维护者在后台配置
2. 公考爬虫：在**校园网环境验证**（云服务器 IP 被封属预期，非 bug）
3. 公共招聘网采集失效（选择器/老 TLS），待移除或修复（TODO-84608c29）
4. 智联/猎聘 Cookie 链路实机验证
5. 学生端乱码问题：用户反馈过一次（疑似旧 SW 缓存），已做 no-cache+favicon 防御 + sw.js 版本机制，**待用户确认是否复现**
6. 手机端响应式只做了 CSS 静态检查，未真机验证
7. Windows Server 2012 虚拟机验收未做（ISO 渠道已调研：archive.org 有带校验和的 2012 R2 评估版，可行；用户在犹豫是否值得）
8. 社招老数据学历字段基本为空（历史采集未提取），学历筛选覆盖率随新采集逐步提升；如需加速可重采或从历史详情页补录
9. todos 在维护者本机 `~/.pi/todos/`（job-board 标签）

## 九、迭代节奏（维护者习惯）

改代码 → 本机起服务验证（含浏览器截图自审，**验证完杀进程**）→ `git push origin delivery-campus` → 服务器 `git pull && systemctl restart jobboard` → 汇报。两个便携包按需重建（前端改动必须 `--skip-downloads` 重建一次刷新代码）。

## 十、2026-10-28 前程无忧采集改进

- 原实现固定 `pageNum=1` 且 `cards[:25]`，没有翻页；现默认采到分页末尾。
- 一次 JavaScript 批量读取整页公开 DOM/sensorsdata，使用职位 ID 生成岗位链接，获取准确地点、学历和发布日期；下一页使用站点按钮，避免整页重载。
- 每页额外等待 1 秒温和限速；等待实际页码及卡片元数据更新，失败页最多重试一次（站点忽略 URL 页码时通过分页控件恢复目标页），重复页不算正常完成；每页日志记录进度、去重数和耗时。
- 每页原子保存 JSON，最终才导出 Excel。中断/超时时调度器仍导入已保存结果，并记录错误，不误报成功。
- JSON 读写使用一致去重规则；保留不同岗位链接、不同地点，合并关键词，按 `last_seen` 清理超过 7 天未再次采到的记录。
- 已知失效的公共招聘网默认停用，仍可用 `--platforms mohrss` 单独排查；其余数据源保留原采集逻辑，去掉已有显式等待前的固定 sleep。
- 手动限定来源/页数：`python login_helper.py --auto --keywords 信息管理与信息系统 --platforms 51job --max-pages 0`（0=全部）。
- 回归测试：`python -m unittest discover -s tests`。离线便携包共用的 `CODE_FILES` 已加入 `crawler_51job.py`，下次构建会包含新模块。
- 实测（2026-10-28，本机）：关键词「信息管理与信息系统」50 页全部完成，847 个不同岗位，122.14 秒（含第 38 页异常后的恢复）；临时 JSON 和内存 SQLite 均 847 条，地点/链接缺失均为 0。回归测试 12 项通过。网站实时排序与广告重复会影响每次去重数量，不能以页数×20作为唯一岗位数。

## 十一、2026-10-28 整体检查

修复与后续建议见 `PROJECT_REVIEW_2026-10-28.md`。重点：种子包仅包含岗位；初始化不再使用固定管理员密码；匹配缓存按账号/完整简历隔离且按 UTC 计算 TTL；订阅在 SQL LIMIT 前过滤入库时间并为失败收件人保留检查点；WAL 用在线备份；调度任务异步派发并加锁；增量导入更新已有字段；采集失败不再伪报成功。前端缓存版本 v4。
