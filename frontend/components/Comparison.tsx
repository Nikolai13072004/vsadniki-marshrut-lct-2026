import type { Plan } from "@/lib/types";
import {
  comparisonChange,
  comparisonRows,
  formatComparison,
} from "@/lib/comparison";

export function Comparison({
  before,
  after,
  compact = false,
}: {
  before: Plan;
  after: Plan;
  compact?: boolean;
}) {
  const a = before.metrics;
  const b = after.metrics;
  const moreWorkAndDistance =
    b.assigned > a.assigned && b.distance_m > a.distance_m;
  return (
    <section aria-label="Показатели сравнения планов">
      <div className={`comparison ${compact ? "compact" : ""}`}>
        <table>
          <thead>
            <tr>
              <th scope="col">Показатель</th>
              <th scope="col">
                {before.mode === "baseline"
                  ? "Базовый"
                  : `До · v${before.version}`}
              </th>
              <th scope="col">
                {after.mode === "baseline"
                  ? "Базовый"
                  : after.parent_id
                    ? `После · v${after.version}`
                    : "Оптимизированный"}
              </th>
              <th scope="col">Изменение к левому плану</th>
            </tr>
          </thead>
          <tbody>
            {comparisonRows(a, b).map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td>
                  {formatComparison(row.before, row.digits)}
                  {row.before !== null && row.unit ? ` ${row.unit}` : ""}
                </td>
                <td className="comparison-current">
                  <strong>
                    {formatComparison(row.after, row.digits)}
                    {row.after !== null && row.unit ? ` ${row.unit}` : ""}
                  </strong>
                </td>
                <td>{comparisonChange(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="calculation-note comparison-scroll-hint">
        На узком экране таблицу можно прокрутить вправо.
      </p>
      <p className="calculation-note">
        Назначено {a.assigned} из {a.total} слева и {b.assigned} из {b.total}{" "}
        справа. Это плановые назначения, не подтверждение выполненных работ.
        Показатели на заявку делятся на число назначений; при нуле назначений
        показан дефис. П.п. - процентные пункты.
      </p>
      {moreWorkAndDistance ? (
        <p className="calculation-note">
          Общий пробег вырос одновременно с числом назначений. Для оценки
          сравните пробег на назначенную заявку; сам рост объёма не доказывает
          экономию маршрута.
        </p>
      ) : null}
      {a.total !== b.total ? (
        <p className="calculation-note">
          Количество заявок в планах различается. Разница описывает эти два
          снимка, а не чистый эффект алгоритма на одинаковых данных.
        </p>
      ) : null}
    </section>
  );
}
