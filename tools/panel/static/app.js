// IoTCmpt 配置面板前端逻辑（无构建步骤，vanilla JS）
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const PANEL_TOKEN =
  document.querySelector('meta[name="panel-token"]')?.content || "";

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Panel-Token": PANEL_TOKEN,
    },
    body: JSON.stringify(body || {}),
  });
}

// ------------------------------------------------------------------ 标签页
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("#tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ------------------------------------------------------------------ 状态栏
let lanIp = "";
function renderSimulatorStatus(status) {
  const root = $("#simulatorStatus");
  if (!root) return;
  root.replaceChildren();
  if (!status?.ready) {
    const empty = document.createElement("span");
    empty.className = "simulator-status-empty";
    empty.textContent = status?.reason || "模拟器状态未就绪";
    root.append(empty);
    return;
  }
  const state = status.state || {};
  const last = status.last_command || {};
  const values = [
    ["MQTT", status.mqtt_connected ? "已连接" : "未连接"],
    ["场景", status.scenario || "—"],
    ["Boot ID", status.boot_id ? status.boot_id.slice(0, 8) : "—"],
    [
      "最近遥测",
      status.last_telemetry_at
        ? new Date(status.last_telemetry_at).toLocaleTimeString()
        : "—",
    ],
    [
      "计数",
      `遥测 ${status.telemetry_count || 0} · 命令 ${status.command_count || 0}`,
    ],
    [
      "窗户 / LED",
      `${state.window_open ? "开" : "关"} / ${state.led_on ? "开" : "关"}`,
    ],
    [
      "报警",
      state.alarm_on ? (state.smoke_silenced ? "已静音" : "开启") : "关闭",
    ],
    [
      "优先级",
      state.control_priority === "auto_first" ? "自动优先" : "人工优先",
    ],
    [
      "最近命令",
      last.command_id
        ? `${last.command_id.slice(0, 12)} · ${last.status || "—"}`
        : "—",
    ],
  ];
  for (const [label, value] of values) {
    const item = document.createElement("span");
    const name = document.createElement("small");
    const content = document.createElement("b");
    name.textContent = label;
    content.textContent = value;
    item.append(name, content);
    root.append(item);
  }
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    lanIp = s.lanIp;
    $("#lanIp").textContent = s.lanIp;
    for (const [key, on] of Object.entries(s.ports)) {
      const dot = $("#dot-" + key);
      if (dot) dot.classList.toggle("on", on);
    }
    const simulatorRunning = !!s.jobs?.simulator?.running;
    $("#dot-simulator")?.classList.toggle("on", simulatorRunning);
    renderSimulatorStatus(s.simulator);
    for (const [key, on] of Object.entries(s.services || {})) {
      $("#dot-" + key)?.classList.toggle("on", on);
    }
  } catch (_) {
    /* 面板自身请求失败时静默 */
  }
}
refreshStatus();
setInterval(refreshStatus, 4000);

// ------------------------------------------------------------------ 电脑环境中心
let environmentData = null;

function selectedEnvironmentComponents() {
  return [...$$('#componentList input[type="checkbox"]:checked')].map(
    (el) => el.value,
  );
}

