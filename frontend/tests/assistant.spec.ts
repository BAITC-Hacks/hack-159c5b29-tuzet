import { expect, test } from "@playwright/test";

test("ассистент передаёт выбранный gid и открывает подтверждающую карточку", async ({ page }) => {
  const summary = await (await page.request.get("/api/summary")).json();
  const top = await (await page.request.get("/api/top?limit=1")).json();
  const gid: string = top.items[0].gid;
  let received: Record<string, unknown> | undefined;

  await page.route("**/api/assistant/status", route => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ run_id: summary.run_id, available: true, message: "Настроен" }),
  }));
  await page.route("**/api/assistant/query", route => {
    received = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      run_id: summary.run_id, status: "ok", answer: `GID ${gid}: признаки роли consolidator.`,
      total: 1, shown: 1, truncated: false, search_truncated: false,
      facts: [{ fact_id: `node:${gid}`, gid, role: "consolidator", limitations: ["Граф ограничен исходящими переводами от seed."] }],
    }) });
  });

  await page.goto(`/?view=assistant&gid=${gid}`);
  await page.getByLabel("Вопрос ассистенту").fill("Почему этот клиент получил такую роль?");
  await page.getByRole("button", { name: "Спросить" }).click();
  await expect(page.getByText(`GID ${gid}: признаки роли consolidator.`)).toBeVisible();
  expect(received).toEqual({
    question: "Почему этот клиент получил такую роль?", selected_gid: gid,
    expected_run_id: summary.run_id,
  });
  await expect(page.getByText("Граф ограничен исходящими переводами от seed.")).toBeVisible();
  await page.getByRole("button", { name: `Открыть клиента ${gid}` }).click();
  await expect(page.getByText("Карточка клиента", { exact: true })).toBeVisible();
});
