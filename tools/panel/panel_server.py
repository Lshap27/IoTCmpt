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
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

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
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(TOOLS / script),
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

    def start(self, cmd, cwd, on_success=None):
        if self.proc and self.proc.poll() is None:
            raise ApiError(409, "任务 {} 正在运行中".format(self.name))
        with self.lock:
            self.lines = []
            self.trimmed = 0
            self.generation += 1
            self.status = "running"
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            with self.lock:
                self.status = "failed"
            raise ApiError(
                500,
                "未找到命令 {}。请先安装它（例如 docker / uv / pnpm），"
                "或改用 Docker 演示栈。".format(cmd[0]),
            )
        threading.Thread(target=self._pump, args=(on_success,), daemon=True).start()

    def _pump(self, on_success):
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
        if code == 0 and on_success:
            try:
                on_success()
            except Exception as exc:  # noqa: BLE001
                with self.lock:
                    self.lines.append("[后续操作失败] {}".format(exc))

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


def environment_args(action, body=None):
    body = body or {}
    args = ps_file_args("environment-manager.ps1", "-Action", action)
    components = body.get("components") or []
    if components:
        if not isinstance(components, list):
            raise ApiError(400, "components 必须是数组")
        args += ["-Components", ",".join(str(item) for item in components)]
    if body.get("networkMode"):
        args += ["-NetworkMode", str(body["networkMode"])]
    if body.get("proxyUrl"):
        args += ["-ProxyUrl", str(body["proxyUrl"])]
    if body.get("mirrorUrl"):
        args += ["-MirrorUrl", str(body["mirrorUrl"])]
    if body.get("confirm"):
        args += ["-Confirm", str(body["confirm"])]
    return args


def start_environment_job(action, body):
    get_job("environment").start(environment_args(action, body), REPO)


SIMULATOR_SCENARIOS = {"normal", "air-alert", "smoke"}
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def write_compose_env_value(key, value):
    path = REPO / ".env"
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    replacement = "{}={}".format(key, value)
    pattern = re.compile(r"^{}=".format(re.escape(key)))
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def simulator_config(body=None):
    body = body or {}
    compose = parse_env(REPO / ".env")
    scenario = str(
        body.get("scenario") or compose.get("AIOT_DEMO_SCENARIO") or "air-alert"
    )
    device_id = str(
        body.get("deviceId") or compose.get("AIOT_DEMO_DEVICE_ID") or "esp32s3-001"
    )
    if scenario not in SIMULATOR_SCENARIOS:
        raise ApiError(400, "模拟场景必须是 normal、air-alert 或 smoke")
    if not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise ApiError(
            400, "设备 ID 必须为 1-64 位，只能包含字母、数字、点、下划线和连字符"
        )
    return compose, scenario, device_id


def start_simulator(body=None, automatic=False):
    compose, scenario, device_id = simulator_config(body)
    if automatic and compose.get("AIOT_DEMO_DEVICE_MODE", "Simulator") != "Simulator":
        return
    job = get_job("simulator")
    if job.running():
        if automatic:
            return
        job.stop()
        for _ in range(20):
            if not job.running():
                break
            time.sleep(0.1)
        if job.running():
            raise ApiError(409, "旧虚拟设备尚未停止，请稍后重试")
    if automatic:
        for _ in range(60):
            if probe(1883) and backend_ready():
                break
            time.sleep(1)
        else:
            raise RuntimeError("等待 MQTT 和后端就绪超时，虚拟设备未启动")
    elif not (probe(1883) and probe(8000)):
        raise ApiError(409, "请先启动 Docker 演示栈或后端与 MQTT 服务")

    python = REPO / "server" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise ApiError(409, "缺少 server/.venv；请先在环境中心点击“一键补全演示环境”")
    write_compose_env_value("AIOT_DEMO_SCENARIO", scenario)
    job.start(
        [
            str(python),
            str(TOOLS / "simulate-device.py"),
            "--scenario",
            scenario,
            "--device-id",
            device_id,
        ],
        REPO,
    )


def backend_ready():
    try:
        with urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def start_docker_stack(_body):
    get_job("docker-up").start(
        ["docker", "compose", "up", "--build", "-d"],
        REPO,
        on_success=lambda: start_simulator(automatic=True),
    )


def stop_docker_stack(_body):
    simulator = get_job("simulator")
    if simulator.running():
        simulator.stop()
    get_job("docker-down").start(["docker", "compose", "down"], REPO)