function renderEnvironment(data) {
  environmentData = data;
  const summary = $("#envSummary");
  const required = data.components.filter((item) => item.required);
  const missing = required.filter((item) => !item.ready);
  summary.className =
    "health-summary " + (missing.length ? "warning" : "ready");
  summary.innerHTML = missing.length
    ? `<span class="health-orb" aria-hidden="true"></span><div><b>还差 ${missing.length} 项即可启动演示</b><small>${missing.map((item) => item.label).join("、")}</small></div>`
    : '<span class="health-orb" aria-hidden="true"></span><div><b>演示环境已就绪</b><small>Docker、Compose 和基础工具状态正常</small></div>';

  const list = $("#componentList");
  list.replaceChildren();
  for (const item of data.components) {
    const label = document.createElement("label");
    label.className = "component-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = item.id;
    checkbox.disabled = !item.canInstall && !item.canUninstall;
    const copy = document.createElement("span");
    copy.className = "component-copy";
    const name = document.createElement("b");
    name.textContent = item.label + (item.required ? " · 必需" : " · 可选");
    const detail = document.createElement("small");
    detail.textContent = [item.version, item.detail]
      .filter(Boolean)
      .join(" · ");
    copy.append(name, detail);
    const pill = document.createElement("span");
    if (item.ready) {
      pill.className = "status-pill ok";
      pill.textContent = "就绪";
    } else if (item.installed) {
      pill.className = "status-pill warn";
      pill.textContent = "需修复";
    } else {
      pill.className = "status-pill missing";
      pill.textContent = "未安装";
    }
    label.append(checkbox, copy, pill);
    list.appendChild(label);
  }

  const network = data.network;
  const notice = $("#networkNotice");
  const mirror = (network.registryMirrors || []).join("、") || "官方源";
  notice.className =
    "network-notice" +
    (network.warning
      ? network.warningLevel === "info"
        ? " info"
        : " warn"
      : "");
  notice.textContent =
    network.warning ||
    `Docker Hub DNS：${(network.dockerHubDns || []).join(", ") || "未解析"}；当前镜像：${mirror}；系统代理：${network.systemProxyEnabled ? network.systemProxy : "未启用"}`;
  if (network.systemProxy) {
    const value = network.systemProxy.match(/^https?:\/\//)
      ? network.systemProxy
      : `http://${network.systemProxy}`;
    $("#proxyUrl").value = value;
  }
  if ((network.registryMirrors || []).length)
    $("#mirrorUrl").value = network.registryMirrors[0];
}

async function loadEnvironment() {
  const summary = $("#envSummary");
  summary.className = "health-summary checking";
  summary.innerHTML =
    '<span class="health-orb" aria-hidden="true"></span><div><b>正在检查这台电脑……</b><small>Docker、运行环境和网络状态</small></div>';
  try {
    renderEnvironment(await api("/api/environment"));
  } catch (e) {
    summary.className = "health-summary warning";
    summary.innerHTML = `<span class="health-orb" aria-hidden="true"></span><div><b>环境检查失败</b><small>${e.message}</small></div>`;
  }
}

function startEnvironmentAction(action, body, label) {
  const msg = $("#systemMsg");
  msg.className = "msg";
  msg.textContent = label + "已启动……";
  return post(`/api/actions/${action}`, body)
    .then(() => {
      const log = $("#environmentLog");
      log.textContent = `[${label}] 已启动\n`;
      streamLogs("environment", log, loadEnvironment);
    })
    .catch((e) => {
      msg.className = "msg err";
      msg.textContent = "✘ " + e.message;
    });
}

$("#btnEnvCheck").addEventListener("click", loadEnvironment);
$("#btnEnvComplete").addEventListener("click", () =>
  startEnvironmentAction(
    "env-install",
    { components: ["demo"] },
    "补全演示环境",
  ),
);
$("#btnEnvInstallSelected").addEventListener("click", () => {
  const components = selectedEnvironmentComponents();
  if (!components.length) {
    alert("请先勾选要安装的组件");
    return;
  }
  startEnvironmentAction("env-install", { components }, "安装所选组件");
});
$("#btnRepairIdf").addEventListener("click", () =>
  startEnvironmentAction(
    "env-install",
    { components: ["espidf"] },
    "安装 / 修复 ESP-IDF 工具链",
  ),
);

const uninstallDialog = $("#uninstallDialog");
$("#btnEnvRemove").addEventListener("click", () => {
  const components = selectedEnvironmentComponents();
  if (!components.length) {
    alert("请先勾选要卸载的组件");
    return;
  }
  $("#uninstallText").textContent =
    `将卸载：${components.join("、")}。项目文件和 Docker 数据卷不会被主动删除。`;
  uninstallDialog.dataset.components = JSON.stringify(components);
  uninstallDialog.showModal();
});
uninstallDialog.addEventListener("close", () => {
  if (uninstallDialog.returnValue !== "confirm") return;
  const components = JSON.parse(uninstallDialog.dataset.components || "[]");
  startEnvironmentAction(
    "env-uninstall",
    { components, confirm: "UNINSTALL" },
    "卸载所选组件",
  );
});

$("#btnOfficialSource").addEventListener("click", () =>
  startEnvironmentAction(
    "env-network",
    { networkMode: "Official" },
    "切回 Docker Hub 官方源",
  ),
);
$("#btnChinaMirror").addEventListener("click", () =>
  startEnvironmentAction(
    "env-network",
    { networkMode: "ChinaMirror", mirrorUrl: $("#mirrorUrl").value },
    "切换国内镜像",
  ),
);
$("#btnAutoProxy").addEventListener("click", () =>
  startEnvironmentAction(
    "env-network",
    { networkMode: "SystemProxy" },
    "自动配置系统代理",
  ),
);
$("#btnManualProxy").addEventListener("click", () =>
  startEnvironmentAction(
    "env-network",
    { networkMode: "ManualProxy", proxyUrl: $("#proxyUrl").value },
    "配置手动代理",
  ),
);
$("#btnNetworkTest").addEventListener("click", () =>
  startEnvironmentAction("env-test", {}, "测试 Docker 网络"),
);

loadEnvironment();

// ------------------------------------------------------------------ 环境配置
const ONLINE_LLM_DEFAULTS = {
  endpoint: "https://ai-gateway.vei.volces.com/v1",
  model: "Doubao-Seed-1.6-flash",
};
let onlineLlmDraft = { ...ONLINE_LLM_DEFAULTS };

function selectedMode(name) {
  return document.querySelector(`input[name=${name}]:checked`).value;
}

function setModeFields(selector, enabled) {
  for (const label of $$(selector)) {
    label.classList.toggle("mode-disabled", !enabled);
    for (const control of label.querySelectorAll("input, button, select")) {
      control.disabled = !enabled;
    }
  }
}

function syncModeFields() {
  setModeFields(
    '[data-for-device="real"]',
    selectedMode("deviceMode") === "Real",
  );
  setModeFields('[data-for-ai="online"]', selectedMode("aiMode") === "Online");
  setModeFields(
    '[data-for-device="simulator"]',
    selectedMode("deviceMode") === "Simulator",
  );
  $("#simulatorImageInterval").disabled =
    selectedMode("deviceMode") !== "Simulator" ||
    !$("#simulatorImageEnabled").checked;
}

function switchAiMode() {
  if (selectedMode("aiMode") === "Online") {
    $("#llmEndpoint").value = onlineLlmDraft.endpoint;
    $("#llmModel").value = onlineLlmDraft.model;
  } else {
    const endpoint = $("#llmEndpoint").value.trim();
    if (endpoint && endpoint !== "mock") {
      onlineLlmDraft = {
        endpoint,
        model: $("#llmModel").value.trim() || ONLINE_LLM_DEFAULTS.model,
      };
    }
    $("#llmEndpoint").value = "mock";
    $("#llmModel").value = "demo-model";
  }
  syncModeFields();
}

async function loadEnvConfig() {
  try {
    const data = await api("/api/config/env");
    const server = data.server.values || {};
    const compose = data.compose.values || {};
    const endpoint = server.AIOT_LLM_ENDPOINT || "mock";
    const online = endpoint !== "mock";
    const realDevice = compose.AIOT_DEMO_DEVICE_MODE
      ? compose.AIOT_DEMO_DEVICE_MODE === "Real"
      : !!server.AIOT_BASE_URL &&
        !/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/i.test(
          server.AIOT_BASE_URL,
        );
    document.querySelector(
      `input[name=aiMode][value=${online ? "Online" : "Mock"}]`,
    ).checked = true;
    document.querySelector(
      `input[name=deviceMode][value=${realDevice ? "Real" : "Simulator"}]`,
    ).checked = true;
    if (online) {
      onlineLlmDraft = {
        endpoint,
        model: server.AIOT_LLM_MODEL || ONLINE_LLM_DEFAULTS.model,
      };
    }
    $("#llmEndpoint").value = online ? endpoint : "mock";
    if (server.AIOT_LLM_MODEL) $("#llmModel").value = server.AIOT_LLM_MODEL;
    $("#llmTimeoutSeconds").value = server.AIOT_LLM_TIMEOUT_SECONDS || "60";
    $("#ackTimeoutSeconds").value =
      server.AIOT_COMMAND_ACK_TIMEOUT_SECONDS || "60";
    $("#toolMaxRounds").value = server.AIOT_AI_TOOL_MAX_ROUNDS || "4";
    $("#toolMaxCalls").value = server.AIOT_AI_TOOL_MAX_CALLS || "8";
    $("#mcpEnabled").checked = server.AIOT_MCP_ENABLED === "true";
    if (compose.AIOT_DEMO_DEVICE_ID) {
      $("#deviceId").value = compose.AIOT_DEMO_DEVICE_ID;
      $("#dataDeviceId").value = compose.AIOT_DEMO_DEVICE_ID;
    }
    if (compose.AIOT_DEMO_SCENARIO)
      $("#simulatorScenario").value = compose.AIOT_DEMO_SCENARIO;
    $("#simulatorInterval").value =
      compose.AIOT_SIMULATOR_TELEMETRY_INTERVAL_SECONDS || "2";
    $("#simulatorImageEnabled").checked =
      compose.AIOT_SIMULATOR_IMAGE_ENABLED !== "false";
    $("#simulatorImageInterval").value =
      compose.AIOT_SIMULATOR_IMAGE_INTERVAL_SECONDS || "30";
    syncModeFields();
  } catch (_) {
    switchAiMode();
  }
}
loadEnvConfig();

$$('input[name="aiMode"]').forEach((input) =>
  input.addEventListener("change", switchAiMode),
);
$$('input[name="deviceMode"]').forEach((input) =>
  input.addEventListener("change", () => {
    if (
      selectedMode("deviceMode") === "Real" &&
      !$("#lanAddress").value &&
      lanIp
    ) {
      $("#lanAddress").value = lanIp;
    }
    syncModeFields();
  }),
);
$("#simulatorImageEnabled").addEventListener("change", syncModeFields);
$("#btnDetectIp").addEventListener("click", () => {
  $("#lanAddress").value = lanIp;
});

$("#btnSaveEnv").addEventListener("click", async () => {
  const msg = $("#envMsg");
  msg.className = "msg";
  msg.textContent = "保存中……";
  const deviceMode = selectedMode("deviceMode");
  const aiMode = selectedMode("aiMode");
  const llmEndpoint = $("#llmEndpoint").value.trim();
  const deviceId = $("#deviceId");
  if (!deviceId.reportValidity()) {
    msg.className = "msg err";
    msg.textContent = "✘ 请修正标红的配置项";
    return;
  }
  if (aiMode === "Online" && (!llmEndpoint || llmEndpoint === "mock")) {
    msg.className = "msg err";
    msg.textContent = "✘ 在线大模型需要填写真实 LLM 接口地址";
    $("#llmEndpoint").focus();
    return;
  }
  const body = {
    deviceMode,
    aiMode,
    deviceId: deviceId.value || null,
    lanAddress: $("#lanAddress").value || null,
    llmEndpoint: llmEndpoint || null,
    llmModel: $("#llmModel").value || null,
    llmApiKey: $("#llmApiKey").value || null,
    llmTimeoutSeconds: $("#llmTimeoutSeconds").value,
    ackTimeoutSeconds: $("#ackTimeoutSeconds").value,
    toolMaxRounds: $("#toolMaxRounds").value,
    toolMaxCalls: $("#toolMaxCalls").value,
    mcpEnabled: $("#mcpEnabled").checked,
    mcpReadToken: $("#mcpReadToken").value || null,
    mcpControlToken: $("#mcpControlToken").value || null,
    scenario: $("#simulatorScenario").value,
    interval: $("#simulatorInterval").value,
    imageEnabled: $("#simulatorImageEnabled").checked,
    imageInterval: $("#simulatorImageInterval").value,
  };
  try {
    const preview = await post("/api/config/env", { ...body, preview: true });
    const lines = preview.diff.map(
      (item) => `${item.file}: ${item.key} → ${item.after ?? "删除"}`,
    );
    const affected = preview.affectedServices.join("、") || "无";
    if (
      !window.confirm(
        `将修改：\n${lines.join("\n")}\n\n需重启：${affected}\n\n确认保存？`,
      )
    ) {
      msg.textContent = "已取消保存";
      return;
    }
    const result = await post("/api/config/env", body);
    msg.className = "msg ok";
    msg.textContent = `✔ 配置已保存；请在服务页重启：${result.affectedServices.join("、") || "无"}`;
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = "✘ 保存失败：" + e.message;
  }
});

// ------------------------------------------------------------------ 日志流
const logStreams = {};
function streamLogs(jobName, targetEl, onEnd) {
  if (logStreams[jobName]) logStreams[jobName].close();
  const es = new EventSource(`/api/actions/${jobName}/logs`);
  logStreams[jobName] = es;
  targetEl.classList.add("running"); // 终端闪烁光标（见 style.css .log.running）
  const settle = () => {
    es.close();
    targetEl.classList.remove("running");
    if (onEnd) onEnd();
  };
  es.onmessage = (ev) => {
    targetEl.textContent += ev.data + "\n";
    targetEl.scrollTop = targetEl.scrollHeight;
  };
  es.addEventListener("end", settle);
  es.onerror = settle;
}

const JOB_OF_ACTION = {
  "docker-up": "docker-up",
  "docker-down": "docker-down",
  "docker-logs": "docker-logs",
  "backend-start": "backend",
  "frontend-start": "frontend",
  "simulator-start": "simulator",
  "simulator-reboot": "simulator",
  "simulator-clear-nvs": "simulator",
  "idf-build": "idf",
  "idf-flash": "idf",
};

const LOG_TARGET = (jobName) =>
  jobName.startsWith("idf") ? $("#idfLog") : $("#svcLog");

$$("button[data-action]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const action = btn.dataset.action;
    const body = {};
    if (action.startsWith("idf-")) {
      const port = $("#comPort").value;
      if (port) body.port = port;
    }
    if (action.startsWith("simulator-")) {
      body.scenario = $("#simulatorScenario").value;
      body.deviceId = $("#deviceId").value || "esp32s3-001";
      body.interval = $("#simulatorInterval").value;
      body.imageEnabled = $("#simulatorImageEnabled").checked;
      body.imageInterval = $("#simulatorImageInterval").value;
    }
    if (
      action === "simulator-clear-nvs" &&
      !window.confirm(
        "确定清除模拟 NVS？控制优先级和最近终态 ACK 将丢失；运行中的模拟器会自动重启。",
      )
    ) {
      return;
    }
    try {
      const result = await post(`/api/actions/${action}`, body);
      if (result.console) return; // 在独立窗口中运行
      const jobName = JOB_OF_ACTION[action];
      if (jobName) {
        const el = LOG_TARGET(jobName);
        el.textContent = `[${action}] 已启动\n`;
        streamLogs(jobName, el);
      }
    } catch (e) {
      alert("操作失败：" + e.message);
    }
  });
});

