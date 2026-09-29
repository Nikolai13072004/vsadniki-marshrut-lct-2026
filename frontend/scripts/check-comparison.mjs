import assert from "node:assert/strict";
import { test } from "node:test";
import {
  comparisonRows,
  comparisonChange,
  formatComparison,
} from "../lib/comparison.ts";

const baseline = {
  assigned: 6,
  total: 12,
  unassigned: 6,
  engineers_used: 3,
  distance_m: 30500,
  travel_minutes: 72,
};
const optimized = {
  assigned: 11,
  total: 12,
  unassigned: 1,
  engineers_used: 2,
  distance_m: 48800,
  travel_minutes: 114,
};

test("отношения используют точные значения, а не округлённые подписи", () => {
  const rows = comparisonRows(baseline, optimized);
  const distance = rows.find(
    (row) => row.label === "Пробег на назначенную заявку",
  );
  assert.equal(distance.before, 30.5 / 6);
  assert.equal(distance.after, 48.8 / 11);
  assert.equal(formatComparison(distance.before, distance.digits), "5,08");
  assert.equal(formatComparison(distance.after, distance.digits), "4,44");
  assert.equal(comparisonChange(distance), "-12,7 %");
  const travel = rows.find(
    (row) => row.label === "Дорога на назначенную заявку",
  );
  assert.equal(travel.before, 12);
  assert.equal(travel.after, 114 / 11);
});

test("доля назначений считается по собственному размеру каждого плана", () => {
  const rows = comparisonRows(baseline, { ...optimized, total: 13 });
  const coverage = rows.find((row) => row.coverage);
  assert.equal(coverage.before, 50);
  assert.equal(coverage.after, 1100 / 13);
  assert.equal(comparisonChange(coverage), "+34,6 п.п.");
});

test("ноль назначений не создаёт Infinity, NaN или ложный нулевой пробег на заявку", () => {
  const empty = {
    ...baseline,
    assigned: 0,
    total: 0,
    distance_m: 0,
    travel_minutes: 0,
  };
  const rows = comparisonRows(empty, optimized);
  for (const row of rows.filter(
    (row) => row.coverage || row.label.includes("на назначенную"),
  )) {
    assert.equal(row.before, null);
    assert.equal(formatComparison(row.before), "-");
    assert.equal(comparisonChange(row), "Нет базы для сравнения");
  }
  assert.equal(comparisonChange(rows[0]), "+11 (слева 0)");
  assert.equal(comparisonChange({ label: "Ноль", before: 0, after: 0 }), "0 %");
});

test("знак означает изменение, а не оценку качества плана", () => {
  const rows = comparisonRows(baseline, optimized);
  assert.equal(comparisonChange(rows[0]), "+83,3 %");
  assert.equal(
    comparisonChange(
      rows.find((row) => row.label === "Задействованные инженеры"),
    ),
    "-33,3 %",
  );
  assert.equal(
    comparisonChange(rows.find((row) => row.label === "Общий пробег")),
    "+60 %",
  );
});
