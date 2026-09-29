"use client";
import { useEffect, useRef, useState } from "react";
import {
  Dataset,
  Engineer,
  Job,
  Plan,
  Settings,
  Skill,
  Transport,
  hm,
  minutes,
  skills,
  transports,
  workingEngineerIds,
} from "@/lib/types";

const items = (text: string) => [
  ...new Set(
    text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  ),
];

export function ExtraJobFields({
  job,
  onChange,
  showPriority = true,
}: {
  job: Job;
  onChange: (job: Job) => void;
  showPriority?: boolean;
}) {
  return (
    <>
      {showPriority ? (
        <label>
          Приоритет
          <select
            value={job.priority}
            onChange={(e) =>
              onChange({ ...job, priority: e.target.value as Job["priority"] })
            }
          >
            <option value="normal">Обычная</option>
            <option value="urgent">Срочная</option>
          </select>
        </label>
      ) : null}
      <label>
        Участок обслуживания
        <input
          required
          value={job.service_area}
          onChange={(e) => onChange({ ...job, service_area: e.target.value })}
        />
      </label>
      <label>
        Срок SLA (отдельно от окна)
        <input
          type="time"
          value={job.sla_deadline === null ? "" : hm(job.sla_deadline)}
          onChange={(e) =>
            onChange({
              ...job,
              sla_deadline: e.target.value ? minutes(e.target.value) : null,
            })
          }
        />
      </label>
      <label>
        Требуемое оборудование через запятую
        <input
          key={job.id}
          defaultValue={job.required_equipment.join(", ")}
          onBlur={(e) =>
            onChange({ ...job, required_equipment: items(e.target.value) })
          }
        />
      </label>
    </>
  );
}