$$("button[data-stop]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      await post(`/api/actions/${btn.dataset.stop}/stop`);
    } catch (e) {
      alert("停止失败：" + e.message);
    }
  });
});

// ------------------------------------------------------------------ 固件配置
const FW_BOOL_KEYS = [
  "CONFIG_APP_SENSOR_MOCK_ENABLED",
  "CONFIG_APP_WIFI_ENABLED",
  "CONFIG_APP_MQTT_ENABLED",
  "CONFIG_APP_IMAGE_UPLOAD_ENABLED",
  "CONFIG_APP_CAMERA_ENABLED",
  "CONFIG_APP_DISPLAY_ENABLED",
  "CONFIG_APP_ACTUATOR_ENABLED",
  "CONFIG_APP_BUTTON_ENABLED",
  "CONFIG_APP_MQ2_ENABLED",
  "CONFIG_APP_VOICE_ENABLED",
  "CONFIG_APP_LED_ENABLED",
  "CONFIG_APP_LED_ACTIVE_LOW",
];
const FW_TEXT_KEYS = [
  "CONFIG_APP_DEVICE_ID",
  "CONFIG_APP_SENSOR_INTERVAL_MS",
  "CONFIG_APP_WIFI_SSID",
  "CONFIG_APP_WIFI_PASSWORD",
  "CONFIG_APP_MQTT_BROKER_URI",
  "CONFIG_APP_IMAGE_UPLOAD_URL",
  "CONFIG_APP_LED_GPIO",
  "CONFIG_APP_CAMERA_UPLOAD_INTERVAL_MS",
];

