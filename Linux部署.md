# Linux 服务器部署指南 · 校园版

> 适用：学院 Linux 服务器（Ubuntu / Debian / CentOS / Rocky 均可）
> 全程约 10 分钟，只需能 SSH 登录服务器。

---

## 一、把项目放到服务器上

两种方式任选：

**方式 A：git 克隆（推荐，方便以后更新）**

```bash
cd /opt
git clone -b delivery-campus https://github.com/Duliy/job-match-platform.git jobboard
cd jobboard
```

**方式 B：本地上传**

在你自己电脑上把项目文件夹打包上传：

```bash
# 在你的电脑上执行（Windows 用 PowerShell 也一样）
scp -r job-match-platform 用户名@服务器IP:/opt/jobboard
```

## 二、一键安装

```bash
cd /opt/jobboard
sudo bash install_linux.sh
```

脚本会自动完成：

1. ✅ 安装 Python3 和 Chromium（社招爬虫需要）
2. ✅ 创建虚拟环境并安装全部依赖（走清华镜像，国内速度快）
3. ✅ **首次运行引导你设置管理员密码**（输入时不显示，是正常的）
4. ✅ 配置 systemd 服务：开机自启 + 崩溃自动重启
5. ✅ 防火墙放行 8000 端口
6. ✅ 打印学生访问地址

安装完成后，把地址发给同学即可。

## 三、日常运维（全部一条命令）

| 操作 | 命令 |
|---|---|
| 查看运行状态 | `systemctl status jobboard` |
| 查看实时日志 | `journalctl -u jobboard -f` |
| 重启 | `systemctl restart jobboard` |
| 停止 | `systemctl stop jobboard` |

**不想用 systemd？** 也可以用自带的手动脚本：`bash start.sh start|stop|restart|status|log`

## 四、安装后必做的两件事（网页上完成）

1. 打开管理后台 → **爬虫系统 → 社招爬虫**：填采集关键词（如 `软件,会计,市场营销`），开启定时采集，点「立即采集一次」
2. **系统设置**：配置 SMTP 邮件服务（订阅推送需要），推荐 QQ/163 邮箱的授权码

## 五、常见问题

**Q：社招爬虫没有数据？**
检查 Chromium 是否装上：`chromium --version`。没装就 `sudo apt install chromium`（Ubuntu/Debian）或 `sudo dnf install chromium`（CentOS/Rocky）。公考采集不需要 Chromium，不受影响。

**Q：同学打不开网页？**
① `systemctl status jobboard` 看服务是否活着
② 云服务器还要去**云控制台的安全组**里放行 8000 端口（这是云平台防火墙，系统防火墙之外的一层）

**Q：想换端口？**
```bash
sudo systemctl edit jobboard
# 加入：
# [Service]
# Environment=PORT=9000
sudo systemctl restart jobboard
```

**Q：怎么更新到最新代码？**
```bash
cd /opt/jobboard
git pull
.venv/bin/pip install -q -r requirements-portable.txt
sudo systemctl restart jobboard
```

**Q：数据在哪？会不会丢？**
全部数据在 `data/` 目录。系统每天凌晨自动备份到 `data_backups/`，保留最近 7 份。
