import { expect, test } from "@playwright/test";

test("стартовый обзор ведёт к карточке, графу, мотиву и выгрузкам", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Обзор" })).toBeVisible();
  const top = await (await page.request.get("/api/top?limit=1")).json();
  const gid: string = top.items[0].gid;
  await page.getByLabel("Поиск по gid").fill(gid);
  await page.getByLabel("Поиск по gid").press("Enter");
  await expect(page.getByRole("heading", { name: "Полная карточка клиента" })).toBeVisible();
  await expect(page.locator(".mg-client-id")).toContainText(gid);
  await expect(page.getByText("Почему такой приоритет")).toBeVisible();
  await expect(page.getByText("Почему назначена роль")).toBeVisible();
  await page.getByRole("button", { name: "В графе" }).click();
  await expect(page.getByLabel("Направленный граф переводов")).toBeVisible();
  await page.getByLabel("Число переходов").selectOption("2");
  await page.getByLabel("Цвет графа").selectOption("cluster");
  await page.getByRole("button", { name: "Полная карточка" }).click();
  await page.getByRole("button", { name: "Все мотивы клиента" }).click();
  await expect(page.getByRole("heading", { name: "Каталог мотивов" })).toBeVisible();
  await page.getByRole("button", { name: "Детали" }).first().click();
  await expect(page.getByText("Подтверждающие рёбра")).toBeVisible();
  await page.getByRole("button", { name: "Сообщества" }).click();
  await expect(page.getByRole("heading", { name: "Сообщества", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Устойчивость" }).click();
  await expect(page.getByRole("heading", { name: "Структурная устойчивость" })).toBeVisible();
  await page.getByRole("button", { name: "Чувствительность" }).click();
  await expect(page.getByRole("heading", { name: "Чувствительность рейтинга" })).toBeVisible();
  await page.getByRole("button", { name: "AI-ассистент" }).click();
  await expect(page.getByText("AI отключён", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "О расчёте и выгрузки" }).click();
  await expect(page.getByRole("heading", { name: "О расчёте и выгрузки" })).toBeVisible();
  for (const name of ["nodes_roles", "clusters", "top_nodes"]) expect((await page.request.get(`/api/exports/${name}`)).status()).toBe(200);
  expect(errors).toEqual([]);
});

test("мобильный обзор, граф и карточка не переполняют экран", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Обзор" })).toBeVisible();
  await page.getByRole("navigation", { name: "Мобильная навигация" }).getByRole("button", { name: "Граф" }).click();
  await expect(page.getByLabel("Направленный граф переводов")).toBeVisible();
  await page.getByRole("button", { name: "Карточка", exact: true }).click();
  await expect(page.getByRole("button", { name: "Полная карточка" })).toBeVisible();
  await page.getByRole("button", { name: "Список", exact: true }).click();
  await expect(page.getByText("Поиск и фильтры")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});

test("выбранная вершина и масштаб сохраняются при смене цвета и раздела", async ({ page }) => {
  const top = await (await page.request.get("/api/top?limit=1")).json();
  const gid: string = top.items[0].gid;
  await page.goto(`/?view=graph&gid=${gid}`);
  await expect(page.getByLabel("Направленный граф переводов")).toBeVisible();
  const selected = () => page.evaluate(() => {
    const container = document.querySelector(".network") as unknown as { _cyreg?: { cy: import("cytoscape").Core } } | null;
    if (!container?._cyreg) return { ids: [], zoom: 0 };
    const cy = container._cyreg.cy;
    return { ids: cy.nodes(":selected").map(node => node.id()), zoom: cy.zoom() };
  });
  await expect.poll(async () => (await selected()).ids).toEqual([gid]);
  await page.evaluate(() => { const cy = (document.querySelector(".network") as unknown as { _cyreg: { cy: import("cytoscape").Core } })._cyreg.cy; cy.zoom(1.2); });
  const before = await selected();
  await page.getByLabel("Цвет графа").selectOption("cluster");
  expect(await selected()).toEqual(before);
  await page.getByRole("button", { name: "Сообщества" }).click();
  await page.getByRole("navigation", { name: "Разделы" }).getByRole("button", { name: /Граф/ }).click();
  await expect.poll(async () => (await selected()).ids).toEqual([gid]);
  expect((await selected()).zoom).toBeCloseTo(before.zoom);
});

test("каталог мотивов поддерживает страницы и фильтр участника", async ({ page }) => {
  const top = await (await page.request.get("/api/top?limit=20")).json();
  const gid: string = top.items[0].gid;
  await page.goto("/?view=motifs");
  await expect(page.getByText(/1–30 из/)).toBeVisible();
  await page.getByRole("button", { name: "Следующая страница" }).click();
  await expect(page.getByText(/31–60 из/)).toBeVisible();
  await page.getByLabel("gid участника").fill(gid);
  await expect(page.getByRole("button", { name: "Предыдущая страница" })).toBeDisabled();
  await page.getByLabel("Тип мотива").selectOption("cycle");
  await expect(page.getByLabel("gid участника")).toHaveValue(gid);
});

test("ошибка загрузки мотивов видна аналитику", async ({ page }) => {
  await page.route("**/api/typologies?*", route => route.fulfill({ status: 503, body: "temporary error" }));
  await page.goto("/?view=motifs");
  await expect(page.getByText("Не удалось загрузить мотивы.")).toBeVisible();
});