async function loadFirmwareConfig() {
  try {
    const data = await api("/api/config/firmware");
    const v = data.values || {};
    for (const key of FW_TEXT_KEYS) {
      const el = $("#fw_" + key);
      if (el && v[key] !== undefined) el.value = v[key];
    }
    for (const key of FW_BOOL_KEYS) {
      const el = $("#fw_" + key);
      if (el && v[key] !== undefined) el.checked = !!v[key];
    }
    renderFirmwarePreflight(data.preflight);
    syncFirmwareFields();
  } catch (_) {}
}
loadFirmwareConfig();

function renderFirmwarePreflight(result) {
  const root = $("#firmwarePreflight");
  if (!root || !result) return;
  const summary = `${result.board}；PSRAM=${result.psram}；原生 USB=${result.nativeUsb ? "开启" : "关闭"}`;
  const details = [...(result.errors || []), ...(result.warnings || [])];
  root.className = result.ok ? "notice" : "notice danger";
  root.textContent = details.length ? `${summary}。${details.join("；")}` : `${summary}。预检通过。`;
}

function syncFirmwareFields() {
  setModeFields(
    '[data-for-firmware="wifi"]',
    $("#fw_CONFIG_APP_WIFI_ENABLED").checked,
  );
  setModeFields(
    '[data-for-firmware="mqtt"]',
    $("#fw_CONFIG_APP_MQTT_ENABLED").checked,
  );
  setModeFields(
    '[data-for-firmware="image"]',
    $("#fw_CONFIG_APP_IMAGE_UPLOAD_ENABLED").checked,
  );
  setModeFields(
    '[data-for-firmware="led-gpio"]',
    $("#fw_CONFIG_APP_LED_ENABLED").checked,
  );
}

