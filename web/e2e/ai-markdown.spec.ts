import { expect, test, type Page } from "@playwright/test";

const longMarkdown = `## 环境判断

- 当前空气质量需要关注
- 建议保持观察，不覆盖手动操作

| 指标 | 状态 |
| --- | --- |
| TVOC | 偏高 |

\`\`\`text
这是一个很长的诊断代码块：${"x".repeat(500)}
\`\`\`

<script>window.__unsafe_ai_html__ = true</script>

${"补充分析内容。".repeat(80)}`;

async function injectDecision(page: Page) {
  await page.route(/\/api\/v1\/devices\/[^/]+\/ai\/runs(?:\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          run_id: "run-markdown-layout",
          trace_id: "trace-markdown-layout",
          device_id: "esp32s3-001",
          kind: "decision",
          trigger: "manual",
          status: "succeeded",
          model: "layout-test",
          input: {},
          output: { summary: longMarkdown, risk_level: "low" },
          error_code: null,
          error_message: null,
          created_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
        },
      ]),
    });
  });
}

test("long AI Markdown stays compact and opens an accessible safe dialog", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await injectDecision(page);
  await page.goto("/");

  const aiCard = page
    .getByRole("heading", { name: "AI 决策" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  const telemetryCard = page
    .getByRole("heading", { name: "实时遥测" })
    .locator("xpath=ancestor::*[contains(@class, 'glass-panel')]");
  await expect(aiCard.getByRole("heading", { name: "环境判断" })).toBeVisible();
  await expect(aiCard.getByText("## 环境判断")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => (window as typeof window & { __unsafe_ai_html__?: boolean }).__unsafe_ai_html__,
    ),
  ).toBeUndefined();

  const aiBox = await aiCard.boundingBox();
  const telemetryBox = await telemetryCard.boundingBox();
  expect(Math.abs((aiBox?.height ?? 0) - (telemetryBox?.height ?? 0))).toBeLessThan(3);

  const trigger = aiCard.getByRole("button", { name: "查看完整分析" });
  await trigger.focus();
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "完整 AI 决策分析" });
  await expect(dialog).toBeVisible();
  const overflow = await dialog
    .locator("table")
    .locator("xpath=parent::*")
    .evaluate((node) => getComputedStyle(node).overflowX);
  expect(overflow).toBe("auto");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("AI Markdown preview does not create mobile horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await injectDecision(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "环境判断" })).toBeVisible();
  const widths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client + 1);
});
