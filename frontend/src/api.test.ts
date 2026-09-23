import { afterEach, expect, test, vi } from "vitest";
import { getJson } from "./api";
import { uniqueSuffixLabels } from "./Graph";

afterEach(() => vi.unstubAllGlobals());

test("ошибка API сохраняет диагностический текст", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, text: async () => "run unavailable" }));
  await expect(getJson("/api/summary")).rejects.toThrow("run unavailable");
});

test("подписи gid становятся уникальными при одинаковых окончаниях", () => {
  const gids = ["100000001234100", "100000002234100", "100000003234100"];
  const labels = uniqueSuffixLabels(gids);
  expect(new Set(labels.values()).size).toBe(gids.length);
  expect(gids.every((gid) => gid.endsWith(labels.get(gid)!))).toBe(true);
  expect([...labels.values()].every((label) => label.length > 6)).toBe(true);
});