[
  "#fw_CONFIG_APP_WIFI_ENABLED",
  "#fw_CONFIG_APP_MQTT_ENABLED",
  "#fw_CONFIG_APP_IMAGE_UPLOAD_ENABLED",
  "#fw_CONFIG_APP_LED_ENABLED",
].forEach((selector) =>
  $(selector).addEventListener("change", syncFirmwareFields),
);

$("#btnFwAutofill").addEventListener("click", () => {
  const deviceId = $("#fw_CONFIG_APP_DEVICE_ID").value || "esp32s3-001";
  if (!lanIp) {
    alert("尚未获取到本机 IP，请稍候重试");
    return;
  }
  $("#fw_CONFIG_APP_MQTT_BROKER_URI").value = `mqtt://${lanIp}:1883`;
  $("#fw_CONFIG_APP_IMAGE_UPLOAD_URL").value =
    `http://${lanIp}:8000/api/v1/devices/${deviceId}/images`;
  $("#fw_CONFIG_APP_WIFI_ENABLED").checked = true;
  $("#fw_CONFIG_APP_MQTT_ENABLED").checked = true;
  $("#fw_CONFIG_APP_IMAGE_UPLOAD_ENABLED").checked = true;
  syncFirmwareFields();
});

$("#btnSaveFw").addEventListener("click", async () => {
  const msg = $("#fwMsg");
  msg.className = "msg";
  msg.textContent = "写入中……";
  const invalidControl = [...$$("#tab-fwcfg input:enabled")].find(
    (control) => !control.checkValidity(),
  );
  if (invalidControl) {
    invalidControl.reportValidity();
    msg.className = "msg err";
    msg.textContent = "✘ 请修正标红的固件配置项";
    return;
  }
  const values = {};
  for (const key of FW_TEXT_KEYS) {
    const el = $("#fw_" + key);
    if (!el) continue;
    if (key === "CONFIG_APP_SENSOR_INTERVAL_MS") {
      if (el.value) values[key] = parseInt(el.value, 10);
    } else {
      values[key] = el.value;
    }
  }
  for (const key of FW_BOOL_KEYS) {
    const el = $("#fw_" + key);
    if (el) values[key] = el.checked;
  }
  try {
    const result = await post("/api/config/firmware", { values });
    renderFirmwarePreflight(result.preflight);
    msg.className = "msg ok";
    msg.textContent = "✔ " + (result.message || "已写入");
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = "✘ 写入失败：" + e.message;
  }
});