ACTIONS = {
    "docker-up": start_docker_stack,
    "docker-down": stop_docker_stack,
    "docker-logs": lambda b: get_job("docker-logs").start(
        ["docker", "compose", "logs", "-f", "--tail", "100"], REPO
    ),
    "backend-start": lambda b: get_job("backend").start(
        ["uv", "run", "python", "run_dev.py"], REPO / "server"
    ),
    "frontend-start": lambda b: get_job("frontend").start(
        ["cmd", "/c", "pnpm", "dev"], REPO / "web"
    ),
    "simulator-start": lambda b: start_simulator(b),
    "idf-build": lambda b: get_job("idf").start(
        ps_file_args("esp-idf-task.ps1", "-Action", "Build"), FIRMWARE
    ),
    "idf-flash": lambda b: get_job("idf").start(
        ps_file_args("esp-idf-task.ps1", "-Action", "Flash", *port_args(b)), FIRMWARE
    ),
    "env-install": lambda b: start_environment_job("Install", b),
    "env-uninstall": lambda b: start_environment_job("Uninstall", b),
    "env-network": lambda b: start_environment_job("Network", b),
    "env-test": lambda b: start_environment_job("TestNetwork", b),
}

CONSOLE_ACTIONS = {
    "idf-menuconfig": lambda b: start_console_window(
        ps_file_args("esp-idf-task.ps1", "-Action", "Menuconfig"), FIRMWARE
    ),
    "idf-monitor": lambda b: start_console_window(
        ps_file_args("esp-idf-task.ps1", "-Action", "Monitor", *port_args(b)), FIRMWARE
    ),
    "idf-flash-monitor": lambda b: start_console_window(
        ps_file_args("esp-idf-task.ps1", "-Action", "FlashMonitor", *port_args(b)),
        FIRMWARE,
    ),
}

STOPPABLE = {"docker-logs", "backend", "frontend", "simulator", "idf", "environment"}


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


def validate_http_url(value, label):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ApiError(400, "{}必须是完整的 http(s) 地址".format(label))


def normalize_trigger_levels(value):
    if isinstance(value, list):
        levels = value
    else:
        levels = str(value or "").split(",")
    levels = list(
        dict.fromkeys(str(item).strip().lower() for item in levels if str(item).strip())
    )
    allowed = {"good", "watch", "alert"}
    if not levels or any(level not in allowed for level in levels):
        raise ApiError(
            400, "自动处置触发级别只能选择 good、watch、alert，且至少选择一项"
        )
    return levels


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
    ("autopilotEnabled", "-AutopilotEnabled"),
]


def save_env_config(body):
    device_mode = body.get("deviceMode")
    ai_mode = body.get("aiMode")
    if device_mode is not None or ai_mode is not None:
        if device_mode not in ("Simulator", "Real"):
            raise ApiError(400, "设备来源必须是 Simulator 或 Real")
        if ai_mode not in ("Mock", "Online"):
            raise ApiError(400, "AI 模式必须是 Mock 或 Online")
        endpoint = str(body.get("llmEndpoint") or "").strip().rstrip("/")
        body["llmEndpoint"] = endpoint
        if ai_mode == "Online" and (not endpoint or endpoint == "mock"):
            raise ApiError(400, "在线大模型需要填写真实 LLM 接口地址")
        if ai_mode == "Online":
            validate_http_url(endpoint, "LLM 接口地址")
            if not str(body.get("llmModel") or "").strip():
                raise ApiError(400, "在线大模型需要填写模型名称")
        if ai_mode == "Mock":
            body["llmEndpoint"] = "mock"
            body["llmModel"] = "demo-model"
        preset = (
            "DeviceDemo"
            if device_mode == "Real"
            else ("LlmDemo" if ai_mode == "Online" else "MockDemo")
        )
    else:
        # 兼容旧版面板和现有 VS Code 任务使用的预设名称。
        preset = body.get("preset", "MockDemo")
    if preset not in ("MockDemo", "DeviceDemo", "LlmDemo"):
        raise ApiError(400, "未知预设 {}".format(preset))
    device_id = str(body.get("deviceId") or "esp32s3-001").strip()
    if not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise ApiError(
            400, "设备 ID 必须为 1-64 位，只能包含字母、数字、点、下划线和连字符"
        )
    body["deviceId"] = device_id
    try:
        confidence = float(body.get("autopilotMinConfidence", 0.6))
    except (TypeError, ValueError):
        raise ApiError(400, "自动处置最低置信度必须是 0 到 1 之间的数字")
    if not 0 <= confidence <= 1:
        raise ApiError(400, "自动处置最低置信度必须在 0 到 1 之间")
    body["autopilotMinConfidence"] = str(confidence)
    body["autopilotTriggerLevels"] = ",".join(
        normalize_trigger_levels(body.get("autopilotTriggerLevels", "alert"))
    )
    args = ["-Preset", preset, "-NonInteractive"]
    if device_mode is not None:
        args += ["-DemoDeviceMode", device_mode, "-DemoAiMode", ai_mode]
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
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise ApiError(500, "配置脚本失败：{}\n{}".format(result.stdout, result.stderr))

    stack_reconfigured = False
    if probe(8000) or probe(1883) or probe(3000):
        simulator = get_job("simulator")
        if simulator.running():
            simulator.stop()
        compose = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if compose.returncode != 0:
            raise ApiError(
                500, "配置已保存，但 Docker 栈重新应用失败：{}".format(compose.stderr)
            )
        stack_reconfigured = True
        if device_mode == "Simulator":
            start_simulator({"deviceId": device_id}, automatic=True)
    return {
        "ok": True,
        "output": result.stdout,
        "stackReconfigured": stack_reconfigured,
    }


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
    "CONFIG_APP_LED_ENABLED": "bool",
    "CONFIG_APP_LED_GPIO": "int",
    "CONFIG_APP_LED_ACTIVE_LOW": "bool",
    "CONFIG_APP_CAMERA_UPLOAD_INTERVAL_MS": "int",
}

