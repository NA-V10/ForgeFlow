import { expect, test } from "@playwright/test";
import { seedRepo, seedWork, uid } from "./seed";

test("command palette finds an agent thread and navigates to it", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const title = `Palette target ${uid()}`;
  const { workspace } = await seedWork(request, repo.id, { title, path: "app/util.py", content: "def add(a, b):\n    return a + b  # p\n" });
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const palette = page.getByTestId("command-palette");
  await expect(palette).toBeVisible();
  await page.keyboard.type(title);
  await expect(palette.locator('[data-selected="true"]')).toContainText(title);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/workspaces/${workspace.id}`));
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
});

test("keyboard navigation: G-shortcuts, help sheet, create task", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("live-status").first()).toHaveAttribute("data-status", "live");
  await page.keyboard.press("g");
  await page.keyboard.press("t");
  await expect(page).toHaveURL(/\/tasks$/);
  await page.keyboard.press("g");
  await page.keyboard.press("i");
  await expect(page).toHaveURL(/\/inbox$/);
  await page.keyboard.press("Shift+?");
  await expect(page.getByTestId("shortcuts-help")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.keyboard.press("c");
  await expect(page.getByRole("dialog", { name: "New task" })).toBeVisible();
});

test("inbox: ranked item approved from the keyboard", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const title = `Inbox auth ${uid()}`;
  await seedWork(request, repo.id, {
    title, path: "app/auth.py", submit: true,
    content: "import hmac\n\n\ndef login(user, password):\n    return hmac.compare_digest(user, 'admin')\n",
  });
  await page.goto("/inbox");
  const row = page.getByTestId("inbox-row").filter({ hasText: title });
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-priority", /P[0-2]/);
  await row.click();
  await expect(page.getByTestId("inbox-preview")).toContainText(title);
  await expect(page.getByTestId("inbox-preview")).toContainText("security-code");
  await page.keyboard.press("Shift+A");
  await expect(page.getByTestId("inbox-row").filter({ hasText: title })).toHaveCount(0);
});

test("command center shows agent threads with gate progress", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const title = `Thread card ${uid()}`;
  const { workspace } = await seedWork(request, repo.id, { title, path: "app/util.py", content: "def add(a, b):\n    return a + b  # c\n" });
  await request.post(`http://localhost:${process.env.FORGEFLOW_API_PORT ?? 8000}/api/v1/merges`, { data: { workspace_id: workspace.id } });
  await page.goto("/");
  const card = page.getByTestId("thread-card").filter({ hasText: title });
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-thread-state", "ready");
  await expect(card).toContainText("Gate 7/7");
  await card.click();
  await expect(page).toHaveURL(new RegExp(`/workspaces/${workspace.id}`));
  await expect(page.locator('[data-lifecycle="REVIEW"]').first()).toBeVisible();
});