// ------------------------------------------------------------------ 数据工具
const DATA_COUNT_IDS = {
  telemetry: "#dataCountTelemetry",
  events: "#dataCountEvents",
  ai: "#dataCountAi",
  notifications: "#dataCountNotifications",
};
let latestDataPreview = null;

function localDateTimeValue(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 19);
}

function setDataLast24Hours() {
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  $("#dataStartAt").value = localDateTimeValue(start);
  $("#dataEndAt").value = localDateTimeValue(end);
  latestDataPreview = null;
}

function dataRangePayload() {
  const controls = [$("#dataDeviceId"), $("#dataStartAt"), $("#dataEndAt")];
  const invalid = controls.find((control) => !control.reportValidity());
  if (invalid) throw new Error("请先填写有效的设备和时间范围");
  const start = new Date($("#dataStartAt").value);
  const end = new Date($("#dataEndAt").value);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
    throw new Error("开始时间或结束时间无效");
  }
  if (start >= end) throw new Error("结束时间必须晚于开始时间");
  return {
    deviceId: $("#dataDeviceId").value.trim(),
    startAt: start.toISOString(),
    endAt: end.toISOString(),
  };
}

function renderDataPreview(result) {
  latestDataPreview = result;
  for (const [key, selector] of Object.entries(DATA_COUNT_IDS)) {
    $(selector).textContent = Number(result.counts?.[key] || 0).toLocaleString(
      "zh-CN",
    );
  }
}

