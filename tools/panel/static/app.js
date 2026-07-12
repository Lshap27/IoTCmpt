// IoTCmpt 配置面板前端逻辑（无构建步骤，vanilla JS）
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
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
  } catch (_) { /* 面板自身请求失败时静默 */ }
}
refreshStatus();
setInterval(refreshStatus, 4000);

// ------------------------------------------------------------------ 环境配置
async function loadEnvConfig() {
  try {
    const data = await api("/api/config/env");
    const server = data.server.values || {};
    if (server.AIOT_LLM_ENDPOINT) $("#llmEndpoint").value = server.AIOT_LLM_ENDPOINT;
    if (server.AIOT_LLM_MODEL) $("#llmModel").value = server.AIOT_LLM_MODEL;
    if (server.AIOT_AUTOPILOT_MIN_CONFIDENCE)
      $("#autopilotMinConfidence").value = server.AIOT_AUTOPILOT_MIN_CONFIDENCE;
    if (server.AIOT_AUTOPILOT_TRIGGER_LEVELS)
      $("#autopilotTriggerLevels").value = server.AIOT_AUTOPILOT_TRIGGER_LEVELS;
    $("#llmVisionEnabled").checked = server.AIOT_LLM_VISION_ENABLED !== "false";
    $("#autopilotEnabled").checked = server.AIOT_AUTOPILOT_ENABLED !== "false";
  } catch (_) {}
}
loadEnvConfig();

$("#btnDetectIp").addEventListener("click", () => {
  $("#lanAddress").value = lanIp;
});

$("#btnSaveEnv").addEventListener("click", async () => {
  const msg = $("#envMsg");
  msg.className = "msg";
  msg.textContent = "保存中……";
  const body = {
    preset: document.querySelector("input[name=preset]:checked").value,
    deviceId: $("#deviceId").value || null,
    lanAddress: $("#lanAddress").value || null,
    llmEndpoint: $("#llmEndpoint").value || null,
    llmModel: $("#llmModel").value || null,
    llmApiKey: $("#llmApiKey").value || null,
    llmVisionEnabled: $("#llmVisionEnabled").checked,
    autopilotEnabled: $("#autopilotEnabled").checked,
    autopilotMinConfidence: $("#autopilotMinConfidence").value || null,
    autopilotTriggerLevels: $("#autopilotTriggerLevels").value || null,
  };
  try {
    await post("/api/config/env", body);
    msg.className = "msg ok";
    msg.textContent = "✔ 环境配置已保存（.env / server/.env / web/.env.local）";
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = "✘ 保存失败：" + e.message;
  }
});

// ------------------------------------------------------------------ 日志流
const logStreams = {};
function streamLogs(jobName, targetEl) {
  if (logStreams[jobName]) logStreams[jobName].close();
  const es = new EventSource(`/api/actions/${jobName}/logs`);
  logStreams[jobName] = es;
  targetEl.classList.add("running"); // 终端闪烁光标（见 style.css .log.running）
  const settle = () => {
    es.close();
    targetEl.classList.remove("running");
  };
  es.onmessage = (ev) => {
    targetEl.textContent += ev.data + "\n";
    targetEl.scrollTop = targetEl.scrollHeight;
  };
  es.addEventListener("end", settle);
  es.onerror = settle;
}

const JOB_OF_ACTION = {
  "docker-up": "docker-up", "docker-down": "docker-down", "docker-logs": "docker-logs",
  "backend-start": "backend", "frontend-start": "frontend",
  "idf-install": "idf", "idf-build": "idf", "idf-flash": "idf",
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
  "CONFIG_APP_SENSOR_MOCK_ENABLED", "CONFIG_APP_WIFI_ENABLED",
  "CONFIG_APP_MQTT_ENABLED", "CONFIG_APP_IMAGE_UPLOAD_ENABLED",
  "CONFIG_APP_CAMERA_ENABLED", "CONFIG_APP_DISPLAY_ENABLED",
  "CONFIG_APP_ACTUATOR_ENABLED", "CONFIG_APP_BUTTON_ENABLED",
  "CONFIG_APP_MQ2_ENABLED", "CONFIG_APP_VOICE_ENABLED",
];
const FW_TEXT_KEYS = [
  "CONFIG_APP_DEVICE_ID", "CONFIG_APP_SENSOR_INTERVAL_MS",
  "CONFIG_APP_WIFI_SSID", "CONFIG_APP_WIFI_PASSWORD",
  "CONFIG_APP_MQTT_BROKER_URI", "CONFIG_APP_IMAGE_UPLOAD_URL",
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
  } catch (_) {}
}
loadFirmwareConfig();

$("#btnFwAutofill").addEventListener("click", () => {
  const deviceId = $("#fw_CONFIG_APP_DEVICE_ID").value || "esp32s3-001";
  if (!lanIp) { alert("尚未获取到本机 IP，请稍候重试"); return; }
  $("#fw_CONFIG_APP_MQTT_BROKER_URI").value = `mqtt://${lanIp}:1883`;
  $("#fw_CONFIG_APP_IMAGE_UPLOAD_URL").value =
    `http://${lanIp}:8000/api/devices/${deviceId}/images`;
  $("#fw_CONFIG_APP_WIFI_ENABLED").checked = true;
  $("#fw_CONFIG_APP_MQTT_ENABLED").checked = true;
  $("#fw_CONFIG_APP_IMAGE_UPLOAD_ENABLED").checked = true;
});

$("#btnSaveFw").addEventListener("click", async () => {
  const msg = $("#fwMsg");
  msg.className = "msg";
  msg.textContent = "写入中……";
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
