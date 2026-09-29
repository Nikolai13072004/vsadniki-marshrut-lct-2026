import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("тёмная тема переключается, сохраняется и доступна на мобильном", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const darkToggle = page.getByRole("button", {
    name: "Включить тёмную тему",
  });
  await expect(darkToggle).toBeVisible();
  await darkToggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  const report = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(report.violations).toEqual([]);

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: "Включить светлую тему" }),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Включить светлую тему" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "План рабочего дня" }),
  ).toBeVisible();
});

test("тёмная тема сохраняет контраст кнопок и переключатель при прокрутке", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("marshrut-theme", "dark"),
  );
  await page.goto("/");

  await page.getByRole("button", { name: "Заявки и инженеры" }).click();
  const edit = page
    .getByRole("button", { name: /Редактировать заявку/ })
    .first();
  await expect(edit).toBeVisible();
  await expect(edit).toHaveCSS("color", "rgb(245, 245, 242)");
  await expect(edit).toHaveCSS("background-color", "rgb(41, 41, 40)");

  await page.getByRole("button", { name: "Справочники" }).click();
  const allSettings = page.getByRole("button", { name: "Все настройки" });
  await expect(allSettings).toHaveCSS("color", "rgb(245, 245, 242)");
  await expect(allSettings).toHaveCSS("background-color", "rgb(41, 41, 40)");
  await expect(page.locator(".settings-grid").first()).toHaveCSS("gap", "20px");
  await expect(page.locator(".settings-grid section").first()).toHaveCSS(
    "padding",
    "24px",
  );

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(
    page.getByRole("button", { name: "Включить светлую тему" }),
  ).toBeInViewport();
});