async function previewDataRange({ quiet = false } = {}) {
  const result = await post("/api/data/preview", dataRangePayload());
  renderDataPreview(result);
  if (!quiet) {
    const msg = $("#dataMsg");
    msg.className = "msg ok";
    msg.textContent = "✔ 已读取所选时段的数据统计";
  }
  return result;
}

function setDataMessage(message, error = false) {
  const msg = $("#dataMsg");
  msg.className = "msg " + (error ? "err" : "ok");
  msg.textContent = (error ? "✘ " : "✔ ") + message;
}

function showDataConfirmation({ title, text, warning, action, body, danger }) {
  const dialog = $("#dataConfirmDialog");
  $("#dataConfirmTitle").textContent = title;
  $("#dataConfirmText").textContent = text;
  $("#dataConfirmWarning").textContent = warning;
  const confirm = $("#btnDataConfirm");
  confirm.className = danger ? "danger-solid" : "primary";
  dialog.dataset.action = action;
  dialog.dataset.body = JSON.stringify(body);
  dialog.showModal();
}

$("#btnDataLast24h").addEventListener("click", setDataLast24Hours);
$("#btnDataPreview").addEventListener("click", async () => {
  try {
    await previewDataRange();
  } catch (error) {
    setDataMessage(error.message, true);
  }
});

