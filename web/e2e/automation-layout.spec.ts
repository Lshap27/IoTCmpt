import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();
const longSummary = `## 策略复盘\n\n${"这是一段用于验证卡片不会被长模型输出撑高的说明。".repeat(40)}`;

function planRule(index: number) {
  return {
    id: `demo-rule-${index}`,
    description: `演示规则 ${index} ${"较长说明".repeat(5)}`,
    trigger: index === 1 ? { type: "delay", after_seconds: 30 } : { type: "interval", every_seconds: 15 },
    action: {
      command: "voice.speak",
      parameter: {},
      text: `第 ${index} 条提醒`,
    },
    cooldown_seconds: 0,
  };
}

async function mockAutomation(page: Page) {
  await page.route(/\/api\/v1\/devices\/[^/]+\/automation-plans(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          plan_id: "plan-layout",
          device_id: "esp32s3-001",
          plan_type: "user",
          title: "长内容演示计划",
          status: "active",
          current_version: 1,
          source_prompt: "每 15 秒提醒一次",
          activation_blockers: [],
          spec: {
            schema_version: "1.0",
            title: "长内容演示计划",
            duration_seconds: 600,
            timezone: "Asia/Shanghai",
            manual_override_policy: "respect",
            end_behavior: "keep_state",
            clarifications: [],
            rules: Array.from({ length: 16 }, (_, index) => planRule(index + 1)),
          },
          explanation: longSummary,
          validation: { valid: true },
          rule_states: Array.from({ length: 16 }, (_, index) => ({
            rule_id: `demo-rule-${index + 1}`,
            last_condition: "unknown",
            last_fired_at: null,
            next_fire_at: now,
            last_command_id: null,
            blocked_reason: null,
          })),
          control_claims: [],
          started_at: now,
          paused_at: null,
          ends_at: new Date(Date.now() + 600_000).toISOString(),
          completed_at: null,
          created_at: now,
          updated_at: now,
        },
      ]),
    });
  });
  await page.route(
    /\/api\/v1\/devices\/[^/]+\/automation-plans\/plan-layout\/events(?:\?.*)?$/,
    async (route) => {
      await route.fulfill({ contentType: "application/json", body: "[]" });
    },
  );
  await page.route(/\/api\/v1\/devices\/[^/]+\/ai\/strategies(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        Array.from({ length: 5 }, (_, index) => ({
          strategy_id: `strategy-${index + 1}`,
          device_id: "esp32s3-001",
          run_id: `run-strategy-${index + 1}`,
          plan_id: "plan-layout",
          base_version: 1,
          proposed_spec: {},
          diff: Array.from({ length: 12 }, (_, diffIndex) => ({
            path: `/rules/${diffIndex}/description/${"long".repeat(20)}`,
            before: "旧值",
            after: "新值",
          })),
          summary: longSummary,
          status: "proposed",
          resolved_at: null,
          created_at: now,
          updated_at: now,
        })),
      ),
    });
  });
  await page.route(/\/api\/v1\/devices\/[^/]+\/ai\/runs(?:\?.*)?$/, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ contentType: "application/json", body: "[]" });
      return;
    }
    await route.continue();
  });
}

test("automation and strategy cards keep long content inside fixed desktop panels", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockAutomation(page);
  await page.goto("/");

  const planCard = page
    .getByRole("heading", { name: "AI 自动化计划" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  const strategyCard = page
    .getByRole("heading", { name: "AI 策略" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  await expect(planCard.getByText("激活后 30 秒提醒一次")).toBeVisible();
  await expect(planCard.getByText("每 15 秒触发").first()).toBeVisible();

  const planBox = await planCard.boundingBox();
  const strategyBox = await strategyCard.boundingBox();
  expect(planBox?.height).toBeLessThanOrEqual(546);
  expect(strategyBox?.height).toBeLessThanOrEqual(546);

  const fullRules = planCard.getByRole("button", { name: "查看全部 16 条规则" });
  await fullRules.click();
  await expect(page.getByRole("dialog", { name: "长内容演示计划 · 完整规则" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(fullRules).toBeFocused();

  const strategyScroll = strategyCard.locator(".overflow-y-auto").first();
  const scrollState = await strategyScroll.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight);
});

test("automation cards do not introduce mobile horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAutomation(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AI 自动化计划" })).toBeVisible();
  const widths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client + 1);
});
