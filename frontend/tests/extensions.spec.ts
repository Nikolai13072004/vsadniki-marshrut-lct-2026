import { test, expect, Page } from "@playwright/test";
import { resolve } from "node:path";

async function isolatedDataset(page: Page) {
  const ds = await (await page.request.get("/api/datasets/demo")).json();
  delete ds.validation;
  ds.name = `Автотест ${test.info().project.name} ${Date.now()}`;
  const imported = await page.request.post("/api/datasets/import", {
    multipart: {
      file: {
        name: "fixture.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(ds)),
      },
    },
  });
  expect(imported.ok()).toBeTruthy();
  const value = await imported.json();
  await page.goto("/");
  await page.getByLabel("Набор данных").selectOption(value.id);
  await expect(page.getByLabel("Набор данных")).toHaveValue(value.id);
  return value.id as string;
}

async function calculate(page: Page) {
  await page
    .getByRole("button", { name: "Построить планы", exact: false })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "План рассчитан",
  );
}

test("отмена и недоступность: две последовательные версии", async ({
  page,
}) => {
  await isolatedDataset(page);
  await calculate(page);
  await page
    .getByRole("button", { name: "Изменения дня", exact: false })
    .click();
  await page.getByLabel("Тип события").selectOption("cancel");
  await page.getByLabel("Объект события").selectOption("demo-j01");
  await page
    .getByRole("button", { name: "Применить и перепланировать" })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 2 готова",
  );
  await page.getByLabel("Тип события").selectOption("unavailable");
  await page.getByLabel("Объект события").selectOption("demo-e1");
  await page
    .getByRole("button", { name: "Посмотреть изменения до подтверждения" })
    .click();
  await expect(page.locator(".event-result")).toContainText(
    "ПРЕДПРОСМОТР · НЕ СОХРАНЁН",
  );
  await expect(page.locator(".history summary")).toContainText(
    "Сохранённые планы · 3",
  );
  await page.getByRole("button", { name: "Подтвердить этот план" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 3 сохранена",
  );
  await expect(page.locator(".event-result")).toContainText("После · v3");
});

