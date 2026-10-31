import { expect, test } from "@playwright/test";
import { seedRepo, seedWork, uid } from "./seed";

test("diff viewer: unified, split and semantic tabs", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const { workspace } = await seedWork(request, repo.id, {
    title: `Diff ${uid()}`, path: "app/util.py",
    content: "def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n",
  });
  await page.goto(`/workspaces/${workspace.id}`);
  const file = page.locator('[data-diff-file="app/util.py"]');
  await expect(file).toContainText("def multiply(a, b):");
  await page.getByRole("tab", { name: "Split" }).click();
  await expect(page.getByText("return a * b")).toBeVisible();
  await page.getByRole("tab", { name: "Semantic" }).click();
  const functions = page.locator('[data-semantic-group="functions"]');
  await expect(functions).toContainText("multiply");
  await expect(functions).toContainText("added");
});

test("approval flow: policy requires approval, a human approves", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const title = `Auth change ${uid()}`;
  await seedWork(request, repo.id, {
    title, path: "app/auth.py", submit: true,
    content: "import hmac\n\n\ndef login(user, password):\n    return hmac.compare_digest(user, 'admin')\n",
  });
  await page.goto("/approvals");
  await page.getByTestId("approvals-table").getByRole("link", { name: title }).click();
  await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]{36}$/);
  await expect(page.getByText("policy 'security-code' requires review of app/auth.py")).toBeVisible();
  const decision = page.getByTestId("approval-decision");
  await expect(decision).toBeVisible();
  await page.getByPlaceholder("Comment (optional)").fill("reviewed in e2e");
  await page.getByTestId("approve").click();
  await expect(decision).toContainText("approved by");
  await expect(page.locator('[data-status="APPROVED"]').first()).toBeVisible();
});

test("merge flow: queue, gate, merge", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const title = `Refactor util ${uid()}`;
  const { workspace } = await seedWork(request, repo.id, { title, path: "app/util.py", content: "def add(a, b):\n    return sum((a, b))\n" });
  await page.goto(`/workspaces/${workspace.id}`);
  await page.getByTestId("evaluate-merge").click();
  await expect(page.locator('[data-check="tests"][data-check-status="pass"]')).toBeVisible({ timeout: 60_000 });
  await page.goto("/merge-queue");
  const card = page.getByTestId("merge-card").filter({ hasText: title });
  await expect(card).toHaveAttribute("data-merge-status", "READY");
  await card.getByTestId("merge-button").click();
  await expect(page.getByTestId("merge-card").filter({ hasText: title })).toHaveAttribute("data-merge-status", "MERGED", { timeout: 60_000 });
});
