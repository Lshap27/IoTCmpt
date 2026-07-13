import { expect, test } from "@playwright/test";

test("dashboard exposes the real hardware-loop surfaces", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MQ-2 烟雾安全")).toBeVisible();
  await expect(page.getByText("环境光照", { exact: true })).toBeVisible();
  await expect(page.getByLabel("LM393 最近明暗历史")).toBeVisible();
  await expect(page.getByText("宿舍环境健康报告")).toBeVisible();
  await expect(page.getByRole("heading", { name: "现场画面与姿态" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "设备指令" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "环境与设备" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "控制与自动化" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI 与视觉" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "安全与系统" })).toBeVisible();
});

test("priority and runtime settings use their domain panels", async ({ page }) => {
  await page.goto("/");
  if (process.env.E2E_DEVICE_ID) {
    await page.getByLabel("选择设备").selectOption(process.env.E2E_DEVICE_ID);
  }
  const priority = page.getByRole("radiogroup", { name: "控制优先级" });
  await expect(priority.getByRole("radio")).toHaveCount(2);
  await expect(priority.getByRole("radio", { checked: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "恢复自动控制" })).toHaveCount(0);

  const cameraPanel = page
    .getByRole("heading", { name: "现场画面与姿态" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  await expect(cameraPanel.getByText("定时视觉分析", { exact: true })).toBeVisible();
  await expect(cameraPanel.getByText("久坐提醒时间", { exact: true })).toBeVisible();
  const safetyPanel = page
    .getByRole("heading", { name: "MQ-2 烟雾安全" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  await expect(safetyPanel.getByText("静音时长", { exact: true })).toBeVisible();
  const aiPanel = page
    .getByRole("heading", { name: "AI 决策" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  await expect(aiPanel.getByText("久坐提醒时间", { exact: true })).toHaveCount(0);
  await expect(aiPanel.getByText("定时视觉分析", { exact: true })).toHaveCount(0);
  await expect(aiPanel.getByText("静音时长", { exact: true })).toHaveCount(0);
});

test("event groups scroll without expanding the event card", async ({ page }) => {
  await page.goto("/");
  const heading = page.getByRole("heading", { name: "实时事件流" });
  const card = heading.locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  const list = page.getByLabel("环境与设备事件列表");
  const before = await card.boundingBox();
  expect(before).not.toBeNull();

  await list.evaluate((element) => {
    for (let index = 0; index < 30; index += 1) {
      const item = document.createElement("div");
      item.textContent = `布局压力测试事件 ${index + 1}`;
      item.style.height = "28px";
      element.appendChild(item);
    }
  });

  const after = await card.boundingBox();
  const scrollState = await list.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    overflowY: getComputedStyle(element).overflowY,
  }));
  expect(Math.abs((after?.height ?? 0) - (before?.height ?? 0))).toBeLessThan(2);
  expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight);
  expect(scrollState.overflowY).toBe("auto");
});

test("LED command remains pending until command_ack", async ({ page }) => {
  await page.goto("/");
  if (process.env.E2E_DEVICE_ID) {
    await page.getByLabel("选择设备").selectOption(process.env.E2E_DEVICE_ID);
  }
  const smokeDialog = page.getByRole("alertdialog", { name: "检测到烟雾" });
  if (process.env.E2E_SCENARIO === "smoke") {
    await expect(smokeDialog).toBeVisible();
    await smokeDialog.getByRole("button", { name: "暂时忽略" }).click();
  }
  const ledOn = page.getByRole("button", { name: "LED 开" });
  await expect(ledOn).toBeVisible();
  await ledOn.click();
  await expect(page.getByText("等待确认…").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "LED 开" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("已执行：开启 LED", { exact: true })).toBeVisible({ timeout: 15_000 });
});

test("smoke scenario shows an actionable persisted alert", async ({ page }) => {
  test.skip(process.env.E2E_SCENARIO !== "smoke", "run with the smoke simulator scenario");
  await page.goto("/");
  const dialog = page.getByRole("alertdialog", { name: "检测到烟雾" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/本地蜂鸣器和语音报警/)).toBeVisible();
  await dialog.getByRole("button", { name: "暂时忽略" }).click();
  await expect(dialog).toBeHidden();

  const acknowledgeButtons = page.getByRole("button", { name: "确认", exact: true });
  const before = await acknowledgeButtons.count();
  expect(before).toBeGreaterThan(0);
  await acknowledgeButtons.first().click();
  await expect(acknowledgeButtons).toHaveCount(before - 1);
});