$("#btnDataCleanup").addEventListener("click", async () => {
  try {
    const categories = [...$$('input[name="dataCategory"]:checked')].map(
      (input) => input.value,
    );
    if (!categories.length) throw new Error("请至少选择一种要清理的数据");
    const preview = await previewDataRange({ quiet: true });
    const labels = {
      telemetry: "遥测",
      events: "事件",
      ai: "AI 决策 / 命令",
      notifications: "通知",
    };
    const total = categories.reduce(
      (sum, category) => sum + Number(preview.counts?.[category] || 0),
      0,
    );
    showDataConfirmation({
      title: "确认清理所选数据？",
      text: `设备 ${preview.deviceId}，${categories.map((item) => labels[item]).join("、")}，共命中 ${total.toLocaleString("zh-CN")} 条。`,
      warning:
        "删除后无法从面板撤销；设备、图片、姿态结果和范围外数据不会被删除。",
      action: "cleanup",
      body: { ...dataRangePayload(), categories },
      danger: true,
    });
  } catch (error) {
    setDataMessage(error.message, true);
  }
});

$("#btnDataDemo").addEventListener("click", () => {
  try {
    const body = dataRangePayload();
    const interval = Number($("#dataIntervalSeconds").value);
    if (
      !$("#dataIntervalSeconds").reportValidity() ||
      !Number.isFinite(interval)
    ) {
      throw new Error("请填写 2.5 到 3600 秒之间的采样间隔");
    }
    const sampleCount = Math.ceil(
      (new Date(body.endAt) - new Date(body.startAt)) / 1000 / interval,
    );
    if (sampleCount > 10_000) {
      throw new Error(
        `预计生成 ${sampleCount.toLocaleString("zh-CN")} 条，超过 10,000 条上限`,
      );
    }
    body.intervalSeconds = interval;
    showDataConfirmation({
      title: "确认生成全状态演示数据？",
      text: `设备 ${body.deviceId} 将生成约 ${sampleCount.toLocaleString("zh-CN")} 条遥测和 5 条阶段事件。`,
      warning: "所选时段内已有的遥测和事件会被替换，其他类别数据保持不变。",
      action: "demo",
      body,
      danger: false,
    });
  } catch (error) {
    setDataMessage(error.message, true);
  }
});

const dataConfirmDialog = $("#dataConfirmDialog");
dataConfirmDialog.addEventListener("close", async () => {
  if (dataConfirmDialog.returnValue !== "confirm") return;
  const action = dataConfirmDialog.dataset.action;
  const body = JSON.parse(dataConfirmDialog.dataset.body || "{}");
  const msg = $("#dataMsg");
  msg.className = "msg";
  msg.textContent = action === "cleanup" ? "正在清理……" : "正在生成演示数据……";
  try {
    const result = await post(`/api/data/${action}`, body);
    if (action === "cleanup") {
      const total = Object.entries(result.deleted || {})
        .filter(([key]) => !["commands", "aiResults"].includes(key))
        .reduce((sum, [, count]) => sum + Number(count || 0), 0);
      setDataMessage(
        `已清理 ${total.toLocaleString("zh-CN")} 条数据，请刷新业务控制台`,
      );
    } else {
      setDataMessage(
        `已生成 ${Number(result.generated?.telemetry || 0).toLocaleString("zh-CN")} 条遥测和 ${result.generated?.events || 0} 条事件，请刷新业务控制台`,
      );
    }
    await previewDataRange({ quiet: true });
  } catch (error) {
    setDataMessage(error.message, true);
  }
});

setDataLast24Hours();
$("#dataDeviceId").value = $("#deviceId").value || "esp32s3-001";

// ------------------------------------------------------------------ 串口
async function refreshComPorts() {
  try {
    const data = await api("/api/comports");
    const sel = $("#comPort");
    const current = sel.value;
    sel.innerHTML = '<option value="">自动</option>';
    for (const p of data.ports) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      sel.appendChild(opt);
    }
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
  } catch (_) {}
}
$("#btnRefreshCom").addEventListener("click", refreshComPorts);
refreshComPorts();
