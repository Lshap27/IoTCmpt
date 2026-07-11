import { expect, test } from "@playwright/test";

test("dashboard exposes the real hardware-loop surfaces", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MQ-2 烟雾安全")).toBeVisible();
  await expect(page.getByText("LM393 环境光照")).toBeVisible();
  await expect(page.getByText("数字量明暗判断，不伪造 lux 数值")).toBeVisible();
  await expect(page.getByText("宿舍环境健康报告")).toBeVisible();
  await expect(page.getByText("温度范围")).toBeVisible();
  await expect(page.getByText("夜间 eCO₂ 超标")).toBeVisible();
  await expect(
    page.getByText("本报告只统计数据库中该时段的真实采样；数据不足时不会补造缺失时段。"),
  ).toBeVisible();
  await expect(
    page.getByText("室外温湿度与除湿器：未接入硬件，本页面不会用固定值或随机数据代替。"),
  ).toBeVisible();
});

test("LED command remains pending until command_ack", async ({ page }) => {
  await page.goto("/");
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
