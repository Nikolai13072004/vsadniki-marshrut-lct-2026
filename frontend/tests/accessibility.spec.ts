import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("доступность основных экранов WCAG AA", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Набор данных")).toHaveValue("demo");
  await page
    .getByRole("button", { name: "Построить планы", exact: false })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "План рассчитан",
  );
  for (const screen of [
    "Маршруты",
    "Заявки и инженеры",
    "Расписание",
    "Сравнение планов",
    "Изменения дня",
    "Справочники",
  ]) {
    await page
      .getByRole("button", { name: screen, exact: false })
      .first()
      .click();
    if (screen === "Маршруты")
      await expect(page.getByLabel("Карта заявок и маршрутов")).toBeVisible();
    const report = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      report.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          summary: n.failureSummary,
        })),
      })),
      screen,
    ).toEqual([]);
    if (screen === "Справочники")
      await page.screenshot({
        path: `output/playwright/settings-${test.info().project.name}.png`,
        fullPage: true,
      });
  }
  await page.getByRole("button", { name: "Импорт" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const dialog = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    dialog.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.failureSummary),
    })),
  ).toEqual([]);
});
