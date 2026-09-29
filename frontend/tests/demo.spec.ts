import { test, expect } from "@playwright/test";

test("основной сценарий: два плана, объяснения, срочная, сравнение и экспорт", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "План рабочего дня" }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Набор данных" }),
  ).toHaveValue("demo");
  await page
    .getByRole("button", { name: "Построить планы", exact: false })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "План рассчитан",
    { timeout: 45000 },
  );
  await expect(
    page.getByText("Проверка ограничений пройдена", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".deadline-overview")).toContainText(
    "Контроль сроков",
  );
  await expect(page.locator(".deadline-overview")).toContainText(
    "Отдельные сроки SLA в этом наборе не заданы",
  );
  await expect(page.getByLabel("Карта заявок и маршрутов")).toBeVisible();
  await page
    .getByRole("button", { name: "Расписание", exact: false })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Порядок посещения" }),
  ).toBeVisible();
  await page.locator(".timeline-work").first().click();
  await expect(
    page.getByRole("dialog", { name: "Карточка заявки" }),
  ).toContainText("Почему это назначение");
  await expect(page.locator(".explanations")).toContainText("внутри окна");
  await page.getByRole("button", { name: "Закрыть карточку" }).click();
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  await page
    .getByRole("combobox", { name: "Статус заявок" })
    .selectOption("unassigned");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.locator(".job-link").first().click();
  await expect(page.getByRole("dialog")).toContainText("Причина неназначения");
  await expect(page.locator(".explanations")).toContainText("не помещается");
  await expect(page.locator(".assignment-help")).toContainText(
    "Что можно проверить",
  );
  await expect(page.locator(".assignment-help")).toContainText(
    "Согласуйте с клиентом другое окно",
  );
  await page.getByRole("button", { name: "Закрыть карточку" }).click();
  await page
    .getByRole("button", { name: "Сравнение планов", exact: false })
    .click();
  await expect(page.locator(".comparison")).toContainText("Оптимизированный");
  await expect(page.locator(".region-report tbody tr")).toHaveCount(3);
  await page
    .getByRole("button", { name: "Изменения дня", exact: false })
    .click();
  await page
    .getByRole("button", { name: "Посмотреть план со срочной заявкой" })
    .click();
  await expect(page.locator(".event-result")).toContainText(
    "ПРЕДПРОСМОТР · НЕ СОХРАНЁН",
    { timeout: 45000 },
  );
  await expect(
    page.locator(".event-map .route-stop-pin.changed").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить этот план" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 2 сохранена",
    { timeout: 45000 },
  );
  await expect(page.locator(".changes-list")).toContainText("СРОЧНАЯ-1");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
  await page
    .getByRole("button", { name: "Маршруты", exact: false })
    .first()
    .click();
  await page.screenshot({
    path: `output/playwright/demo-${test.info().project.name}.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("недоступная подложка не блокирует работу", async ({ page }) => {
  await page.route("**/tile.openstreetmap.org/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByLabel("Карта заявок и маршрутов")).toBeVisible();
  await expect(
    page.getByText("Подложка карты недоступна.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Построить планы", exact: false })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "План рассчитан",
    { timeout: 45000 },
  );
  await page
    .getByRole("button", { name: "Расписание", exact: false })
    .first()
    .click();
  await expect(page.locator(".timeline-work").first()).toBeVisible();
});

test("планирование доступно на узком экране", async ({ page }) => {
  await page.setViewportSize({ width: 780, height: 1024 });
  await page.goto("/");
  await expect(
    page.getByRole("combobox", { name: "Набор данных" }),
  ).toHaveValue("demo");
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Поиск заявки" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
