#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JobBoard 一键启动器
双击即可启动所有服务：
  - FastAPI 匹配服务  (5001)
  - Flask  调度服务   (5000)
  - Node.js 前端      (8766)
"""

import os
import sys
import json
import time
import shutil
import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

# ─── 路径常量 ─────────────────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    # PyInstaller 打包后，EXE 所在目录就是项目根
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PYTHON_EXE   = sys.executable        # 当前 Python 解释器（打包后跟着走）
NODE_EXE     = shutil.which("node")  # 从 PATH 找 node
REQ1         = os.path.join(BASE_DIR, "requirements.txt")
REQ2         = os.path.join(BASE_DIR, "requirements_match.txt")
MATCH_API    = os.path.join(BASE_DIR, "match_api.py")
SCHEDULE_API = os.path.join(BASE_DIR, "schedule_api.py")
SERVE_JS     = os.path.join(BASE_DIR, "serve.js")
ENV_MATCH    = os.path.join(BASE_DIR, ".env.match")
FRONTEND_URL = "http://localhost:8766"
ADMIN_URL    = "http://localhost:5001/docs"

# ─── 全局状态 ─────────────────────────────────────────────────────────────────

procs = {}          # name -> subprocess.Popen
log_lines = []      # 日志缓冲
app_running = True

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    log_lines.append(line)
    print(line)
    try:
        if text_widget:
            text_widget.configure(state="normal")
            text_widget.insert("end", line + "\n")
            text_widget.see("end")
            text_widget.configure(state="disabled")
    except Exception:
        pass


def read_deepseek_key():
    """从 .env.match 读取 DEEPSEEK_API_KEY"""
    if not os.path.exists(ENV_MATCH):
        return ""
    with open(ENV_MATCH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def save_deepseek_key(key):
    """将 DEEPSEEK_API_KEY 写入 .env.match"""
    lines = []
    found = False
    if os.path.exists(ENV_MATCH):
        with open(ENV_MATCH, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("DEEPSEEK_API_KEY="):
                    lines.append(f"DEEPSEEK_API_KEY={key}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"DEEPSEEK_API_KEY={key}\n")
    with open(ENV_MATCH, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ─── 依赖检测与安装 ───────────────────────────────────────────────────────────

REQUIRED_PACKAGES = {
    # 包名: import名
    "flask":            "flask",
    "requests":         "requests",
    "schedule":         "schedule",
    "beautifulsoup4":   "bs4",
    "lxml":             "lxml",
    "pandas":           "pandas",
    "openpyxl":         "openpyxl",
    "selenium":         "selenium",
    "undetected-chromedriver": "undetected_chromedriver",
    "fastapi":          "fastapi",
    "uvicorn":          "uvicorn",
    "httpx":            "httpx",
    "PyPDF2":           "PyPDF2",
    "pydantic":         "pydantic",
    "python-multipart": "multipart",
    "python-jose":      "jose",
    "bcrypt":           "bcrypt",
    "python-docx":      "docx",
    "Pillow":           "PIL",
}


def check_and_install_deps(progress_cb=None):
    """检查缺失依赖，批量安装；progress_cb(current, total, pkg_name)"""
    missing = []
    for pkg, imp in REQUIRED_PACKAGES.items():
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)

    if not missing:
        log("✅ 所有依赖已就绪，无需安装")
        return True

    log(f"⚠️ 发现 {len(missing)} 个缺失依赖，开始自动安装...")
    log(f"   缺失包: {', '.join(missing)}")

    for i, pkg in enumerate(missing):
        if progress_cb:
            progress_cb(i, len(missing), pkg)
        log(f"  安装 [{i+1}/{len(missing)}] {pkg} ...")
        result = subprocess.run(
            [PYTHON_EXE, "-m", "pip", "install", pkg,
             "--quiet", "--no-warn-script-location"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log(f"  ❌ 安装失败: {pkg}")
            log(f"     {result.stderr.strip()[:200]}")
            return False
        log(f"  ✅ 安装成功: {pkg}")

    if progress_cb:
        progress_cb(len(missing), len(missing), "完成")
    log("✅ 所有依赖安装完毕")
    return True


# ─── 服务启动 ─────────────────────────────────────────────────────────────────

def start_service(name, cmd, env=None, cwd=None, update_cb=None):
    """启动一个后台子进程，持续读取其输出"""
    global procs
    if name in procs and procs[name].poll() is None:
        log(f"⚠️ {name} 已在运行，跳过")
        return

    log(f"🚀 启动 {name}: {' '.join(cmd)}")
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd or BASE_DIR,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        procs[name] = proc

        def _reader():
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    log(f"  [{name}] {line}")
                    if update_cb:
                        update_cb(name, line)
            proc.stdout.close()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        log(f"  ✅ {name} 进程已启动 (PID {proc.pid})")
    except Exception as e:
        log(f"  ❌ 启动 {name} 失败: {e}")


def stop_all():
    """终止所有子进程"""
    for name, proc in procs.items():
        if proc.poll() is None:
            log(f"  🛑 停止 {name} (PID {proc.pid})")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    log("所有服务已停止")


def is_alive(name):
    return name in procs and procs[name].poll() is None


# ─── GUI 主界面 ───────────────────────────────────────────────────────────────

text_widget = None   # 全局引用，供 log() 使用


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JobBoard 就业服务平台 — 启动器")
        self.geometry("700x540")
        self.resizable(False, False)
        self.configure(bg="#FBF8F3")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.after(200, self._start_sequence)   # 延迟启动，让窗口先渲染

    def _build_ui(self):
        global text_widget

        # ── 顶部 Logo 区 ──
        header = tk.Frame(self, bg="#9C6B3C", height=56)
        header.pack(fill="x")
        tk.Label(header, text="JobBoard  就业服务平台",
                 font=("Microsoft YaHei", 16, "bold"),
                 fg="white", bg="#9C6B3C").pack(side="left", padx=20, pady=10)
        tk.Label(header, text="智能招聘匹配系统",
                 font=("Microsoft YaHei", 10),
                 fg="#F5DEB3", bg="#9C6B3C").pack(side="right", padx=20, pady=14)

        # ── 进度条区 ──
        prog_frame = tk.Frame(self, bg="#FBF8F3", pady=10)
        prog_frame.pack(fill="x", padx=20)
        self.status_label = tk.Label(prog_frame, text="正在初始化...",
                                     font=("Microsoft YaHei", 10),
                                     bg="#FBF8F3", fg="#555")
        self.status_label.pack(anchor="w")
        self.progress = ttk.Progressbar(prog_frame, length=660, mode="determinate",
                                        maximum=100)
        self.progress.pack(fill="x", pady=(4, 0))

        # ── 服务状态指示 ──
        svc_frame = tk.Frame(self, bg="#FBF8F3")
        svc_frame.pack(fill="x", padx=20, pady=(6, 0))
        self.svc_labels = {}
        services = [
            ("match_api",    "FastAPI 匹配服务 :5001"),
            ("schedule_api", "Flask  调度服务  :5000"),
            ("frontend",     "Node.js 前端     :8766"),
        ]
        for i, (name, label) in enumerate(services):
            col = tk.Frame(svc_frame, bg="#FBF8F3")
            col.grid(row=0, column=i, padx=8)
            dot = tk.Label(col, text="●", font=("Arial", 14), fg="#CCC", bg="#FBF8F3")
            dot.pack()
            txt = tk.Label(col, text=label, font=("Microsoft YaHei", 9),
                           bg="#FBF8F3", fg="#777", wraplength=160)
            txt.pack()
            self.svc_labels[name] = dot

        # ── DeepSeek Key 输入 ──
        key_frame = tk.Frame(self, bg="#FBF8F3", pady=6)
        key_frame.pack(fill="x", padx=20)
        tk.Label(key_frame, text="DeepSeek API Key:",
                 font=("Microsoft YaHei", 9, "bold"),
                 bg="#FBF8F3", fg="#555").pack(side="left")
        self.key_var = tk.StringVar(value=read_deepseek_key())
        key_entry = tk.Entry(key_frame, textvariable=self.key_var, width=42,
                             show="*", font=("Consolas", 9))
        key_entry.pack(side="left", padx=(8, 4))
        tk.Button(key_frame, text="保存", command=self._save_key,
                  bg="#9C6B3C", fg="white", relief="flat",
                  padx=8, cursor="hand2").pack(side="left")

        # ── 日志区 ──
        log_frame = tk.Frame(self, bg="#FBF8F3")
        log_frame.pack(fill="both", expand=True, padx=20, pady=(6, 0))
        tk.Label(log_frame, text="运行日志", font=("Microsoft YaHei", 9, "bold"),
                 bg="#FBF8F3", fg="#888").pack(anchor="w")
        text_widget = scrolledtext.ScrolledText(
            log_frame, height=12, state="disabled",
            font=("Consolas", 9), bg="#1E1E1E", fg="#D4D4D4",
            insertbackground="white", relief="flat", borderwidth=0
        )
        text_widget.pack(fill="both", expand=True)

        # ── 底部按钮 ──
        btn_frame = tk.Frame(self, bg="#FBF8F3", pady=10)
        btn_frame.pack(fill="x", padx=20)
        tk.Button(btn_frame, text="🌐 打开前台", command=lambda: webbrowser.open(FRONTEND_URL),
                  bg="#9C6B3C", fg="white", relief="flat", padx=16, pady=6,
                  font=("Microsoft YaHei", 10), cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="⚙️ 打开后台管理", command=lambda: webbrowser.open("http://localhost:5001/static-admin/index.html"),
                  bg="#7A5030", fg="white", relief="flat", padx=16, pady=6,
                  font=("Microsoft YaHei", 10), cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="🔄 重启所有服务", command=self._restart,
                  bg="#555", fg="white", relief="flat", padx=16, pady=6,
                  font=("Microsoft YaHei", 10), cursor="hand2").pack(side="left", padx=(0, 8))
        self.stop_btn = tk.Button(btn_frame, text="■ 停止并退出", command=self._on_close,
                                  bg="#C0392B", fg="white", relief="flat", padx=16, pady=6,
                                  font=("Microsoft YaHei", 10), cursor="hand2")
        self.stop_btn.pack(side="right")

    def _set_progress(self, val, msg=""):
        self.progress["value"] = val
        if msg:
            self.status_label.config(text=msg)
        self.update_idletasks()

    def _set_svc(self, name, ok):
        color = "#27AE60" if ok else "#E74C3C"
        if name in self.svc_labels:
            self.svc_labels[name].config(fg=color)

    def _save_key(self):
        key = self.key_var.get().strip()
        if not key:
            messagebox.showwarning("提示", "API Key 不能为空")
            return
        save_deepseek_key(key)
        log("✅ DeepSeek API Key 已保存到 .env.match")
        messagebox.showinfo("保存成功", "DeepSeek API Key 已保存\n重启匹配服务后生效")

    def _start_sequence(self):
        """在后台线程中执行：检查依赖 → 启动三个服务"""
        def _worker():
            self._set_progress(5, "正在检查依赖库...")
            log("=" * 50)
            log("JobBoard 就业服务平台 启动器 v1.0")
            log("=" * 50)

            # 1. 检查 Node.js
            if not NODE_EXE:
                log("❌ 未找到 node.exe，前端服务无法启动")
                log("   请访问 https://nodejs.org 下载安装 Node.js (LTS)")
                self._set_progress(100, "❌ 缺少 Node.js，请安装后重试")
                messagebox.showerror(
                    "缺少 Node.js",
                    "未找到 Node.js\n\n请访问 https://nodejs.org 安装 LTS 版本\n安装完成后重新启动本程序"
                )
                return
            log(f"✅ Node.js: {NODE_EXE}")
            self._set_progress(10)

            # 2. 检查并安装 Python 依赖
            def _prog(cur, total, pkg):
                pct = 10 + int(cur / max(total, 1) * 30)
                self._set_progress(pct, f"安装依赖 [{cur}/{total}] {pkg}")

            ok = check_and_install_deps(progress_cb=_prog)
            if not ok:
                self._set_progress(100, "❌ 依赖安装失败，请查看日志")
                messagebox.showerror("依赖安装失败",
                    "部分 Python 依赖安装失败\n请确保网络正常后重启\n也可手动运行：\npip install -r requirements.txt\npip install -r requirements_match.txt")
                return
            self._set_progress(40, "依赖检查完成，启动服务...")

            # 3. 准备 DeepSeek Key 环境变量
            key = read_deepseek_key()
            env_extra = {}
            if key:
                env_extra["DEEPSEEK_API_KEY"] = key
                log(f"✅ DeepSeek API Key 已加载（{key[:8]}...）")
            else:
                log("⚠️ 未配置 DeepSeek API Key，AI 匹配功能不可用")
                log("   请在启动器上方输入框填入 Key 并保存")

            # 4. 启动 FastAPI 匹配服务 (5001)
            self._set_progress(50, "启动 FastAPI 匹配服务 (5001)...")
            start_service(
                "match_api",
                [PYTHON_EXE, "-m", "uvicorn", "match_api:app",
                 "--host", "0.0.0.0", "--port", "5001", "--reload"],
                env=env_extra,
                cwd=BASE_DIR,
            )
            time.sleep(2)
            self._set_svc("match_api", is_alive("match_api"))
            self._set_progress(65, "启动 Flask 调度服务 (5000)...")

            # 5. 启动 Flask 调度服务 (5000)
            start_service(
                "schedule_api",
                [PYTHON_EXE, "schedule_api.py"],
                cwd=BASE_DIR,
            )
            time.sleep(2)
            self._set_svc("schedule_api", is_alive("schedule_api"))
            self._set_progress(80, "启动 Node.js 前端 (8766)...")

            # 6. 启动 Node.js 前端服务 (8766)
            start_service(
                "frontend",
                [NODE_EXE, "serve.js"],
                cwd=BASE_DIR,
            )
            time.sleep(2)
            self._set_svc("frontend", is_alive("frontend"))
            self._set_progress(95, "等待服务就绪...")

            # 7. 等待端口就绪
            import socket
            for port in [5001, 5000, 8766]:
                for _ in range(10):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=1):
                            break
                    except OSError:
                        time.sleep(1)

            self._set_progress(100, "✅ 所有服务已就绪！")
            log("=" * 50)
            log(f"🎉 启动完成！前台地址: {FRONTEND_URL}")
            log("=" * 50)

            # 8. 自动打开浏览器
            time.sleep(1)
            webbrowser.open(FRONTEND_URL)

        threading.Thread(target=_worker, daemon=True).start()

    def _restart(self):
        log("🔄 重启所有服务...")
        stop_all()
        time.sleep(1)
        procs.clear()
        for name in self.svc_labels:
            self._set_svc(name, False)
        self._start_sequence()

    def _on_close(self):
        if messagebox.askyesno("退出确认", "停止所有服务并退出 JobBoard 启动器？"):
            stop_all()
            self.destroy()

    def _periodic_check(self):
        """每 5 秒刷新服务状态指示灯"""
        for name in self.svc_labels:
            self._set_svc(name, is_alive(name))
        self.after(5000, self._periodic_check)


# ─── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = LauncherApp()
    app.after(5000, app._periodic_check)
    app.mainloop()