export function AdvancedSettings({
  settings,
  onChange,
}: {
  settings: Settings;
  onChange: (s: Settings) => void;
}) {
  return (
    <div className="settings-grid">
      <section>
        <h3>Оборудование и совместимость</h3>
        <label>
          Учитывать матрицу типов работ
          <input
            type="checkbox"
            checked={settings.equipment_enabled}
            onChange={(e) =>
              onChange({ ...settings, equipment_enabled: e.target.checked })
            }
          />
        </label>
        <p>
          Оборудование задаётся для заявки и выдаётся инженеру на день. Навык,
          транспорт и оборудование - независимые ограничения. Комплект инженера
          меняется в его карточке.
        </p>
        <label>
          Каталог через запятую
          <input
            defaultValue={settings.equipment_catalog.join(", ")}
            onBlur={(e) =>
              onChange({
                ...settings,
                equipment_catalog: items(e.target.value),
              })
            }
          />
        </label>
        <details>
          <summary>Матрица требований по типу работы</summary>
          {[
            ...new Set([
              ...Object.keys(settings.normative_durations),
              ...Object.keys(settings.durations),
            ]),
          ].map((name) => (
            <label key={name}>
              {name}
              <input
                aria-label={`Оборудование ${name}`}
                defaultValue={(
                  settings.equipment_by_work_type[name] || []
                ).join(", ")}
                onBlur={(e) =>
                  onChange({
                    ...settings,
                    equipment_by_work_type: {
                      ...settings.equipment_by_work_type,
                      [name]: items(e.target.value),
                    },
                  })
                }
              />
            </label>
          ))}
        </details>
      </section>
      <section>
        <h3>SLA и устойчивость плана</h3>
        <label>
          Учитывать мягкий SLA
          <input
            type="checkbox"
            checked={settings.sla_enabled}
            onChange={(e) =>
              onChange({ ...settings, sla_enabled: e.target.checked })
            }
          />
        </label>
        <label>
          Срок относится к
          <select
            value={settings.sla_basis}
            onChange={(e) =>
              onChange({
                ...settings,
                sla_basis: e.target.value as Settings["sla_basis"],
              })
            }
          >
            <option value="start">Началу работы</option>
            <option value="finish">Завершению работы</option>
          </select>
        </label>
        <label>
          Запас до срока для риска, мин
          <input
            type="number"
            min="0"
            max="240"
            value={settings.sla_risk_buffer}
            onChange={(e) =>
              onChange({ ...settings, sla_risk_buffer: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Вес опоздания
          <input
            type="number"
            min="0"
            max="100"
            value={settings.sla_penalty}
            onChange={(e) =>
              onChange({ ...settings, sla_penalty: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Вес изменения назначения
          <input
            type="number"
            min="0"
            max="100"
            value={settings.change_penalty}
            onChange={(e) =>
              onChange({ ...settings, change_penalty: Number(e.target.value) })
            }
          />
        </label>
        <p>
          Срок задаётся в карточке заявки. Риск - детерминированный запас
          времени, не вероятность. SLA и стабильность - мягкие критерии после
          назначений, числа инженеров, аварий, подключений и пробега.
        </p>
      </section>
    </div>
  );
}

export function EngineerForm({
  value,
  onChange,
  onSave,
  busy,
}: {
  value: Engineer;
  onChange: (e: Engineer) => void;
  onSave: () => void;
  busy: boolean;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <label>
        Имя инженера
        <input
          required
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
      </label>
      <label>
        Участок обслуживания
        <input
          required
          value={value.service_area}
          onChange={(e) => onChange({ ...value, service_area: e.target.value })}
        />
      </label>
      <label>
        Типовые часы для этой бригады
        <select
          value={
            value.shift_start === 600 && value.shift_end === 1320
              ? "2/2"
              : value.shift_start === 540 && value.shift_end === 1080
                ? "5/2"
                : "custom"
          }
          onChange={(e) => {
            if (e.target.value === "2/2") {
              onChange({ ...value, shift_start: 600, shift_end: 1320 });
            } else if (e.target.value === "5/2") {
              onChange({ ...value, shift_start: 540, shift_end: 1080 });
            }
          }}
        >
          <option value="2/2">2/2 · 10:00–22:00</option>
          <option value="5/2">5/2 · 09:00–18:00</option>
          <option value="custom">Свои часы</option>
        </select>
      </label>
      <div className="form-row">
        <label>
          Начало смены
          <input
            required
            type="time"
            value={hm(value.shift_start)}
            onChange={(e) =>
              onChange({ ...value, shift_start: minutes(e.target.value) })
            }
          />
        </label>
        <label>
          Конец смены
          <input
            required
            type="time"
            value={hm(value.shift_end)}
            onChange={(e) =>
              onChange({ ...value, shift_end: minutes(e.target.value) })
            }
          />
        </label>
      </div>
      <p>
        Пресет задаёт часы только этого инженера в выбранный день. Календарь
        выходных не рассчитывается; часы ниже можно изменить вручную.
      </p>
      <fieldset>
        <legend>Навыки (хотя бы один)</legend>
        {Object.entries(skills).map(([key, name]) => (
          <label className="check-label" key={key}>
            <input
              type="checkbox"
              checked={value.skills.includes(key as Skill)}
              onChange={(e) =>
                onChange({
                  ...value,
                  skills: e.target.checked
                    ? [...value.skills, key as Skill]
                    : value.skills.filter((s) => s !== key),
                })
              }
            />
            {name}
          </label>
        ))}
      </fieldset>
      <label>
        Транспорт
        <select
          value={value.transport}
          onChange={(e) =>
            onChange({ ...value, transport: e.target.value as Transport })
          }
        >
          {Object.entries(transports).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Оборудование через запятую
        <input
          defaultValue={value.equipment.join(", ")}
          onBlur={(e) =>
            onChange({ ...value, equipment: items(e.target.value) })
          }
        />
      </label>
      <label>
        Старт рабочего дня
        <select
          value={value.start_mode}
          onChange={(e) =>
            onChange({
              ...value,
              start_mode: e.target.value as Engineer["start_mode"],
            })
          }
        >
          <option value="office">Офис района</option>
          <option value="home">Из дома</option>
          <option value="custom">Другая точка</option>
        </select>
      </label>
      <label>
        Подпись стартовой точки
        <input
          value={value.start_address}
          placeholder={
            value.start_mode === "office"
              ? "Адрес офиса из набора"
              : "Например: домашняя стартовая точка"
          }
          onChange={(e) =>
            onChange({ ...value, start_address: e.target.value })
          }
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={value.available}
          onChange={(e) =>
            onChange({
              ...value,
              available: e.target.checked,
              unavailable_from: null,
            })
          }
        />
        Доступен для работы
      </label>
      <div className="form-row">
        {(["latitude", "longitude"] as const).map((key) => (
          <label key={key}>
            {key === "latitude" ? "Широта старта" : "Долгота старта"}
            <input
              required
              type="number"
              min={key === "latitude" ? -90 : -180}
              max={key === "latitude" ? 90 : 180}
              step="any"
              value={value.start_location?.[key] ?? ""}
              onChange={(e) =>
                onChange({
                  ...value,
                  start_location: {
                    latitude: value.start_location?.latitude || 0,
                    longitude: value.start_location?.longitude || 0,
                    [key]: Number(e.target.value),
                  },
                })
              }
            />
          </label>
        ))}
      </div>
      <button className="primary full" disabled={busy || !value.skills.length}>
        Сохранить профиль
      </button>
    </form>
  );
}

export function ManualForm({
  plan,
  jobId,
  eventTime,
  onSave,
  busy,
}: {
  plan: Plan;
  jobId: string;
  eventTime: number;
  onSave: (body: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const [engineer, setEngineer] = useState(
    plan.snapshot.engineers[0]?.id || "",
  );
  const [time, setTime] = useState(
    hm(Math.max(eventTime, plan.event?.time || 0)),
  );
  const [position, setPosition] = useState(0),
    [lock, setLock] = useState(true);
  const [activateEngineer, setActivateEngineer] = useState(false);
  const roster = workingEngineerIds(plan);
  const needsActivation = !roster.has(engineer);
  const future =
    plan.routes
      .find((r) => r.engineer_id === engineer)
      ?.stops.filter((s) => s.start > minutes(time) && s.job_id !== jobId) ||
    [];
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          job_id: jobId,
          engineer_id: engineer,
          time: minutes(time),
          position,
          lock,
          activate_engineer: needsActivation && activateEngineer,
        });
      }}
    >
      <p>
        Сохраняет порядок остальных работ. Выполнимость проверяется до создания
        версии; ошибка не изменит текущий план.
      </p>
      <label>
        Инженер для назначения
        <select
          value={engineer}
          onChange={(e) => {
            setEngineer(e.target.value);
            setPosition(0);
            setActivateEngineer(false);
          }}
        >
          {plan.snapshot.engineers.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
              {!roster.has(e.id) ? " (не задействован в плане дня)" : ""}
            </option>
          ))}
        </select>
      </label>
      <label>
        Момент ручной правки
        <input
          type="time"
          required
          value={time}
          onChange={(e) => {
            setTime(e.target.value);
            setPosition(0);
          }}
        />
      </label>
      <label>
        Позиция в оставшемся маршруте
        <select
          value={position}
          onChange={(e) => setPosition(Number(e.target.value))}
        >
          {Array.from({ length: future.length + 1 }, (_, i) => (
            <option key={i} value={i}>
              {i + 1}.{" "}
              {i < future.length
                ? `Перед ${plan.snapshot.jobs.find((j) => j.id === future[i].job_id)?.source_id}`
                : "В конец маршрута"}
            </option>
          ))}
        </select>
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={lock}
          onChange={(e) => setLock(e.target.checked)}
        />
        Зафиксировать инженера и начало для будущих пересчётов
      </label>
      {needsActivation ? (
        <div className="attention" role="status">
          <div>
            <p>
              Инженер не задействован в первоначальном плане. Отдельный вызов
              нужно согласовать; участок, ресурсы и смена всё равно проверяются.
            </p>
            <label className="check-label">
              <input
                type="checkbox"
                checked={activateEngineer}
                onChange={(e) => setActivateEngineer(e.target.checked)}
              />
              Подтверждаю отдельный вызов инженера на этот день
            </label>
          </div>
        </div>
      ) : null}
      <button
        className="primary full"
        disabled={busy || (needsActivation && !activateEngineer)}
      >
        Проверить и назначить
      </button>
    </form>
  );
}

export function makeUrgent(ds: Dataset, time: number): Job {
  return {
    id: crypto.randomUUID(),
    source_id: "СРОЧНАЯ",
    source_line: 0,
    address: ds.office_address,
    raw_address: "",
    district: ds.region,
    service_area: ds.jobs[0]?.service_area || ds.region,
    location: ds.office_location,
    geo_quality: ds.office_geo_quality,
    geo_note: ds.office_geo_note,
    work_type: "Авария",
    bk_type: "Глобальная проблема",
    window_start: time,
    window_end: Math.min(1439, time + ds.settings.demo_urgent_window),
    duration_minutes: ds.settings.demo_urgent_duration,
    required_skill: "emergency",
    required_transport: null,
    required_equipment: [],
    priority: "urgent",
    sla_deadline: null,
    provenance: { priority: "configured", location: "computed" },
  };
}

export function makeOrdinary(ds: Dataset, time: number): Job {
  const kind = "Локальная заявка";
  return {
    id: crypto.randomUUID(),
    source_id: "НОВАЯ",
    source_line: 0,
    address: ds.office_address,
    raw_address: "",
    district: ds.region,
    service_area: ds.jobs[0]?.service_area || ds.region,
    location: ds.office_location,
    geo_quality: ds.office_geo_quality,
    geo_note: ds.office_geo_note,
    work_type: kind,
    bk_type: kind,
    window_start: time,
    window_end: Math.min(1439, time + 120),
    duration_minutes: ds.settings.normative_service_durations[kind] || 30,
    required_skill: "local",
    required_transport: null,
    required_equipment: [],
    priority: "normal",
    sla_deadline: null,
    provenance: { priority: "configured", location: "computed" },
  };
}

export function useDialogFocus(open: boolean | string, close: () => void) {
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = "hidden";
    const dialog = document.querySelector<HTMLElement>("[role=dialog]");
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea, [tabindex="0"]',
        ) || [],
      ).filter((e) => e.offsetParent !== null);
    focusable()[0]?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key === "Tab") {
        const all = focusable(),
          first = all[0],
          last = all[all.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
      document.documentElement.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, [open]);
}