PANEL_FIRMWARE_DEFAULTS = {
    "CONFIG_APP_DEVICE_ID": "esp32s3-001",
    "CONFIG_APP_SENSOR_MOCK_ENABLED": False,
    "CONFIG_APP_SENSOR_INTERVAL_MS": "2500",
    "CONFIG_APP_WIFI_ENABLED": True,
    "CONFIG_APP_MQTT_ENABLED": True,
    "CONFIG_APP_IMAGE_UPLOAD_ENABLED": True,
    "CONFIG_APP_CAMERA_ENABLED": True,
    "CONFIG_APP_DISPLAY_ENABLED": True,
    "CONFIG_APP_ACTUATOR_ENABLED": True,
    "CONFIG_APP_BUTTON_ENABLED": True,
    "CONFIG_APP_MQ2_ENABLED": True,
    "CONFIG_APP_VOICE_ENABLED": True,
    "CONFIG_APP_LED_ENABLED": True,
    "CONFIG_APP_LED_GPIO": "41",
    "CONFIG_APP_LED_ACTIVE_LOW": False,
    "CONFIG_APP_CAMERA_UPLOAD_INTERVAL_MS": "2000",
}

LEGACY_LED_KEYS = ("CONFIG_APP_LED_MODE_GPIO", "CONFIG_APP_LED_MODE_LOGICAL")


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
    if SDKCONFIG.exists():
        return {**PANEL_FIRMWARE_DEFAULTS, **values}
    return {**values, **PANEL_FIRMWARE_DEFAULTS}


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

    device_id = str(values.get("CONFIG_APP_DEVICE_ID") or "").strip()
    if device_id and not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise ApiError(
            400, "固件设备 ID 必须为 1-64 位，只能包含字母、数字、点、下划线和连字符"
        )
    if "CONFIG_APP_SENSOR_INTERVAL_MS" in values:
        try:
            interval = int(values["CONFIG_APP_SENSOR_INTERVAL_MS"])
        except (TypeError, ValueError):
            raise ApiError(400, "传感器采集间隔必须是整数")
        if not 1000 <= interval <= 60000:
            raise ApiError(400, "传感器采集间隔必须在 1000 到 60000 毫秒之间")
    if "CONFIG_APP_CAMERA_UPLOAD_INTERVAL_MS" in values:
        interval = int(values["CONFIG_APP_CAMERA_UPLOAD_INTERVAL_MS"])
        if not 1000 <= interval <= 60000:
            raise ApiError(400, "摄像头上传间隔必须在 1000 到 60000 毫秒之间")
    if values.get("CONFIG_APP_LED_ENABLED"):
        led_gpio = int(values.get("CONFIG_APP_LED_GPIO", 41))
        if not 0 <= led_gpio <= 48:
            raise ApiError(400, "LED GPIO 必须在 0 到 48 之间")
    if (
        values.get("CONFIG_APP_WIFI_ENABLED")
        and not str(values.get("CONFIG_APP_WIFI_SSID") or "").strip()
    ):
        raise ApiError(400, "启用 Wi-Fi 时必须填写 Wi-Fi 名称")
    if values.get("CONFIG_APP_MQTT_ENABLED"):
        mqtt = urlparse(str(values.get("CONFIG_APP_MQTT_BROKER_URI") or "").strip())
        if mqtt.scheme not in ("mqtt", "mqtts") or not mqtt.netloc:
            raise ApiError(400, "MQTT 服务器地址必须是完整的 mqtt:// 或 mqtts:// 地址")
    if values.get("CONFIG_APP_IMAGE_UPLOAD_ENABLED"):
        validate_http_url(values.get("CONFIG_APP_IMAGE_UPLOAD_URL"), "图片上传地址")

    if SDKCONFIG.exists():
        text = SDKCONFIG.read_text(encoding="utf-8", errors="replace")
    elif SDKCONFIG_DEFAULTS.exists():
        # 首次写入：以 defaults 播种，idf.py 下次构建会补全其余选项
        text = SDKCONFIG_DEFAULTS.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    for legacy_key in LEGACY_LED_KEYS:
        pattern = r"^(?:{0}=.*|# {0} is not set)\r?\n?".format(
            re.escape(legacy_key)
        )
        text = re.sub(pattern, "", text, flags=re.M)

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
    # Windows hostname resolution often returns WSL/Hyper-V adapters first.
    # Prefer a connected physical adapter ordered by Windows interface metric.
    try:
        script = (
            "$m=@{}; Get-NetIPInterface -AddressFamily IPv4 -ConnectionState Connected | "
            "% {$m[$_.InterfaceIndex]=$_.InterfaceMetric}; "
            "Get-NetIPAddress -AddressFamily IPv4 | ? {"
            "$_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' -and "
            "$_.InterfaceAlias -notmatch 'vEthernet|WSL|Hyper-V|Default Switch|Docker|Loopback|Clash|TUN|TAP|Tailscale|VPN|WireGuard|Wintun|ZeroTier'"
            "} | sort {$m[$_.InterfaceIndex]} | select -ExpandProperty IPAddress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        candidates.extend(line.strip() for line in result.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        pass
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
    return list(dict.fromkeys(usable))[0]


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
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-Command",
            "[System.IO.Ports.SerialPort]::GetPortNames() -join ','",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    ports = [p for p in result.stdout.strip().split(",") if p]
    return {"ports": ports}


def get_environment():
    result = subprocess.run(
        environment_args("Check"),
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise ApiError(500, "环境检查失败：{}".format(result.stderr or result.stdout))
    try:
        return json.loads(result.stdout.lstrip("\ufeff"))
    except ValueError:
        raise ApiError(500, "环境检查返回了无效数据")


# ---------------------------------------------------------------- data tools


def run_data_tool(operation, body):
    payload = json.dumps(body or {}, ensure_ascii=False)
    try:
        container = subprocess.run(
            [
                "docker",
                "compose",
                "ps",
                "--status",
                "running",
                "-q",
                "server",
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        container_running = container.returncode == 0 and bool(
            container.stdout.strip()
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        container_running = False
    if container_running:
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "server",
            "python",
            "-m",
            "app.tools.data_manager",
            operation,
        ]
        cwd = REPO
    else:
        venv_python = REPO / "server" / ".venv" / "Scripts" / "python.exe"
        command = (
            [str(venv_python), "-m", "app.tools.data_manager", operation]
            if venv_python.exists()
            else ["uv", "run", "python", "-m", "app.tools.data_manager", operation]
        )
        cwd = REPO / "server"
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise ApiError(503, "数据工具需要运行中的 Docker server 或本机 uv 环境") from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError(504, "数据操作超时，请缩短时间范围后重试") from exc

    output = result.stdout.strip()
    try:
        data = json.loads(output) if output else {}
    except ValueError as exc:
        raise ApiError(
            500,
            "数据工具返回了无效结果：{}".format(result.stderr.strip() or output),
        ) from exc
    if result.returncode != 0:
        detail = data.get("detail") or result.stderr.strip() or "数据操作失败"
        if "No module named 'app.tools'" in detail:
            detail = "运行中的 server 镜像尚未包含数据工具，请重新构建 Docker 演示栈"
        raise ApiError(400 if result.returncode == 2 else 500, detail)
    return data


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
            CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream"),
        )
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
                        "event: end\ndata: {}\n\n".format(status).encode("utf-8")
                    )
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
                self.send_file(STATIC / path[len("/static/") :])
            elif path == "/api/status":
                self.send_json(get_status())
            elif path == "/api/comports":
                self.send_json(get_comports())
            elif path == "/api/environment":
                self.send_json(get_environment())
            elif path == "/api/config/env":
                self.send_json(get_env_config())
            elif path == "/api/config/firmware":
                self.send_json(
                    {
                        "sdkconfigExists": SDKCONFIG.exists(),
                        "values": read_sdkconfig_values(),
                    }
                )
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
            elif path == "/api/data/preview":
                self.send_json(run_data_tool("preview", body))
            elif path == "/api/data/cleanup":
                self.send_json(run_data_tool("cleanup", body))
            elif path == "/api/data/demo":
                self.send_json(run_data_tool("demo", body))
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
