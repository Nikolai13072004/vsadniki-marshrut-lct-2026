import type { Metrics } from "./types";

export type ComparisonRow = {
  label: string;
  before: number | null;
  after: number | null;
  unit?: string;
  digits?: number;
  coverage?: boolean;
};

function perAssigned(value: number, assigned: number): number | null {
  return assigned > 0 ? value / assigned : null;
}

export function comparisonRows(a: Metrics, b: Metrics): ComparisonRow[] {
  return [
    { label: "Назначенные заявки", before: a.assigned, after: b.assigned },
    {
      label: "Доля назначений",
      before: a.total > 0 ? (100 * a.assigned) / a.total : null,
      after: b.total > 0 ? (100 * b.assigned) / b.total : null,
      unit: "%",
      digits: 1,
      coverage: true,
    },
    {
      label: "Задействованные инженеры",
      before: a.engineers_used,
      after: b.engineers_used,
    },
    {
      label: "Общий пробег",
      before: a.distance_m / 1000,
      after: b.distance_m / 1000,
      unit: "км",
      digits: 1,
    },
    {
      label: "Время в дороге",
      before: a.travel_minutes,
      after: b.travel_minutes,
      unit: "мин",
      digits: 1,
    },
    {
      label: "Пробег на назначенную заявку",
      before: perAssigned(a.distance_m / 1000, a.assigned),
      after: perAssigned(b.distance_m / 1000, b.assigned),
      unit: "км",
      digits: 2,
    },
    {
      label: "Дорога на назначенную заявку",
      before: perAssigned(a.travel_minutes, a.assigned),
      after: perAssigned(b.travel_minutes, b.assigned),
      unit: "мин",
      digits: 2,
    },
    { label: "Без назначения", before: a.unassigned, after: b.unassigned },
  ];
}

export function formatComparison(value: number | null, digits = 0): string {
  return value === null
    ? "-"
    : value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
}

export function comparisonChange(row: ComparisonRow): string {
  if (row.before === null || row.after === null)
    return "Нет базы для сравнения";
  const delta = row.after - row.before;
  const signed = (value: number) =>
    value.toLocaleString("ru-RU", {
      maximumFractionDigits: 1,
      signDisplay: "exceptZero",
    });
  if (row.coverage) return `${signed(delta)} п.п.`;
  if (row.before === 0) {
    return delta === 0
      ? "0 %"
      : `${signed(delta)}${row.unit ? ` ${row.unit}` : ""} (слева 0)`;
  }
  return `${signed((100 * delta) / row.before)} %`;
}
