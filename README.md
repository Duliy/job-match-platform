# 学院就业服务平台 · AI 岗位智能匹配系统

> 与学院合作落地、部署供全院师生使用的就业服务平台：招聘信息采集 + AI 简历匹配 + 订阅推送的完整闭环。

## 核心亮点

- **真实落地**：与学院合作部署，供全院师生日常使用
- **多源采集**：Selenium 爬虫覆盖 5 大社招平台（51job / 智联 / 猎聘 / Boss / 公共招聘网）及 31 省公考职位库
- **两段式 AI 匹配架构**：`SQL 粗筛（技能/城市/薪资/学历）→ LLM 精排`，自定义技能(40)/经验(25)/学历(15)/薪资(10)/地点(10) 五维百分制评分体系并输出录取概率，LLM 精排调用量压缩约 80%（100→20 候选）
- **简历解析工程化**：PyPDF2 → pdfplumber → pymupdf 三重降级解析策略 + 严格 JSON 输出的 Prompt 约束，保证非结构化简历解析稳定性
- **订阅推送闭环**：VIP 订阅每 48 小时自动扫描新岗位，匹配度超阈值自动邮件推送
- **交付级工程化**：一键部署脚本、systemd 服务、Windows 可执行程序分发（PyInstaller）、JWT 权限与会员积分体系

## 技术栈

FastAPI（匹配核心）+ Flask（爬虫调度）+ 原生 HTML/JS 前端（PWA）+ SQLite（WAL + FTS5 全文索引）+ DeepSeek API

## 架构速览

```
crawler.py / gongkao_crawler.py   社招 + 公考职位采集
match_ai.py / match_api.py        AI 匹配核心（两段式）
admin_api.py / admin.html         管理后台
auth.py                           JWT + bcrypt 认证
index.html / resume_match.html    学生端 / 简历匹配页
DEPLOY.md                         服务器部署文档
```

## 快速开始

```bash
pip install -r requirements.txt -r requirements_match.txt
export DEEPSEEK_API_KEY=你的key   # 见 .env 配置说明
bash start.sh
```

> 本仓库不包含任何采集数据、Cookie、登录态与 API 凭证；管理员初始密码请在部署时通过环境变量修改（见 DEPLOY.md）。
