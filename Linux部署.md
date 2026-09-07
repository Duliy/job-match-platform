# Linux 服务器部署指南 · 校园版

> 适用：学院 Linux 服务器（Ubuntu / Debian / CentOS / Rocky 均可）
> **离线便携包**：Python、Chrome、全部依赖均已内置，服务器无需联网下载任何东西。

---

## 一、部署（约 5 分钟）

### 第 1 步：获取并上传便携包

拿到 `就业服务平台-校园版-linux.tar.gz`（约 350MB，由维护者用 `build_portable_linux.py` 构建），上传到服务器：

```bash
# 在你自己电脑上执行
scp 就业服务平台-校园版-linux.tar.gz root@服务器IP:/root/
```

### 第 2 步：解压安装

```bash
# 在服务器上执行
mkdir -p /opt/jobboard
tar xzf /root/就业服务平台-校园版-linux.tar.gz -C /opt/jobboard --strip-components=1
cd /opt/jobboard
sudo bash install.sh
```

脚本自动完成（**全程离线**）：

1. ✅ 环境自检（内置 Python / Chrome）
2. ✅ 检查 Chrome 共享库（如缺失才调用系统包管理器，这是唯一可能需要联网的一步）
3. ✅ 离线安装全部 Python 依赖
4. ✅ 首次运行引导设置管理员密码（输入时不显示，是正常的）
5. ✅ systemd 开机自启 + 崩溃自动重启 + 防火墙放行
6. ✅ 打印访问地址

### 第 3 步：云服务器安全组（**云服务器必做**）

如果服务器在火山引擎 / 阿里云 / 腾讯云等云平台，系统装好后**还必须到云控制台**：

> 安全组 → 入站规则 → 放行 **TCP 8000** 端口

（云安全组在操作系统之外，安装脚本管不到它。不做这一步，外网就是访问不到。）

## 二、日常运维

| 操作 | 命令 |
|---|---|
| 查看运行状态 | `systemctl status jobboard` |
| 查看实时日志 | `journalctl -u jobboard -f` |
| 重启 | `systemctl restart jobboard` |
| 停止 | `systemctl stop jobboard` |

## 三、安装后必做（网页上完成）

1. 管理后台 → **爬虫系统 → 社招爬虫**：填采集关键词，开启定时采集，点「立即采集一次」
2. **系统设置**：配置 SMTP 邮件服务（订阅推送需要，推荐 QQ/163 邮箱授权码）
3. **数据源健康**：确认各数据源状态

## 四、常见问题

**Q：同学打不开网页？**
① `systemctl status jobboard` 看服务是否活着
② 云服务器检查**安全组**是否放行 8000（最常见原因）
③ `curl http://127.0.0.1:8000/` 在服务器上自测，通则问题在网络层

**Q：社招爬虫没有数据？**
`ldd /opt/jobboard/runtime/chrome/chrome | grep "not found"` 查看缺失的共享库并安装。公考采集不需要 Chrome，不受影响。

**Q：想换端口？**
```bash
sudo systemctl edit jobboard
# 加入：
# [Service]
# Environment=PORT=9000
sudo systemctl restart jobboard
```

**Q：数据在哪？会不会丢？**
全部数据在 `data/` 目录。系统每天凌晨自动备份到 `data_backups/`，保留最近 7 份。

**Q：怎么升级到新版本？**
拿到新的 tar.gz 后：备份 `data/` 目录 → 解压覆盖 → `systemctl restart jobboard`。

---

## 附：从源码开发部署（维护者用，不推荐老师使用）

```bash
git clone -b delivery-campus https://github.com/Duliy/job-match-platform.git jobboard
cd jobboard
sudo bash install_linux.sh   # 联网安装版
bash start.sh start          # 或手动控制（不依赖 systemd）
```

> ⚠️ 联网安装依赖目标机的 apt 源、Python 包源、Chrome 来源可用，
> 任一环节出问题都需要人工排查。**给老师交付请一律使用离线便携包。**
