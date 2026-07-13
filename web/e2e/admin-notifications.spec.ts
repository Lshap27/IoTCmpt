import { expect, test } from "@playwright/test";

test("admin page preserves the prototype showcase and separates live data", async ({ page }) => {
  await page.goto("/admin");
  await expect(page.getByRole("button", { name: "宿舍管理" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("180", { exact: true })).toBeVisible();
  await expect(page.getByText(/89[12]/, { exact: true })).toBeVisible();
  await expect(page.getByText(/当前存在 [34] 条高危告警需立即处理/)).toBeVisible();
  await expect(page.getByText("映雪3-301 物联网设备状态")).toBeVisible();
  await expect(page.getByText("esp32s3-001")).toBeVisible();
  await expect(page.getByText("实时", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("演示数据", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/MQ-2 仅显示检测到烟雾\/正常，不虚构 ppm/)).toBeVisible();

  await page.getByRole("button", { name: "文明宿舍评分" }).click();
  await expect(page.getByText("文明宿舍红黑榜（月度）")).toBeVisible();
  await expect(page.getByText("评分维度分布")).toBeVisible();

  await page.getByRole("button", { name: /安全告警中心/ }).click();
  await expect(page.getByText("告警台账列表")).toBeVisible();
  await expect(page.getByText("告警降噪设置")).toBeVisible();
  await expect(page.getByLabel("告警等级")).toBeVisible();

  await page.getByRole("button", { name: "消息通知", exact: true }).click();
  await expect(page.getByLabel("目标宿舍").locator("option")).toHaveCount(6);
  await expect(page.getByText("恶劣天气提醒")).toBeVisible();
  await expect(page.getByText("整栋(180间)")).toBeVisible();

  await page.getByRole("button", { name: "系统设置" }).click();
  await expect(page.getByRole("button", { name: "权限管理" })).toBeVisible();
  await expect(page.getByRole("button", { name: "设备运维工单" })).toBeVisible();
  await expect(page.getByRole("button", { name: "隐私设置" })).toBeVisible();
});

test("notification reaches the resident page live and survives refresh", async ({ browser }) => {
  const context = await browser.newContext();
  const resident = await context.newPage();
  const admin = await context.newPage();
  const content = `端到端通知 ${Date.now()}`;

  await resident.goto("/");
  await admin.goto("/admin");
  await admin.getByRole("button", { name: "消息通知", exact: true }).click();
  await admin.getByLabel("通知内容").fill(content);
  await admin.getByLabel("语音播报").uncheck();
  await admin.getByRole("button", { name: "立即下发" }).click();

  await expect(admin.getByText(/通知已下发到映雪3-301：文字已下发/)).toBeVisible();
  await expect(resident.getByRole("heading", { name: "宿舍通知" })).toBeVisible();
  await expect(resident.getByText(content, { exact: true })).toBeVisible();

  await resident.reload();
  await expect(resident.getByText(content, { exact: true })).toBeVisible();
  await context.close();
});

test("voice notification reports the simulator acknowledgement", async ({ page }) => {
  test.skip(!process.env.E2E_SCENARIO, "run with the MQTT device simulator");
  const content = `语音闭环验证 ${Date.now()}`;

  await page.goto("/admin");
  await page.getByRole("button", { name: "消息通知", exact: true }).click();
  await page.getByLabel("通知内容").fill(content);
  await page.getByLabel("语音播报").check();
  await page.getByRole("button", { name: "立即下发" }).click();

  const row = page.getByRole("row").filter({ hasText: content });
  await expect(row).toContainText("文字及语音均已送达", { timeout: 15_000 });
});
