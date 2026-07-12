"""IoTCmpt 本地可视化配置面板后端（纯标准库，Python 3.8+，零第三方依赖）。

仅绑定 127.0.0.1（配置里含 API Key / WiFi 密码，不得暴露到局域网）。
所有动作都通过 subprocess 复用 tools/ 下现有 PowerShell 脚本，避免逻辑重复。

启动：python tools/panel/panel_server.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
STATIC = Path(__file__).resolve().parent / "static"
FIRMWARE = REPO / "firmware" / "esp32s3"
SDKCONFIG = FIRMWARE / "sdkconfig"
SDKCONFIG_DEFAULTS = FIRMWARE / "sdkconfig.defaults"

CREATE_NEW_CONSOLE = 0x00000010


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def ps_file_args(script, *extra):
    return [
        "powershell.exe", "-NoLogo", "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(TOOLS / script),
    ] + list(extra)


# ---------------------------------------------------------------- job runner

class Job:
    def __init__(self, name):
        self.name = name
        self.proc = None
        self.lines = []
        self.trimmed = 0  # 因缓冲裁剪而丢弃的行数（用于换算绝对行号）
        self.generation = 0  # 每次 start 递增，旧的日志流据此感知任务已重启
        self.lock = threading.Lock()
        self.status = "idle"  # idle | running | done | failed | stopped

    def start(self, cmd, cwd):
        if self.proc and self.proc.poll() is None:
            raise ApiError(409, "任务 {} 正在运行中".format(self.name))
        with self.lock:
            self.lines = []
            self.trimmed = 0
            self.generation += 1
            self.status = "running"
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            with self.lock:
                self.status = "failed"
            raise ApiError(
                500,
                "未找到命令 {}。请先安装它（例如 docker / uv / pnpm），"
                "或改用 Docker 演示栈。".format(cmd[0]),
            )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip("\r\n"))
                if len(self.lines) > 5000:
                    del self.lines[:1000]
                    self.trimmed += 1000
        code = self.proc.wait()
        with self.lock:
            if self.status == "running":
                self.status = "done" if code == 0 else "failed"
            self.lines.append("[进程退出，代码 {}]".format(code))

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            raise ApiError(409, "任务 {} 未在运行".format(self.name))
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
            capture_output=True,
        )
        with self.lock:
            self.status = "stopped"

    def running(self):
        return self.proc is not None and self.proc.poll() is None


JOBS = {}
JOBS_LOCK = threading.Lock()


def get_job(name):
    with JOBS_LOCK:
        if name not in JOBS:
            JOBS[name] = Job(name)
        return JOBS[name]


# ---------------------------------------------------------------- actions

def start_console_window(args, cwd):
    """交互式 TUI（menuconfig / monitor）在独立控制台窗口运行。"""
    subprocess.Popen(args, cwd=str(cwd), creationflags=CREATE_NEW_CONSOLE)


def port_args(body):
    port = (body or {}).get("port")
    return ["-Port", port] if port else []


ACTIONS = {
    "docker-up": lambda b: get_job("docker-up").start(
        ["docker", "compose", "up", "--build", "-d"], REPO),
    "docker-down": lambda b: get_job("docker-down").start(
        ["docker", "compose", "down"], REPO),
    "docker-logs": lambda b: get_job("docker-logs").start(
        ["docker", "compose", "logs", "-f", "--tail", "100"], REPO),
    "backend-start": lambda b: get_job("backend").start(
        ["uv", "run", "python", "run_dev.py"], REPO / "server"),
    "frontend-start": lambda b: get_job("frontend").start(
        ["cmd", "/c", "pnpm", "dev"], REPO / "web"),
    "idf-install": lambda b: get_job("idf").start(
        ps_file_args("esp-idf-task.ps1", "-Action", "Install"), REPO),
    "idf-build": lambda b: get_job("idf").start(
        ps_file_args("esp-idf-task.ps1", "-Action", "Build"), FIRMWARE),
    "idf-flash": lambda b: get_job("idf").start(
        ps_file_args("esp-idf-task.ps1", "-Action", "Flash", *port_args(b)), FIRMWARE),
}

CONSOLE_ACTIONS = {
    "idf-menuconfig": lambda b: start_console_window(
        ps_file_args("esp-idf-task.ps1", "-Action", "Menuconfig"), FIRMWARE),
    "idf-monitor": lambda b: start_console_window(
        ps_file_args("esp-idf-task.ps1", "-Action", "Monitor", *port_args(b)), FIRMWARE),
    "idf-flash-monitor": lambda b: start_console_window(
        ps_file_args("esp-idf-task.ps1", "-Action", "FlashMonitor", *port_args(b)), FIRMWARE),
}

STOPPABLE = {"docker-logs", "backend", "frontend", "idf"}


# ---------------------------------------------------------------- env config

ENV_FILES = {
    "compose": REPO / ".env",
    "server": REPO / "server" / ".env",
    "web": REPO / "web" / ".env.local",
}

MASKED_KEYS = {"AIOT_LLM_API_KEY"}


def parse_env(path):
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def get_env_config():
    data = {}
    for name, path in ENV_FILES.items():
        values = parse_env(path)
        for key in MASKED_KEYS & set(values):
            values[key] = "******" if values[key] else ""
        data[name] = {"exists": path.exists(), "values": values}
    return data


ENV_PARAM_FLAGS = [
    ("deviceId", "-DeviceId"),
    ("lanAddress", "-LanAddress"),
    ("apiBaseUrl", "-ApiBaseUrl"),
    ("llmEndpoint", "-LlmEndpoint"),
    ("llmModel", "-LlmModel"),
    ("llmApiKey", "-LlmApiKey"),
    ("autopilotMinConfidence", "-AutopilotMinConfidence"),
    ("autopilotTriggerLevels", "-AutopilotTriggerLevels"),
]

ENV_BOOL_FLAGS = [
    ("llmVisionEnabled", "-LlmVisionEnabled"),
    ("autopilotEnabled", "-AutopilotEnabled"),
]


def save_env_config(body):
    preset = body.get("preset", "MockDemo")
    if preset not in ("MockDemo", "DeviceDemo", "LlmDemo"):
        raise ApiError(400, "未知预设 {}".format(preset))
    args = ["-Preset", preset, "-NonInteractive"]
    for key, flag in ENV_PARAM_FLAGS:
        value = body.get(key)
        if value:
            args += [flag, str(value)]
    for key, flag in ENV_BOOL_FLAGS:
        value = body.get(key)
        if value is not None:
            args += [flag, "true" if value else "false"]
    result = subprocess.run(
        ps_file_args("configure-local.ps1", *args),
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode != 0:
        raise ApiError(500, "配置脚本失败：{}\n{}".format(result.stdout, result.stderr))
    return {"ok": True, "output": result.stdout}


# ---------------------------------------------------------------- firmware config

FIRMWARE_KEYS = {
    "CONFIG_APP_DEVICE_ID": "str",
    "CONFIG_APP_SENSOR_MOCK_ENABLED": "bool",
    "CONFIG_APP_SENSOR_INTERVAL_MS": "int",
    "CONFIG_APP_WIFI_ENABLED": "bool",
    "CONFIG_APP_WIFI_SSID": "str",
    "CONFIG_APP_WIFI_PASSWORD": "str",
    "CONFIG_APP_MQTT_ENABLED": "bool",
    "CONFIG_APP_MQTT_BROKER_URI": "str",
    "CONFIG_APP_IMAGE_UPLOAD_ENABLED": "bool",
    "CONFIG_APP_IMAGE_UPLOAD_URL": "str",
    "CONFIG_APP_CAMERA_ENABLED": "bool",
    "CONFIG_APP_DISPLAY_ENABLED": "bool",
    "CONFIG_APP_ACTUATOR_ENABLED": "bool",
    "CONFIG_APP_BUTTON_ENABLED": "bool",
    "CONFIG_APP_MQ2_ENABLED": "bool",
    "CONFIG_APP_VOICE_ENABLED": "bool",
}


def read_sdkconfig_values():
    source = SDKCONFIG if SDKCONFIG.exists() else SDKCONFIG_DEFAULTS
    values = {}
    if not source.exists():
        return values
    text = source.read_text(encoding="utf-8", errors="replace")
    for key, kind in FIRMWARE_KEYS.items():
        m = re.search(r"^{}=(.*)$".format(re.escape(key)), text, re.M)
        if m:
            raw = m.group(1).strip()
            if kind == "bool":
                values[key] = raw == "y"
            elif kind == "str":
                values[key] = raw.strip('"')
            else:
                values[key] = raw
        elif re.search(r"^# {} is not set$".format(re.escape(key)), text, re.M):
            values[key] = False
    return values


def format_sdk_line(key, kind, value):
    if kind == "bool":
        return "{}=y".format(key) if value else "# {} is not set".format(key)
    if kind == "int":
        return "{}={}".format(key, int(value))
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '{}="{}"'.format(key, escaped)


def save_firmware_config(body):
    values = body.get("values") or {}
    unknown = set(values) - set(FIRMWARE_KEYS)
    if unknown:
        raise ApiError(400, "不支持的配置项：{}".format(sorted(unknown)))

    if SDKCONFIG.exists():
        text = SDKCONFIG.read_text(encoding="utf-8", errors="replace")
    elif SDKCONFIG_DEFAULTS.exists():
        # 首次写入：以 defaults 播种，idf.py 下次构建会补全其余选项
        text = SDKCONFIG_DEFAULTS.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    for key, value in values.items():
        kind = FIRMWARE_KEYS[key]
        try:
            line = format_sdk_line(key, kind, value)
        except (TypeError, ValueError):
            raise ApiError(400, "配置项 {} 的值无效：{!r}".format(key, value))
        pattern = r"^(?:{0}=.*|# {0} is not set)$".format(re.escape(key))
        if re.search(pattern, text, re.M):
            text = re.sub(pattern, lambda _m: line, text, flags=re.M)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"

    SDKCONFIG.write_text(text, encoding="utf-8")
    return {"ok": True, "message": "已写入固件配置，下次编译生效"}


# ---------------------------------------------------------------- status

def probe(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _lan_ip_rank(ip):
    """私网地址优先级：192.168 > 10.x > 172.16-31 > 其他公网。"""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    parts = ip.split(".")
    if parts[0] == "172" and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
        return 2
    return 3


def _lan_ip_usable(ip):
    # 排除回环、链路本地和 198.18.0.0/15（VPN/测试工具常占用的基准网段）
    return not (
        ip.startswith("127.")
        or ip.startswith("169.254.")
        or ip.startswith("198.18.")
        or ip.startswith("198.19.")
    )


def detect_lan_ip():
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            candidates.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except OSError:
        pass
    usable = [ip for ip in candidates if _lan_ip_usable(ip)]
    if not usable:
        return "127.0.0.1"
    return sorted(set(usable), key=_lan_ip_rank)[0]


def get_status():
    return {
        "lanIp": detect_lan_ip(),
        "ports": {
            "backend8000": probe(8000),
            "frontend3000": probe(3000),
            "mqtt1883": probe(1883),
            "postgres5432": probe(5432),
        },
        "jobs": {
            name: {"status": job.status, "running": job.running()}
            for name, job in list(JOBS.items())
        },
    }


def get_comports():
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-Command",
         "[System.IO.Ports.SerialPort]::GetPortNames() -join ','"],
        capture_output=True, text=True, timeout=15,
    )
    ports = [p for p in result.stdout.strip().split(",") if p]
    return {"ports": ports}


# ---------------------------------------------------------------- http

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默访问日志，保持控制台整洁

    # ------------------------------------------------------------- helpers

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "请求体不是合法 JSON")

    def send_file(self, path):
        try:
            resolved = path.resolve()
            resolved.relative_to(STATIC)
            data = resolved.read_bytes()
        except (OSError, ValueError):
            self.send_json({"detail": "未找到文件"}, 404)
            return
        self.send_response(200)
        self.send_header(
            "Content-Type",
            CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def stream_job_logs(self, name):
        job = get_job(name)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        sent = 0  # 绝对行号（含已被裁剪的行）
        with job.lock:
            generation = job.generation
        try:
            while True:
                with job.lock:
                    if job.generation != generation:
                        # 任务已被重新启动，本流对应的日志已作废
                        self.wfile.write(b"event: end\ndata: restarted\n\n")
                        self.wfile.flush()
                        return
                    start = max(sent - job.trimmed, 0)
                    new = job.lines[start:]
                    sent = job.trimmed + len(job.lines)
                    status = job.status
                    alive = job.running()
                for line in new:
                    payload = "data: {}\n\n".format(line)
                    self.wfile.write(payload.encode("utf-8"))
                if new:
                    self.wfile.flush()
                if not alive and status != "running" and not new:
                    self.wfile.write(
                        "event: end\ndata: {}\n\n".format(status).encode("utf-8"))
                    self.wfile.flush()
                    return
                time.sleep(0.4)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return  # 页面关闭或切换，正常现象

    # -------------------------------------------------------------- routes

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/":
                self.send_file(STATIC / "index.html")
            elif path.startswith("/static/"):
                self.send_file(STATIC / path[len("/static/"):])
            elif path == "/api/status":
                self.send_json(get_status())
            elif path == "/api/comports":
                self.send_json(get_comports())
            elif path == "/api/config/env":
                self.send_json(get_env_config())
            elif path == "/api/config/firmware":
                self.send_json({
                    "sdkconfigExists": SDKCONFIG.exists(),
                    "values": read_sdkconfig_values(),
                })
            else:
                m = re.fullmatch(r"/api/actions/([\w-]+)/logs", path)
                if m:
                    self.stream_job_logs(m.group(1))
                else:
                    self.send_json({"detail": "未知路径"}, 404)
        except ApiError as e:
            self.send_json({"detail": e.message}, e.status)
        except Exception as e:  # noqa: BLE001
            self.send_json({"detail": "服务器内部错误：{}".format(e)}, 500)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self.read_body()
            if path == "/api/config/env":
                self.send_json(save_env_config(body))
            elif path == "/api/config/firmware":
                self.send_json(save_firmware_config(body))
            else:
                m = re.fullmatch(r"/api/actions/([\w-]+)(/stop)?", path)
                if not m:
                    self.send_json({"detail": "未知路径"}, 404)
                    return
                name, is_stop = m.group(1), bool(m.group(2))
                if is_stop:
                    if name not in STOPPABLE:
                        raise ApiError(400, "任务 {} 不支持停止".format(name))
                    get_job(name).stop()
                    self.send_json({"ok": True})
                elif name in CONSOLE_ACTIONS:
                    CONSOLE_ACTIONS[name](body)
                    self.send_json({"ok": True, "console": True})
                elif name in ACTIONS:
                    ACTIONS[name](body)
                    self.send_json({"ok": True})
                else:
                    self.send_json({"detail": "未知动作 {}".format(name)}, 404)
        except ApiError as e:
            self.send_json({"detail": e.message}, e.status)
        except Exception as e:  # noqa: BLE001
            self.send_json({"detail": "服务器内部错误：{}".format(e)}, 500)


def main():
    parser = argparse.ArgumentParser(description="IoTCmpt 本地配置面板")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("IoTCmpt 配置面板已启动：http://127.0.0.1:{}".format(args.port))
    print("关闭此窗口（或按 Ctrl+C）即可停止面板。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
