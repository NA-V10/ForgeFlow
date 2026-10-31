import { expect, test } from "@playwright/test";
import { API, seedRepo, seedWork, uid } from "./seed";

test("command center shows live state and real-time activity", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Command center" })).toBeVisible();
  for (const tile of ["active-agents", "running-tasks", "pending-approvals", "merge-queue"]) {
    await expect(page.getByTestId(`stat-${tile}`)).toBeVisible();
  }
  await expect(page.getByTestId("live-status").first()).toHaveAttribute("data-status", "live");

  // an event produced elsewhere shows up without reloading
  const repo = await seedRepo(request);
  await seedWork(request, repo.id, { title: `Live update ${uid()}`, path: "app/util.py", content: "def add(a, b):\n    return b + a\n" });
  const feed = page.getByTestId("activity-feed");
  await expect(feed.locator('[data-event-type="checkpoint.created"]').first()).toBeVisible();
  await expect(feed.locator('[data-event-type="agent.finished"]').first()).toBeVisible();
});

test("task creation", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const title = `Implement OAuth ${uid()}`;
  await page.goto("/tasks");
  await page.getByTestId("new-task").click();
  const dialog = page.getByRole("dialog", { name: "New task" });
  await dialog.getByLabel("Repository").selectOption(repo.id);
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByLabel("Description").fill("Add OAuth login");
  await dialog.getByLabel("Priority").selectOption("HIGH");
  await dialog.getByRole("button", { name: "Create task" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("PENDING").first()).toBeVisible();
  await page.goto("/tasks");
  await expect(page.getByTestId("tasks-table").getByText(title)).toBeVisible();
});

test("repository graph opens node details", async ({ page, request }) => {
  const repo = await seedRepo(request);
  const { workspace } = await seedWork(request, repo.id, { title: "Graph work", path: "app/util.py", content: "def add(a, b):\n    return a + b + 0\n" });
  const merge = await request.post(`${API}/merges`, { data: { workspace_id: workspace.id, execute: true } });
  expect((await merge.json()).status).toBe("MERGED");
  await page.goto(`/repositories/${repo.id}`);
  const graph = page.getByTestId("repo-graph");
  const taskNode = graph.locator('[data-testid^="rf__node-task:"]').filter({ hasText: "Graph work" });
  await expect(taskNode).toBeVisible();
  await taskNode.click();
  await expect(page.getByTestId("node-details")).toContainText("task");
  await page.getByRole("tab", { name: "Files & provenance" }).click();
  await page.getByRole("button", { name: "app/util.py" }).click();
  await page.getByText("return a + b + 0").click();
  await expect(page.getByTestId("provenance-chain")).toContainText("Graph work");
});
