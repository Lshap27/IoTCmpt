// IoTCmpt 配置面板前端逻辑（无构建步骤，vanilla JS）
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

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
    headers: { "Content-Type": "application/json" },
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
  endpoint: "https://api.openai.com/v1/chat/completions",
  model: "gpt-4o-mini",
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
    '[data-for-autopilot="enabled"]',
    $("#autopilotEnabled").checked,
  );
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
    if (server.AIOT_AUTOPILOT_MIN_CONFIDENCE)
      $("#autopilotMinConfidence").value = server.AIOT_AUTOPILOT_MIN_CONFIDENCE;
    if (server.AIOT_AUTOPILOT_TRIGGER_LEVELS)
      $$('input[name="triggerLevel"]').forEach((input) => {
        input.checked = server.AIOT_AUTOPILOT_TRIGGER_LEVELS.split(",")
          .map((item) => item.trim())
          .includes(input.value);
      });
    if (compose.AIOT_DEMO_DEVICE_ID)
      $("#deviceId").value = compose.AIOT_DEMO_DEVICE_ID;
    if (compose.AIOT_DEMO_SCENARIO)
      $("#simulatorScenario").value = compose.AIOT_DEMO_SCENARIO;
    $("#llmVisionEnabled").checked = server.AIOT_LLM_VISION_ENABLED !== "false";
    $("#autopilotEnabled").checked = server.AIOT_AUTOPILOT_ENABLED !== "false";
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
$("#autopilotEnabled").addEventListener("change", syncModeFields);

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
  const confidence = $("#autopilotMinConfidence");
  if (!deviceId.reportValidity() || !confidence.reportValidity()) {
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
  const triggerLevels = [...$$('input[name="triggerLevel"]:checked')].map(
    (input) => input.value,
  );
  if (!triggerLevels.length) {
    msg.className = "msg err";
    msg.textContent = "✘ 自动处置触发级别至少选择一项";
    $("#autopilotTriggerLevels").focus();
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
    llmVisionEnabled: $("#llmVisionEnabled").checked,
    autopilotEnabled: $("#autopilotEnabled").checked,
    autopilotMinConfidence: confidence.value || null,
    autopilotTriggerLevels: triggerLevels,
  };
  try {
    const result = await post("/api/config/env", body);
    msg.className = "msg ok";
    msg.textContent = result.stackReconfigured
      ? "✔ 配置已保存，并已重新应用到运行中的服务；虚拟设备正在连接"
      : "✔ 配置已保存；启动 Docker 演示栈后自动生效";
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
    if (action === "simulator-start") {
      body.scenario = $("#simulatorScenario").value;
      body.deviceId = $("#deviceId").value || "esp32s3-001";
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
];
const FW_TEXT_KEYS = [
  "CONFIG_APP_DEVICE_ID",
  "CONFIG_APP_SENSOR_INTERVAL_MS",
  "CONFIG_APP_WIFI_SSID",
  "CONFIG_APP_WIFI_PASSWORD",
  "CONFIG_APP_MQTT_BROKER_URI",
  "CONFIG_APP_IMAGE_UPLOAD_URL",
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
    syncFirmwareFields();
  } catch (_) {}
}
loadFirmwareConfig();

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
}

[
  "#fw_CONFIG_APP_WIFI_ENABLED",
  "#fw_CONFIG_APP_MQTT_ENABLED",
  "#fw_CONFIG_APP_IMAGE_UPLOAD_ENABLED",
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
    `http://${lanIp}:8000/api/devices/${deviceId}/images`;
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
    msg.className = "msg ok";
    msg.textContent = "✔ " + (result.message || "已写入");
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = "✘ 写入失败：" + e.message;
  }
});

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