test("диспетчер последовательно ведёт заявку до завершения", async ({
  page,
}, testInfo) => {
  await isolatedDataset(page);
  await calculate(page);
  await page
    .getByRole("button", { name: "Изменения дня", exact: false })
    .click();
  await page.getByLabel("Тип события").selectOption("status_en_route");
  await page.getByLabel("Время события").fill("19:00");
  const target = page.getByLabel("Объект события");
  await expect(target.locator("option")).not.toHaveCount(1);
  await target.selectOption({ index: 1 });
  const jobId = await target.inputValue();
  await page.getByRole("button", { name: "Зафиксировать статус" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 2 готова",
  );

  await page.getByLabel("Тип события").selectOption("status_in_progress");
  await page.getByLabel("Объект события").selectOption(jobId);
  await page.getByRole("button", { name: "Зафиксировать статус" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 3 готова",
  );
  await page.screenshot({
    path: `output/playwright/statuses-${testInfo.project.name}.png`,
    fullPage: true,
  });

  await page.getByLabel("Тип события").selectOption("complete");
  await page.getByLabel("Объект события").selectOption(jobId);
  await page
    .getByRole("button", { name: "Завершить и перепланировать" })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 4 готова",
  );
});

test("диспетчер переносит временное окно клиента", async ({ page }) => {
  await isolatedDataset(page);
  await calculate(page);
  await page
    .getByRole("button", { name: "Изменения дня", exact: false })
    .click();
  await page.getByLabel("Тип события").selectOption("reschedule");
  await page.getByLabel("Время события").fill("10:45");
  await page.getByLabel("Объект события").selectOption("demo-j01");
  await page.getByLabel("Новое начало окна").fill("18:30");
  await page.getByLabel("Новый конец окна").fill("20:30");
  await page
    .getByRole("button", { name: "Посмотреть изменения до подтверждения" })
    .click();
  await expect(page.locator(".event-result")).toContainText(
    "ПРЕДПРОСМОТР · НЕ СОХРАНЁН",
  );
  await page.getByRole("button", { name: "Подтвердить этот план" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 2 сохранена",
  );
});

test("обычная заявка добавляется через изменения дня", async ({ page }) => {
  await isolatedDataset(page);
  await calculate(page);
  await page
    .getByRole("button", { name: "Изменения дня", exact: false })
    .click();
  await page.getByLabel("Тип события").selectOption("new");
  await page.getByLabel("Время события").fill("13:00");
  await page.getByRole("button", { name: "Ввести новую заявку" }).click();

  const dialog = page.getByRole("dialog", { name: "Новая обычная заявка" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Тип заявки").selectOption("Дозаказ");
  await dialog.getByLabel("Адрес").fill("Москва, тестовый адрес 1");
  await expect(dialog.getByLabel("Широта")).toBeEmpty();
  await expect(dialog.getByLabel("Долгота")).toBeEmpty();
  await expect(dialog.getByRole("status")).toContainText("широту и долготу");
  await dialog
    .getByRole("button", { name: "Попробовать вставить в план" })
    .click();
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Широта").fill("55.75");
  await dialog.getByLabel("Долгота").fill("37.62");
  await dialog
    .getByRole("button", { name: "Попробовать вставить в план" })
    .click();

  await expect(page.locator(".banner[role=status]")).toContainText(
    "Версия 2 готова",
  );
  await expect(page.locator(".event-notice")).toContainText(
    /свободн|без изменений/i,
  );
});

test("смена адреса заявки требует новых координат", async ({ page }) => {
  const datasetId = await isolatedDataset(page);
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  const technicalTools = page.locator(".technical-tools");
  await expect(technicalTools.getByRole("button")).not.toBeVisible();
  await technicalTools.locator("summary").click();
  await expect(technicalTools.getByRole("button")).toBeVisible();
  await technicalTools.locator("summary").click();
  await page
    .getByRole("button", { name: "Редактировать заявку Д-001" })
    .click();

  const dialog = page.getByRole("dialog", { name: "Изменить заявку Д-001" });
  await dialog.getByLabel("Адрес").fill("Москва, улица Тестовая, дом 10");
  await expect(dialog.getByLabel("Широта")).toBeEmpty();
  await expect(dialog.getByLabel("Долгота")).toBeEmpty();
  await dialog.getByLabel("Широта").fill("55.71");
  await dialog.getByRole("button", { name: "Сохранить заявку" }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Долгота")).toBeEmpty();

  await dialog.getByLabel("Долгота").fill("37.64");
  await dialog.getByRole("button", { name: "Сохранить заявку" }).click();
  await expect(dialog).not.toBeVisible();
  const saved = await (
    await page.request.get(`/api/datasets/${datasetId}`)
  ).json();
  const job = saved.jobs.find(
    (item: { source_id: string }) => item.source_id === "Д-001",
  );
  expect(job.address).toBe("Москва, улица Тестовая, дом 10");
  expect(job.location).toEqual({ latitude: 55.71, longitude: 37.64 });
  expect(job.geo_quality).toBe("manual");
  await calculate(page);
});

test("ручное назначение: отказ ресурса и успешная фиксация", async ({
  page,
}) => {
  await isolatedDataset(page);
  await calculate(page);
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  await page.getByRole("button", { name: "№ Д-001", exact: true }).click();
  await page.getByRole("button", { name: "Назначить вручную" }).click();
  await page.getByLabel("Момент ручной правки").fill("09:00");
  await page.getByLabel("Инженер для назначения").selectOption("demo-e2");
  await page
    .getByLabel("Подтверждаю отдельный вызов инженера на этот день")
    .check();
  await page.getByRole("button", { name: "Проверить и назначить" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "транспорт",
  );
  await page.getByLabel("Инженер для назначения").selectOption("demo-e1");
  const options = await page
    .getByLabel("Позиция в оставшемся маршруте")
    .locator("option")
    .count();
  await page
    .getByLabel("Позиция в оставшемся маршруте")
    .selectOption(String(options - 1));
  await page.getByRole("button", { name: "Проверить и назначить" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Ручное назначение проверено",
  );
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("формы профиля, оборудования, SLA и сравнения вариантов", async ({
  page,
}) => {
  await isolatedDataset(page);
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  await page.getByRole("button", { name: "Инженеры · 4" }).click();
  await page.getByLabel("Редактировать инженера Соколов Алексей").click();
  await page.getByLabel("Имя инженера").fill("Соколов Алексей - тест");
  await page
    .getByLabel("Оборудование через запятую")
    .fill("Тестер линии, Роутер, Кабельный комплект");
  await page.getByLabel("Оборудование через запятую").blur();
  await page.getByRole("button", { name: "Сохранить профиль" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("tbody")).toContainText("Соколов Алексей - тест");
  await page.getByRole("button", { name: "Справочники", exact: false }).click();
  await page.getByLabel("Учитывать матрицу типов работ").check();
  await page.getByLabel("Учитывать мягкий SLA").check();
  await page
    .getByRole("button", { name: "Сохранить настройки", exact: true })
    .click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Данные сохранены",
  );
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  await expect(page.locator("tbody")).toContainText("Тестер линии");
  await page.getByRole("button", { name: "Заявки · 12" }).click();
  await page.getByLabel("Редактировать заявку Д-001").click();
  await page.getByLabel("Срок SLA (отдельно от окна)").fill("09:01");
  await page
    .getByRole("button", { name: "Сохранить заявку", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await calculate(page);
  await page.getByRole("button", { name: "Маршруты", exact: false }).click();
  await expect(page.locator(".deadline-overview")).toContainText(
    "SLA: опоздание",
  );
  await page
    .locator(".deadline-row")
    .filter({ hasText: "Д-001" })
    .first()
    .click();
  await expect(page.locator(".sla.late")).toContainText("Опоздание");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Сравнение планов", exact: false })
    .click();
  await page.getByRole("button", { name: "Тщательный вариант" }).click();
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Дополнительный вариант готов",
  );
  expect(await page.getByLabel("Левый план").inputValue()).not.toEqual(
    await page.getByLabel("Правый план").inputValue(),
  );
  await page.screenshot({
    path: `output/playwright/extensions-${test.info().project.name}.png`,
    fullPage: true,
  });
});

test("мобильный экран и управление фокусом импорта", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("Набор данных")).toHaveValue("demo");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Импорт" }).click();
  await expect(
    page.getByRole("dialog", { name: "Импорт данных" }),
  ).toBeVisible();
  await page.getByLabel("Участок для нового CSV").fill("Восток");
  await page.getByRole("button", { name: "Закрыть редактор" }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect(
    page.getByRole("button", { name: "Выбрать CSV или JSON" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Импорт" })).toBeFocused();
  const map = await page.locator(".map-shell").boundingBox();
  expect(map?.width).toBeGreaterThan(300);
  const legend = await page.locator(".map-label").boundingBox();
  expect(legend!.x + legend!.width).toBeLessThanOrEqual(map!.x + map!.width);
  await page.screenshot({
    path: `output/playwright/mobile-${test.info().project.name}.png`,
    fullPage: true,
  });
});

test("исходный CP1251 CSV: импорт, новый инженер и расчёт", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByLabel("Набор данных")).toHaveValue("demo");
  await page.getByRole("button", { name: "Импорт" }).click();
  await page
    .locator("input[type=file]")
    .setInputFiles(resolve("../data/raw/Восток Синтетические данные.csv"));
  await expect(
    page.getByRole("dialog", { name: "Импорт данных" }),
  ).toContainText("Для CSV укажите участок");
  await page.getByLabel("Участок для нового CSV").fill("Восток");
  await page.getByLabel("Кодировка").selectOption("cp1251");
  await page.getByLabel("Разделитель").selectOption(";");
  await page
    .locator("input[type=file]")
    .setInputFiles(resolve("../data/raw/Восток Синтетические данные.csv"));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".banner[role=status]")).toContainText(
    "Файл загружен",
  );
  await expect(
    page.getByRole("button", { name: "Заявки · 66", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Построить планы", exact: false }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Инженеры · 0", exact: true }).click();
  await page
    .getByRole("button", { name: "Добавить инженера", exact: true })
    .click();
  await page.getByLabel("Имя инженера").fill("Инженер проверки импорта");
  await page.getByLabel("Подключение и дозаказы", { exact: true }).check();
  await page.getByLabel("Глобальные проблемы", { exact: true }).check();
  await expect(page.getByLabel("Широта старта")).not.toHaveValue("");
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const datasetId = await page.getByLabel("Набор данных").inputValue();
  const dataset = await (
    await page.request.get(`/api/datasets/${datasetId}`)
  ).json();
  expect(dataset.jobs).toHaveLength(66);
  expect(dataset.engineers).toHaveLength(1);
  expect(dataset.engineers[0].skills).toEqual(
    expect.arrayContaining(["local", "connection", "emergency"]),
  );
  expect(
    dataset.validation.filter(
      (issue: { severity: string }) => issue.severity === "error",
    ),
  ).toEqual([]);
  await calculate(page);
  await page
    .getByRole("button", { name: "Маршруты", exact: false })
    .first()
    .click();
  await expect(
    page.getByText("Проверка ограничений пройдена", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Набор данных")).toHaveValue("demo");
  await page.getByLabel("Набор данных").selectOption(datasetId);
  await page
    .getByRole("button", { name: "Заявки и инженеры", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "Заявки · 66", exact: true }),
  ).toBeVisible();
});

test("первичная загрузка не допускает выбора ещё не готового набора", async ({
  page,
}) => {
  let release!: () => void;
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/datasets/demo", async (route) => {
    await ready;
    await route.continue();
  });
  await page.goto("/");
  await expect(page.getByLabel("Набор данных")).toBeDisabled();
  release();
  await expect(page.getByLabel("Набор данных")).toHaveValue("demo");
  await expect(page.getByLabel("Набор данных")).toBeEnabled();
});

test("локальный доступ: чужой Host и изменение со стороннего сайта запрещены", async ({
  request,
}) => {
  expect(
    (
      await request.get("/api/datasets", {
        headers: { host: "foreign.example" },
      })
    ).status(),
  ).toBe(400);
  expect(
    (
      await request.post("/api/plans/optimize", {
        headers: { origin: "https://foreign.example" },
        data: { dataset_id: "demo" },
      })
    ).status(),
  ).toBe(403);
  expect((await request.get("/api/health")).ok()).toBeTruthy();
});
