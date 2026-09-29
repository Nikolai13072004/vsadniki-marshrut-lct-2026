import { hm, Plan } from "@/lib/types";

type DeadlineAlert = {
  jobId: string;
  sourceId: string;
  address: string;
  kind: "unassigned" | "sla_late" | "sla_risk" | "window_risk";
  detail: string;
  slack: number | null;
};

function collectAlerts(plan: Plan): DeadlineAlert[] {
  const jobs = new Map(plan.snapshot.jobs.map((job) => [job.id, job]));
  const alerts: DeadlineAlert[] = [];
  const windowBuffer = plan.snapshot.settings.sla_risk_buffer;

  for (const item of plan.unassigned) {
    const job = jobs.get(item.job_id);
    if (!job) continue;
    alerts.push({
      jobId: job.id,
      sourceId: job.source_id || job.id,
      address: job.address,
      kind: "unassigned",
      detail: `Окно начала ${hm(job.window_start)}-${hm(job.window_end)}`,
      slack: null,
    });
  }

  for (const route of plan.routes) {
    for (const stop of route.stops) {
      const job = jobs.get(stop.job_id);
      if (!job || stop.status === "completed" || stop.status === "in_progress")
        continue;

      if (
        job.sla_deadline !== null &&
        (stop.sla_status === "late" || stop.sla_status === "risk")
      ) {
        alerts.push({
          jobId: job.id,
          sourceId: job.source_id || job.id,
          address: job.address,
          kind: stop.sla_status === "late" ? "sla_late" : "sla_risk",
          detail: `Срок SLA ${hm(job.sla_deadline)} · ${route.engineer_name}`,
          slack: stop.sla_slack_minutes ?? null,
        });
      }

      const windowSlack = job.window_end - stop.start;
      if (windowSlack <= windowBuffer) {
        alerts.push({
          jobId: job.id,
          sourceId: job.source_id || job.id,
          address: job.address,
          kind: "window_risk",
          detail: `Начало в ${hm(stop.start)} · окно до ${hm(job.window_end)}`,
          slack: windowSlack,
        });
      }
    }
  }

  const order = { unassigned: 0, sla_late: 1, sla_risk: 2, window_risk: 3 };
  return alerts.sort((left, right) => {
    return (
      order[left.kind] - order[right.kind] ||
      (left.slack ?? 0) - (right.slack ?? 0)
    );
  });
}

function alertLabel(alert: DeadlineAlert): string {
  switch (alert.kind) {
    case "unassigned":
      return "Нет назначения";
    case "sla_late":
      return `SLA: опоздание ${Math.abs(alert.slack ?? 0)} мин`;
    case "sla_risk":
      return `SLA: запас ${alert.slack} мин`;
    case "window_risk":
      return `Запас окна ${alert.slack} мин`;
  }
}

export function DeadlineOverview({
  plan,
  onSelect,
}: {
  plan: Plan;
  onSelect: (jobId: string) => void;
}) {
  const alerts = collectAlerts(plan);
  const unassigned = alerts.filter(
    (alert) => alert.kind === "unassigned",
  ).length;
  const sla = alerts.filter(
    (alert) => alert.kind === "sla_late" || alert.kind === "sla_risk",
  ).length;
  const windows = alerts.filter((alert) => alert.kind === "window_risk").length;
  const slaJobs = plan.snapshot.jobs.filter(
    (job) => job.sla_deadline !== null,
  ).length;
  const windowBuffer = plan.snapshot.settings.sla_risk_buffer;

  return (
    <section className="deadline-overview" aria-label="Контроль сроков">
      <div className="deadline-heading">
        <div>
          <div className="eyebrow">ВНИМАНИЕ ДИСПЕТЧЕРА</div>
          <h2>Контроль сроков</h2>
        </div>
        <span>По рассчитанному плану · не GPS-прогноз</span>
      </div>
      <div className="deadline-counts">
        <span>
          <strong>{unassigned}</strong> без назначения
        </span>
        <span>
          <strong>{sla}</strong> риск / нарушение SLA
        </span>
        <span>
          <strong>{windows}</strong> близко к концу окна
        </span>
      </div>
      {alerts.length ? (
        <div className="deadline-list">
          {alerts.map((alert) => (
            <button
              key={`${alert.jobId}-${alert.kind}`}
              className={`deadline-row ${alert.kind}`}
              onClick={() => onSelect(alert.jobId)}
            >
              <strong>№ {alert.sourceId}</strong>
              <span>
                {alert.address}
                <small>{alert.detail}</small>
              </span>
              <em>{alertLabel(alert)}</em>
            </button>
          ))}
        </div>
      ) : (
        <p className="deadline-empty">
          В найденном плане нет заявок, требующих внимания по заданным срокам.
        </p>
      )}
      <p className="deadline-note">
        Окно ограничивает начало работы; предупреждение появляется при запасе не
        больше {windowBuffer} мин.
        {slaJobs
          ? ` Отдельный SLA задан у ${slaJobs} заявок.`
          : " Отдельные сроки SLA в этом наборе не заданы."}
      </p>
    </section>
  );
}
