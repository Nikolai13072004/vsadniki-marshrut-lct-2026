"use client";
import { AdvancedSettings } from "./AdvancedControls";
import {
  Settings,
  Skill,
  Transport,
  hm,
  minutes,
  skills,
  transports,
} from "@/lib/types";

type PlanningSettingsProps = {
  settings: Settings;
  onChange: (settings: Settings) => void;
  onSave: () => void;
  onOpenJson: () => void;
  busy: boolean;
};

// This panel edits a draft; persistence and revision checks stay in Workspace.
export function PlanningSettings({
  settings,
  onChange,
  onSave,
  onOpenJson,
  busy,
}: PlanningSettingsProps) {
  return (
    <>
      <div className="section-title">
        <h2>Временные правила</h2>
        <div className="button-row">
          <button className="secondary" onClick={onOpenJson}>
            Все настройки
          </button>
          <button className="primary" disabled={!!busy} onClick={onSave}>
            Сохранить настройки
          </button>
        </div>
      </div>
      <p className="settings-intro">
        Нормативы получены от постановщика 16.09.2026. Транспорт, скорости,
        смены и квалификации остаются изменяемыми допущениями. Изменения
        применяются только к полям, полученным из настроек.
      </p>
      <div className="settings-grid">
        <section>
          <h3>Рабочий день и расчёт</h3>
          <label>
            Начало смены
            <input
              type="time"
              value={hm(settings.shift_start)}
              onChange={(e) =>
                onChange({
                  ...settings,
                  shift_start: minutes(e.target.value),
                })
              }
            />
          </label>
          <label>
            Конец смены
            <input
              type="time"
              value={hm(settings.shift_end)}
              onChange={(e) =>
                onChange({
                  ...settings,
                  shift_end: minutes(e.target.value),
                })
              }
            />
          </label>
          <label>
            Лимит расчёта, секунд
            <input
              type="number"
              min="1"
              max="25"
              value={settings.time_limit_seconds}
              onChange={(e) =>
                onChange({
                  ...settings,
                  time_limit_seconds: Number(e.target.value),
                })
              }
            />
          </label>
          <label>
            Seed
            <input
              type="number"
              value={settings.seed}
              onChange={(e) =>
                onChange({
                  ...settings,
                  seed: Number(e.target.value),
                })
              }
            />
          </label>
        </section>
        <section>
          <h3>Дорога и транспорт</h3>
          <label>
            Источник расстояний
            <select
              value={settings.routing_provider}
              onChange={(e) =>
                onChange({
                  ...settings,
                  routing_provider: e.target
                    .value as Settings["routing_provider"],
                })
              }
            >
              <option value="estimate">Автономный расчёт</option>
              <option value="osrm">OSRM с резервным расчётом</option>
            </select>
          </label>
          <label>
            Дорожный коэффициент
            <input
              type="number"
              min="1"
              max="3"
              step="0.1"
              value={settings.road_factor}
              onChange={(e) =>
                onChange({
                  ...settings,
                  road_factor: Number(e.target.value),
                })
              }
            />
          </label>
          {Object.entries(settings.speeds_kmh).map(([key, value]) => (
            <label key={key}>
              {transports[key as Transport]}, км/ч
              <input
                type="number"
                min="1"
                max="150"
                value={value}
                onChange={(e) =>
                  onChange({
                    ...settings,
                    speeds_kmh: {
                      ...settings.speeds_kmh,
                      [key]: Number(e.target.value),
                    },
                  })
                }
              />
            </label>
          ))}
          <p className="field-note">
            Для общественного транспорта используется редактируемая средняя
            скорость. Исторические и прогнозные пробки в статическом плане не
            моделируются.
          </p>
        </section>
        <section className="durations">
          <h3>Длительности работ, минут</h3>
          <label>
            Учёт 20 минут дороги из норматива
            <select
              value={settings.normative_travel_mode}
              onChange={(e) =>
                onChange({
                  ...settings,
                  normative_travel_mode: e.target
                    .value as Settings["normative_travel_mode"],
                })
              }
            >
              <option value="separate">Дорога только по маршруту</option>
              <option value="included">Полный норматив плюс маршрут</option>
            </select>
          </label>
          <p className="field-note">
            Основной режим вычитает фиксированные 20 минут из норматива и
            учитывает фактическую дорогу по маршруту. Это исключает двойной
            учёт. Полный норматив вместе с маршрутом оставлен только для
            сценарного сравнения.
          </p>
          {Object.entries(settings.normative_durations).map(([name, value]) => (
            <label key={name}>
              {name}
              <input
                aria-label={`Длительность ${name}`}
                type="number"
                min="1"
                max="1440"
                value={value}
                onChange={(e) =>
                  onChange({
                    ...settings,
                    normative_durations: {
                      ...settings.normative_durations,
                      [name]: Number(e.target.value),
                    },
                  })
                }
              />
            </label>
          ))}
          <details>
            <summary>Нормативы без фиксированной дороги</summary>
            {Object.entries(settings.normative_service_durations).map(
              ([name, value]) => (
                <label key={name}>
                  {name}
                  <input
                    aria-label={`Работа без дороги ${name}`}
                    type="number"
                    min="1"
                    max="1440"
                    value={value}
                    onChange={(e) =>
                      onChange({
                        ...settings,
                        normative_service_durations: {
                          ...settings.normative_service_durations,
                          [name]: Number(e.target.value),
                        },
                      })
                    }
                  />
                </label>
              ),
            )}
          </details>
        </section>
        <section>
          <h3>Навыки по типам BK</h3>
          {Object.entries(settings.skill_mapping).map(([name, value]) => (
            <label key={name}>
              {name}
              <select
                value={value}
                onChange={(e) =>
                  onChange({
                    ...settings,
                    skill_mapping: {
                      ...settings.skill_mapping,
                      [name]: e.target.value as Skill,
                    },
                  })
                }
              >
                {Object.entries(skills).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <h3>Срочная заявка для демо</h3>
          <label>
            Длительность
            <input
              type="number"
              min="1"
              value={settings.demo_urgent_duration}
              onChange={(e) =>
                onChange({
                  ...settings,
                  demo_urgent_duration: Number(e.target.value),
                })
              }
            />
          </label>
          <label>
            Ширина окна, минут
            <input
              type="number"
              value={settings.demo_urgent_window}
              onChange={(e) =>
                onChange({
                  ...settings,
                  demo_urgent_window: Number(e.target.value),
                })
              }
            />
          </label>
        </section>
      </div>
      <AdvancedSettings settings={settings} onChange={onChange} />
      <div className="calculation-note">
        Поля SLA хранятся отдельно от временного окна. Конец окна не является
        официальным SLA Билайн.
      </div>
    </>
  );
}
