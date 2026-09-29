"use client";
import {
  EngineerForm,
  ExtraJobFields,
  ManualForm,
  makeOrdinary,
  makeUrgent,
  useDialogFocus,
} from "./AdvancedControls";
import dynamic from "next/dynamic";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock3,
  Download,
  GitCompareArrows,
  History,
  MapPinned,
  Moon,
  Navigation,
  Play,
  Route,
  Settings2,
  Sun,
  Upload,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { PlanningSettings } from "./PlanningSettings";
import { DeadlineOverview } from "./DeadlineOverview";
import { Comparison } from "./Comparison";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  Assignment,
  colors,
  Dataset,
  Engineer,
  hm,
  Job,
  JobStatus,
  json,
  km,
  minutes,
  Plan,
  RegionReport,
  Settings,
  Skill,
  skills,
  Summary,
  Transport,
  transports,
  workingEngineerIds,
} from "@/lib/types";

const RouteMap = dynamic(() => import("./RouteMap"), {
  ssr: false,
  loading: () => <div className="map-loading">Загрузка карты…</div>,
});
const tabs = [
  { id: "routes", name: "Маршруты", Icon: Route },
  { id: "data", name: "Заявки и инженеры", Icon: ClipboardList },
  { id: "schedule", name: "Расписание", Icon: CalendarDays },
  { id: "compare", name: "Сравнение планов", Icon: GitCompareArrows },
  { id: "events", name: "Изменения дня", Icon: History },
  { id: "settings", name: "Справочники", Icon: Settings2 },
];
const pageTitles: Record<string, [string, string]> = {
  routes: [
    "План рабочего дня",
    "Распределение заявок и маршруты выездных инженеров",
  ],
  data: ["Заявки и инженеры", "Исходные данные, проверка и редактирование"],
  schedule: [
    "Расписание выездов",
    "Переезды, ожидание и работы в пределах смены",
  ],
  compare: [
    "Эффективность плана",
    "Базовое распределение и результат оптимизации",
  ],
  events: [
    "Изменения рабочего дня",
    "Перестройка будущих маршрутов с сохранением выполненных работ",
  ],
  settings: [
    "Справочники и допущения",
    "Редактируемые правила планирования из раздела 15 ТЗ",
  ],
};

export default function Workspace() {
  const [datasets, setDatasets] = useState<Summary[]>([]),
    [ds, setDs] = useState<Dataset | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [plan, setPlan] = useState<Plan | null>(null),
    [baseline, setBaseline] = useState<Plan | null>(null),
    [before, setBefore] = useState<Plan | null>(null);
  const [previewPlan, setPreviewPlan] = useState<Plan | null>(null);
  const [regionReport, setRegionReport] = useState<RegionReport | null>(null);
  const [tab, setTab] = useState("routes"),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [engineerId, setEngineerId] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"),
    [showEngineers, setShowEngineers] = useState(false);
  const [editJob, setEditJob] = useState<Job | null>(null),
    [editor, setEditor] = useState<{
      title: string;
      value: string;
      kind: "engineers" | "dataset" | "settings";
    } | null>(null);
  const [jobCoordinates, setJobCoordinates] = useState({
    latitude: "",
    longitude: "",
  });
  const [settings, setSettings] = useState<Settings | null>(null),
    [eventTime, setEventTime] = useState("13:00");
  const [eventType, setEventType] = useState("urgent"),
    [eventTarget, setEventTarget] = useState("");
  const [eventWindowStart, setEventWindowStart] = useState("14:00"),
    [eventWindowEnd, setEventWindowEnd] = useState("16:00");
  const [history, setHistory] = useState<
    {
      id: string;
      mode: string;
      version: number;
      metrics: Plan["metrics"];
      event: Plan["event"];
    }[]
  >([]);
  const upload = useRef<HTMLInputElement>(null);
  const sectionNav = useRef<HTMLElement>(null);
  const [navEdges, setNavEdges] = useState({ left: false, right: false });
  const loadSequence = useRef(0);
  const [editEngineer, setEditEngineer] = useState<Engineer | null>(null);
  const [manualJob, setManualJob] = useState<string | null>(null);
  const [jobEventType, setJobEventType] = useState<"new" | "urgent" | null>(
    null,
  );
  const [importOpen, setImportOpen] = useState(false),
    [encoding, setEncoding] = useState(""),
    [delimiter, setDelimiter] = useState(""),
    [importRegion, setImportRegion] = useState("");
  const [openingDatasetId, setOpeningDatasetId] = useState<string | null>(null);
  useDialogFocus(
    selected
      ? "card"
      : editJob
        ? "job"
        : editor
          ? "json"
          : editEngineer
            ? "engineer"
            : manualJob
              ? "manual"
              : importOpen
                ? "import"
                : "",
    () => {
      setSelected(null);
      setEditJob(null);
      setJobEventType(null);
      setEditor(null);
      setEditEngineer(null);
      setManualJob(null);
      setImportOpen(false);
    },
  );
  const pickJob = useCallback((id: string) => setSelected(id), []);
  function openJobEditor(job: Job) {
    setEditJob({ ...job });
    setJobCoordinates({
      latitude: job.location?.latitude.toString() ?? "",
      longitude: job.location?.longitude.toString() ?? "",
    });
  }

  function changeJobCoordinate(key: "latitude" | "longitude", value: string) {
    if (!editJob) return;
    const next = { ...jobCoordinates, [key]: value };
    setJobCoordinates(next);
    setEditJob({
      ...editJob,
      geo_quality: "manual",
      geo_note: "Координаты введены диспетчером",
      location:
        next.latitude !== "" && next.longitude !== ""
          ? {
              latitude: Number(next.latitude),
              longitude: Number(next.longitude),
            }
          : null,
    });
  }

  const load = useCallback(async (id: string) => {
    const request = ++loadSequence.current;
    const [data, plans] = await Promise.all([
      api<Dataset>(`/datasets/${id}`),
      api<typeof history>(`/plans?dataset_id=${id}`),
    ]);
    if (request !== loadSequence.current) return;
    setDs(data);
    setSettings(data.settings);
    setHistory(plans);
    setPlan(null);
    setBaseline(null);
    setBefore(null);
    setPreviewPlan(null);
    setSelected(null);
    setEngineerId("");
    setEventTime(hm(data.settings.demo_event_time));
    setEventTarget("");
    setNotice("");
  }, []);
  useEffect(() => {
    const current =
      document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    setTheme(current);
  }, []);
  useEffect(() => {
    let active = true;
    api<Summary[]>("/datasets")
      .then(async (items) => {
        if (!active) return;
        setDatasets(items);
        if (items.length) await load(items[0].id);
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
      loadSequence.current += 1;
    };
  }, [load]);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("marshrut-theme", next);
    setTheme(next);
  }
  useEffect(() => {
    api<RegionReport>("/reports/regions")
      .then(setRegionReport)
      .catch(() => setRegionReport(null));
  }, []);
  useEffect(() => {
    const nav = sectionNav.current;
    if (!nav) return;

    const updateEdges = () => {
      const left = nav.scrollLeft > 2;
      const right = nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 2;
      setNavEdges((current) =>
        current.left === left && current.right === right
          ? current
          : { left, right },
      );
    };

    const observer = new ResizeObserver(updateEdges);
    observer.observe(nav);
    nav.addEventListener("scroll", updateEdges, { passive: true });
    window.addEventListener("resize", updateEdges);
    updateEdges();

    return () => {
      observer.disconnect();
      nav.removeEventListener("scroll", updateEdges);
      window.removeEventListener("resize", updateEdges);
    };
  }, []);

  function scrollSections(direction: -1 | 1) {
    const nav = sectionNav.current;
    if (!nav) return;
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    nav.scrollBy({
      left: direction * Math.round(nav.clientWidth * 0.75),
      behavior: reducedMotion ? "auto" : "smooth",
    });
  }
  async function work(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Операция не выполнена");
    } finally {
      setBusy("");
    }
  }
  async function refreshHistory(id: string) {
    setHistory(await api(`/plans?dataset_id=${id}`));
  }
  async function openDataset(id: string) {
    setOpeningDatasetId(id);
    try {
      await work("Открываем набор…", () => load(id));
    } finally {
      setOpeningDatasetId(null);
    }
  }
  async function calculate() {
    if (!ds) return;
    await work("Строим базовый план…", async () => {
      const base = await api<Plan>(
        "/plans/baseline",
        json({ dataset_id: ds.id }),
      );
      setBaseline(base);
      setPlan(base);
      setBusy("Оптимизируем маршруты…");
      const result = await api<Plan>(
        "/plans/optimize",
        json({ dataset_id: ds.id }),
      );
      setPlan(result);
      setBefore(null);
      setPreviewPlan(null);
      setEngineerId("");
      setNotice(
        `План рассчитан за ${result.calculation_seconds.toLocaleString("ru-RU")} с. Назначено ${result.metrics.assigned} из ${result.metrics.total} заявок.`,
      );
      await refreshHistory(ds.id);
    });
  }
  async function savePatch(patch: Record<string, unknown>) {
    if (!ds) return;
    const data = await api<Dataset>(
      `/datasets/${ds.id}`,
      json({ revision: ds.revision, ...patch }, "PATCH"),
    );
    setDs(data);
    setSettings(data.settings);
    setPlan(null);
    setBaseline(null);
    setBefore(null);
    setPreviewPlan(null);
    setSelected(null);
    setNotice("Данные сохранены. Постройте новый план с учётом изменений.");
  }
  const activePreview =
    previewPlan?.parent_id === plan?.id ? previewPlan : null;
  const displayedPlan =
    tab === "events" && activePreview ? activePreview : plan;
  const shown = displayedPlan?.snapshot || ds;
  const scheduleStart =
    Math.floor(
      Math.min(...(shown?.engineers.map((e) => e.shift_start) || [540])) / 60,
    ) * 60;
  const scheduleEnd =
    Math.ceil(
      Math.max(...(shown?.engineers.map((e) => e.shift_end) || [1320])) / 60,
    ) * 60;
  const scheduleSpan = Math.max(60, scheduleEnd - scheduleStart);
  const stops = useMemo(
    () =>
      new Map(
        displayedPlan?.routes.flatMap((r) =>
          r.stops.map((s) => [s.job_id, s] as const),
        ) || [],
      ),
    [displayedPlan],
  );
  const reasons = useMemo(
    () =>
      new Map(
        displayedPlan?.unassigned.map((u) => [u.job_id, u] as const) || [],
      ),
    [displayedPlan],
  );
  const selectedJob = shown?.jobs.find((j) => j.id === selected);
  const dayRoster = plan ? workingEngineerIds(plan) : null;
  const selectedStop = selected ? stops.get(selected) : null;
  const selectedStatus = selected
    ? currentJobStatus(displayedPlan, selected, selectedStop?.status)
    : "unassigned";
  const rows =
    shown?.jobs.filter(
      (j) =>
        (!search ||
          `${j.address} ${j.source_id} ${j.work_type}`
            .toLowerCase()
            .includes(search.toLowerCase())) &&
        (filter !== "unassigned" || reasons.has(j.id)),
    ) || [];
  const title = pageTitles[tab];
  const eventResult = activePreview || plan;
  const eventBefore = activePreview ? plan : before;

  async function confirmPreview() {
    if (!ds || !plan || !activePreview) return;
    await work("Сохраняем подтверждённый план…", async () => {
      const result = await api<Plan>(
        `/plans/${plan.id}/events/confirm`,
        json({ preview_id: activePreview.id }),
      );
      setBefore(plan);
      setPlan(result);
      setPreviewPlan(null);
      setEngineerId("");
      setNotice(
        `Версия ${result.version} сохранена. Изменений: ${result.changes.length}.`,
      );
      await refreshHistory(ds.id);
    });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="билайн бизнес · маршрут">
          <img className="beeline-logo" src="/beeline-logo.svg" alt="билайн" />
          <span className="product-lockup">
            <img className="route-mark" src="/route-mark.svg" alt="" />
            <span className="product-name">
              <strong>маршрут</strong>
              <span className="brand-caption">планирование выездов</span>
            </span>
          </span>
        </a>
        <div className="nav-label">ДИСПЕТЧЕРСКАЯ</div>
        <div className="section-nav-shell">
          <nav ref={sectionNav} aria-label="Основные разделы">
            {tabs.map((item) => (
              <button
                key={item.id}
                className={`nav-item ${tab === item.id ? "active" : ""}`}
                onClick={() => {
                  setTab(item.id);
                  setSelected(null);
                  setFilter("all");
                }}
              >
                <span className="nav-icon" aria-hidden="true">
                  <item.Icon />
                </span>
                {item.name}
              </button>
            ))}
          </nav>
          {navEdges.left && (
            <button
              type="button"
              className="section-nav-arrow section-nav-arrow-left"
              aria-label="Показать предыдущие разделы"
              onClick={() => scrollSections(-1)}
            >
              <ChevronLeft aria-hidden="true" />
            </button>
          )}
          {navEdges.right && (
            <button
              type="button"
              className="section-nav-arrow section-nav-arrow-right"
              aria-label="Показать следующие разделы"
              onClick={() => scrollSections(1)}
            >
              <ChevronRight aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="sidebar-bottom">
          <span className="live-dot" /> Сервис доступен
          <div>билайн бизнес · Москва</div>
          <small>
            Данные и допущения видны
            <br />
            на каждом этапе расчёта.
          </small>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            билайн бизнес <span>/</span> Выездная служба <span>/</span>{" "}
            Планирование
          </div>
          <div className="topbar-right">
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              aria-label={
                theme === "dark"
                  ? "Включить светлую тему"
                  : "Включить тёмную тему"
              }
              title={
                theme === "dark"
                  ? "Включить светлую тему"
                  : "Включить тёмную тему"
              }
            >
              {theme === "dark" ? (
                <Sun aria-hidden="true" />
              ) : (
                <Moon aria-hidden="true" />
              )}
            </button>
            <span className="operator-avatar">Д</span>
            <span>Диспетчер</span>
          </div>
        </header>
        <section className="page-heading">
          <div className="page-heading-content">
            <div className="hero-kicker">
              <div className="eyebrow">ОПЕРАЦИОННЫЙ ПЛАН</div>
              <span className={`hero-status ${plan ? "ready" : "draft"}`}>
                <span aria-hidden="true" />
                {plan
                  ? `План готов · версия ${plan.version}`
                  : "Ожидает расчёта"}
              </span>
            </div>
            <h1>{title[0]}</h1>
            <p>{title[1]}</p>
            {ds ? (
              <div className="hero-facts" aria-label="Сводка набора данных">
                <span>
                  <strong>{ds.jobs.length}</strong> заявок
                </span>
                <span>
                  <strong>{ds.engineers.length}</strong> инженера
                </span>
                <span>
                  <strong>
                    {ds.validation?.filter(
                      (issue) => issue.severity === "error",
                    ).length || 0}
                  </strong>{" "}
                  ошибок в данных
                </span>
              </div>
            ) : null}
            {ds?.validation?.some((issue) => issue.severity === "error") ? (
              <p>
                Перед расчётом исправьте ошибки в разделе «Заявки и инженеры».
              </p>
            ) : null}
          </div>
          <button
            className="primary"
            onClick={calculate}
            disabled={
              !ds ||
              !!busy ||
              ds.validation?.some((issue) => issue.severity === "error")
            }
          >
            <Play aria-hidden="true" />
            {busy === "Строим базовый план…" ||
            busy === "Оптимизируем маршруты…"
              ? "Выполняется расчёт…"
              : "Построить планы"}
          </button>
        </section>
        <section className="workspace-toolbar">
          <label className="dataset-select">
            <span aria-live="polite">
              Набор данных{openingDatasetId ? " · открываем…" : ""}
            </span>
            <select
              aria-label="Набор данных"
              value={openingDatasetId || ds?.id || ""}
              disabled={!ds || !!busy}
              onChange={(e) => void openDataset(e.target.value)}
            >
              {datasets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="date-label">
            <span>Рабочий день</span>
            <strong>{ds?.date.split("-").reverse().join(".") || "-"}</strong>
          </div>
          <div className="date-label">
            <span>Участок</span>
            <strong>{ds?.region || "-"}</strong>
          </div>
          <div className="toolbar-spacer" />
          <button
            className="text-button"
            disabled={!!busy}
            onClick={() => {
              setError("");
              setImportRegion("");
              setImportOpen(true);
            }}
          >
            <Upload aria-hidden="true" />
            Импорт
          </button>
          <input
            ref={upload}
            type="file"
            accept=".csv,.json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              if (
                file.name.toLowerCase().endsWith(".csv") &&
                !importRegion.trim()
              ) {
                setError(
                  "Для CSV укажите участок, затем выберите файл ещё раз.",
                );
                e.target.value = "";
                return;
              }
              work("Проверяем файл…", async () => {
                const body = new FormData();
                body.append("file", file);
                if (encoding) body.append("encoding", encoding);
                if (delimiter) body.append("delimiter", delimiter);
                body.append("region", importRegion.trim() || "Импорт");
                const imported = await api<Dataset>("/datasets/import", {
                  method: "POST",
                  body,
                });
                setDatasets(await api("/datasets"));
                await load(imported.id);
                setImportOpen(false);
                setTab("data");
                setNotice(
                  "Файл загружен. Проверьте поля и профили инженеров перед расчётом.",
                );
              });
              e.target.value = "";
            }}
          />
          <a
            className={`text-button ${!plan ? "disabled" : ""}`}
            href={plan ? `/api/plans/${plan.id}/export?format=csv` : undefined}
            aria-disabled={!plan}
          >
            <Download aria-hidden="true" />
            CSV
          </a>
          <a
            className={`text-button ${!plan ? "disabled" : ""}`}
            href={plan ? `/api/plans/${plan.id}/export?format=json` : undefined}
            aria-disabled={!plan}
          >
            <Download aria-hidden="true" />
            JSON
          </a>
        </section>
        {error ? (
          <div className="banner error" role="alert">
            <strong>Не удалось выполнить операцию.</strong> {error}
            <button aria-label="Закрыть ошибку" onClick={() => setError("")}>
              ×
            </button>
          </div>
        ) : null}
        {busy ? (
          <div className="banner progress" role="status">
            <span className="spinner" />
            {busy} Предыдущий результат доступен для просмотра.
          </div>
        ) : notice ? (
          <div className="banner success" role="status">
            {notice}
          </div>
        ) : null}
        {!ds ? (
          <div className="empty">
            <h2>Открываем рабочее место</h2>
            <p>
              {error
                ? "Проверьте, что API запущен. Инструкция находится в README."
                : "Загружаем демонстрационные данные…"}
            </p>
          </div>
        ) : (
          <>
            <div className="metrics-strip">
              <Metric
                Icon={Check}
                tone="yellow"
                label="Назначено заявок"
                value={plan ? `${plan.metrics.assigned}` : `${ds.jobs.length}`}
                suffix={plan ? ` / ${plan.metrics.total}` : " в наборе"}
                foot={
                  plan
                    ? `Требуют внимания: ${plan.metrics.unassigned}`
                    : "Готовы к планированию"
                }
              />
              <Metric
                Icon={UsersRound}
                tone="green"
                label="Инженеров на выезде"
                value={plan ? String(plan.metrics.engineers_used) : "-"}
                suffix={` / ${ds.engineers.length}`}
                foot="Хотя бы одна работа или выезд"
              />
              <Metric
                Icon={Navigation}
                tone="violet"
                label="Общий пробег"
                value={plan ? km(plan.metrics.distance_m) : "-"}
                suffix=" км"
                foot={
                  baseline && plan
                    ? deltaText(
                        plan.metrics.distance_m,
                        baseline.metrics.distance_m,
                        "км",
                      )
                    : "От старта до последней заявки"
                }
              />
              <Metric
                Icon={Clock3}
                tone="blue"
                label="Время в дороге"
                value={
                  plan ? String(Math.round(plan.metrics.travel_minutes)) : "-"
                }
                suffix=" мин"
                foot={
                  plan
                    ? `Работы: ${Math.round(plan.metrics.work_minutes / 60)} ч суммарно`
                    : "С учётом типа транспорта"
                }
              />
            </div>
            {tab === "routes" && shown ? (
              <>
                {plan ? (
                  <DeadlineOverview plan={plan} onSelect={pickJob} />
                ) : null}
                <div className="section-title">
                  <h2>
                    Маршруты на карте{" "}
                    <span>
                      {plan
                        ? plan.mode === "baseline"
                          ? "Базовый план"
                          : `Версия ${plan.version}`
                        : "До расчёта"}
                    </span>
                  </h2>
                  <span className="subtle">
                    {plan
                      ? "● Проверка ограничений пройдена"
                      : "Откройте набор и постройте планы"}
                  </span>
                </div>
                <div className="routes-layout">
                  <div className="route-list">
                    <button
                      className={`route-all ${!engineerId ? "selected" : ""}`}
                      onClick={() => setEngineerId("")}
                    >
                      Все инженеры <span>{shown.engineers.length}</span>
                    </button>
                    {shown.engineers.map((e, index) => {
                      const r = plan?.routes.find(
                        (r) => r.engineer_id === e.id,
                      );
                      return (
                        <button
                          className={`route-card ${engineerId === e.id ? "selected" : ""}`}
                          key={e.id}
                          onClick={() =>
                            setEngineerId(engineerId === e.id ? "" : e.id)
                          }
                        >
                          <div className="route-person">
                            <span
                              className="route-color"
                              style={{
                                background: colors[index % colors.length],
                              }}
                            />
                            <strong>{e.name.replace("Бригада ", "")}</strong>
                            <span className="route-count">
                              {r?.stops.length || 0}
                            </span>
                          </div>
                          <div className="route-meta">
                            {transports[e.transport]} ·{" "}
                            {e.start_mode === "home"
                              ? "старт из дома"
                              : e.start_mode === "office"
                                ? "старт из офиса"
                                : "своя точка старта"}{" "}
                            <span>
                              {r
                                ? `${km(r.distance_m)} км`
                                : hm(e.shift_start) + "-" + hm(e.shift_end)}
                            </span>
                          </div>
                          {r?.stops.length ? (
                            <div className="route-line">
                              <span
                                style={{
                                  width: `${Math.min(100, (r.work_minutes / (e.shift_end - e.shift_start)) * 100)}%`,
                                  background: colors[index % colors.length],
                                }}
                              />
                            </div>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                  <RouteMap
                    dataset={shown}
                    plan={plan}
                    comparePlan={before?.id === plan?.parent_id ? before : null}
                    engineerId={engineerId}
                    onSelect={pickJob}
                  />
                </div>
                <div className="calculation-note">
                  {plan?.routing_notice ||
                    "Координаты подготовлены заранее. Для просмотра деталей нажмите на точку или откройте список заявок."}
                </div>
                {plan?.status === "time_limit" ||
                plan?.status === "fallback" ? (
                  <div className="attention" role="status">
                    {plan.status === "time_limit"
                      ? "Достигнут лимит расчёта. Показан найденный допустимый план."
                      : "Использован допустимый базовый план: оптимизатор не нашёл решения."}
                  </div>
                ) : null}
                {plan?.unassigned.length ? (
                  <div className="attention">
                    <div>
                      <strong>
                        Заявок без назначения: {plan.unassigned.length}
                      </strong>
                      <p>
                        Для каждой указана проверяемая причина и ограничения.
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        setTab("data");
                        setShowEngineers(false);
                        setSearch("");
                        setFilter("unassigned");
                        setSelected(plan.unassigned[0].job_id);
                      }}
                    >
                      Посмотреть причины
                    </button>
                  </div>
                ) : null}
              </>
            ) : null}
            {tab === "data" ? (
              <>
                <div className="section-title">
                  <div className="segmented">
                    <button
                      className={!showEngineers ? "active" : ""}
                      onClick={() => setShowEngineers(false)}
                    >
                      Заявки · {shown?.jobs.length}
                    </button>
                    <button
                      className={showEngineers ? "active" : ""}
                      onClick={() => setShowEngineers(true)}
                    >
                      Инженеры · {ds.engineers.length}
                    </button>
                  </div>
                  {showEngineers ? (
                    <button
                      className="secondary"
                      disabled={!!busy || ds.engineers.length >= 15}
                      onClick={() =>
                        setEditEngineer({
                          id: crypto.randomUUID(),
                          name: "Новый инженер",
                          service_area:
                            ds.engineers[0]?.service_area || ds.region,
                          start_location: ds.office_location,
                          start_mode: "office",
                          start_address: ds.office_address,
                          shift_start: ds.settings.shift_start,
                          shift_end: ds.settings.shift_end,
                          skills: ["local"],
                          transport: "car",
                          equipment: [],
                          available: true,
                          unavailable_from: null,
                          provenance: {},
                        })
                      }
                    >
                      Добавить инженера
                    </button>
                  ) : null}
                </div>
                <details className="technical-tools">
                  <summary>Дополнительно: массовое редактирование</summary>
                  <p>
                    Для обычных изменений используйте кнопки у заявки или
                    инженера. Здесь можно править исходные данные в JSON.
                  </p>
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={() =>
                      setEditor({
                        title: showEngineers
                          ? "Редактор профилей инженеров"
                          : "Редактор нормализованного набора",
                        kind: showEngineers ? "engineers" : "dataset",
                        value: JSON.stringify(
                          showEngineers
                            ? ds.engineers
                            : {
                                jobs: ds.jobs,
                                engineers: ds.engineers,
                                issues: ds.issues,
                              },
                          null,
                          2,
                        ),
                      })
                    }
                  >
                    Редактировать {showEngineers ? "профили" : "набор"} в JSON
                  </button>
                </details>
                {(ds.validation?.length || 0) > 0 ? (
                  <details
                    className="validation"
                    open={ds.validation?.some((i) => i.severity === "error")}
                  >
                    <summary>
                      Проверка данных:{" "}
                      {
                        ds.validation?.filter((i) => i.severity === "error")
                          .length
                      }{" "}
                      ошибок,{" "}
                      {
                        ds.validation?.filter((i) => i.severity === "warning")
                          .length
                      }{" "}
                      предупреждений
                    </summary>
                    <div className="validation-list">
                      {ds.validation?.map((item, i) => (
                        <div key={i} className={item.severity}>
                          <strong>
                            {item.row ? `Строка ${item.row} · ` : ""}
                            {item.field}
                          </strong>{" "}
                          {item.message} {item.value}
                          <small>{item.suggestion}</small>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : (
                  <div className="data-valid">
                    ✓ Обязательные поля заполнены. {ds.source_files.length}{" "}
                    исходных файлов; дополнения отмечены в карточках.
                  </div>
                )}
                {!showEngineers ? (
                  <>
                    <div className="table-tools">
                      <input
                        aria-label="Поиск заявки"
                        placeholder="Найти адрес, номер или тип работы…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                      <select
                        aria-label="Статус заявок"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        <option value="all">Все заявки</option>
                        <option value="unassigned">Без назначения</option>
                      </select>
                      <span>{rows.length} записей</span>
                    </div>
                    <div className="table-wrap jobs-table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Заявка / адрес</th>
                            <th>Тип работы</th>
                            <th>Окно начала</th>
                            <th>Длительность</th>
                            <th>Назначение</th>
                            <th />
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((j) => (
                            <tr key={j.id}>
                              <td>
                                <button
                                  className="job-link"
                                  onClick={() => setSelected(j.id)}
                                >
                                  № {j.source_id || j.id}
                                </button>
                                <div className="address-cell">{j.address}</div>
                              </td>
                              <td>
                                {j.work_type}
                                <small>{skills[j.required_skill]}</small>
                              </td>
                              <td className="nowrap">
                                {hm(j.window_start)}-{hm(j.window_end)}
                              </td>
                              <td>{j.duration_minutes} мин</td>
                              <td>
                                {stops.has(j.id) ? (
                                  <span className="status assigned">
                                    {jobStatusLabel(
                                      currentJobStatus(
                                        plan,
                                        j.id,
                                        stops.get(j.id)?.status,
                                      ),
                                    )}
                                    <small>
                                      {
                                        shown?.engineers.find(
                                          (e) =>
                                            e.id ===
                                            stops.get(j.id)?.engineer_id,
                                        )?.name
                                      }
                                    </small>
                                  </span>
                                ) : (
                                  <>
                                    <span
                                      className={`status ${plan ? "unassigned" : ""}`}
                                    >
                                      {plan
                                        ? "Не назначена"
                                        : "Ожидает расчёта"}
                                    </span>
                                    {reasons.has(j.id) ? (
                                      <>
                                        <small>
                                          {reasons
                                            .get(j.id)!
                                            .reasons.join("; ")}
                                        </small>
                                        <button
                                          className="job-link"
                                          aria-label={`Разобрать причину заявки ${j.source_id || j.id}`}
                                          onClick={() => setSelected(j.id)}
                                        >
                                          Разобрать причину
                                        </button>
                                      </>
                                    ) : null}
                                  </>
                                )}
                              </td>
                              <td>
                                <button
                                  className="small-button"
                                  aria-label={`Редактировать заявку ${j.source_id}`}
                                  disabled={
                                    !!busy ||
                                    !ds.jobs.some(
                                      (original) => original.id === j.id,
                                    )
                                  }
                                  onClick={() => {
                                    setJobEventType(null);
                                    openJobEditor(j);
                                  }}
                                >
                                  Изменить
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!rows.length ? (
                        <div className="empty small">
                          Нет заявок по выбранному фильтру.
                        </div>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Инженер</th>
                          <th>Смена</th>
                          <th>Навыки</th>
                          <th>Транспорт</th>
                          <th>Оборудование</th>
                          <th>Старт</th>
                          <th>Правка</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ds.engineers.map((e) => (
                          <tr key={e.id}>
                            <td>
                              <strong>{e.name}</strong>
                              <small>
                                {e.available ? "Доступен" : "Недоступен"}
                              </small>
                              <small>Участок: {e.service_area}</small>
                              {dayRoster ? (
                                <small>
                                  {dayRoster.has(e.id)
                                    ? "В составе рабочего дня"
                                    : "Не задействован в плане дня"}
                                </small>
                              ) : null}
                            </td>
                            <td>
                              {hm(e.shift_start)}-{hm(e.shift_end)}
                            </td>
                            <td>{e.skills.map((s) => skills[s]).join(", ")}</td>
                            <td>{transports[e.transport]}</td>
                            <td>{e.equipment.join(", ") || "Не задано"}</td>
                            <td>
                              {e.start_mode === "home"
                                ? "Из дома"
                                : e.start_mode === "office"
                                  ? "Офис района"
                                  : "Другая точка"}
                              <small>
                                {e.start_address || shown?.office_address}
                              </small>
                            </td>
                            <td>
                              <button
                                className="small-button"
                                disabled={!!busy}
                                aria-label={`Редактировать инженера ${e.name}`}
                                onClick={() => setEditEngineer({ ...e })}
                              >
                                Изменить
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="calculation-note">
                  Сырые CSV сохранены отдельно. Контрольное распределение -
                  историческая справка. Повторяющиеся адреса остаются отдельными
                  заявками.
                </div>
              </>
            ) : null}
            {tab === "schedule" ? (
              <>
                {!plan ? (
                  <EmptyPlan />
                ) : (
                  <>
                    <div className="section-title">
                      <h2>
                        Смена {hm(scheduleStart)}-{hm(scheduleEnd)}
                      </h2>
                      <div className="schedule-legend">
                        <span className="travel-swatch" /> Дорога{" "}
                        <span className="wait-swatch" /> Ожидание{" "}
                        <span className="work-swatch" /> Работа
                      </div>
                    </div>
                    <div className="timeline-wrap">
                      <div className="timeline-axis">
                        <span>Инженер</span>
                        <div>
                          {Array.from(
                            { length: Math.round(scheduleSpan / 60) + 1 },
                            (_, i) => (
                              <span key={i}>{hm(scheduleStart + i * 60)}</span>
                            ),
                          )}
                        </div>
                      </div>
                      {plan.routes
                        .filter((r) => r.stops.length)
                        .map((r, index) => (
                          <div className="timeline-row" key={r.engineer_id}>
                            <div>
                              <strong>{r.engineer_name}</strong>
                              <small>
                                {r.stops.length} заявок · {km(r.distance_m)} км
                              </small>
                            </div>
                            <div className="timeline-track">
                              {r.legs.map((leg, i) => (
                                <span
                                  key={`leg${i}`}
                                  className="timeline-travel"
                                  title={`Переезд ${hm(leg.departure)}-${hm(leg.arrival)}`}
                                  style={{
                                    left: `${((leg.departure - scheduleStart) / scheduleSpan) * 100}%`,
                                    width: `${((leg.arrival - leg.departure) / scheduleSpan) * 100}%`,
                                  }}
                                />
                              ))}
                              {r.stops.map((s) => (
                                <span key={s.job_id}>
                                  <span
                                    className="timeline-wait"
                                    style={{
                                      left: `${((s.arrival - scheduleStart) / scheduleSpan) * 100}%`,
                                      width: `${(s.waiting_minutes / scheduleSpan) * 100}%`,
                                    }}
                                  />
                                  <button
                                    className="timeline-work"
                                    title={`${shown?.jobs.find((j) => j.id === s.job_id)?.source_id} · ${hm(s.start)}-${hm(s.finish)}`}
                                    aria-label={`Открыть работу ${shown?.jobs.find((j) => j.id === s.job_id)?.source_id}`}
                                    onClick={() => setSelected(s.job_id)}
                                    style={{
                                      left: `${((s.start - scheduleStart) / scheduleSpan) * 100}%`,
                                      width: `${((s.finish - s.start) / scheduleSpan) * 100}%`,
                                      background: colors[index % colors.length],
                                    }}
                                  >
                                    {hm(s.start)}
                                  </button>
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                    </div>
                    <div className="section-title">
                      <h2>Порядок посещения</h2>
                    </div>
                    {plan.routes
                      .filter((r) => r.stops.length)
                      .map((r) => (
                        <details
                          key={r.engineer_id}
                          className="schedule-detail"
                        >
                          <summary>
                            {r.engineer_name}{" "}
                            <span>
                              {r.stops.length} заявок · {km(r.distance_m)} км
                            </span>
                          </summary>
                          <div className="table-wrap">
                            <table>
                              <thead>
                                <tr>
                                  <th>Порядок / адрес</th>
                                  <th>Прибытие</th>
                                  <th>Работы</th>
                                  <th>Переезд</th>
                                  <th>Ожидание</th>
                                </tr>
                              </thead>
                              <tbody>
                                {r.stops.map((s, i) => (
                                  <tr key={s.job_id}>
                                    <td>
                                      <button
                                        className="job-link"
                                        onClick={() => setSelected(s.job_id)}
                                      >
                                        {i + 1}.{" "}
                                        {
                                          shown?.jobs.find(
                                            (j) => j.id === s.job_id,
                                          )?.address
                                        }
                                      </button>
                                    </td>
                                    <td>{hm(s.arrival)}</td>
                                    <td>
                                      {hm(s.start)}-{hm(s.finish)}
                                      {s.status === "completed" ? (
                                        <small>
                                          Завершена в {hm(s.completed_at!)}
                                        </small>
                                      ) : (
                                        <small>
                                          {jobStatusLabel(s.status)}
                                        </small>
                                      )}
                                    </td>
                                    <td>{s.travel_minutes} мин</td>
                                    <td>{s.waiting_minutes} мин</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </details>
                      ))}
                  </>
                )}
              </>
            ) : null}
            {tab === "compare" ? (
              <>
                {regionReport ? (
                  <section className="region-report">
                    <div className="section-title">
                      <div>
                        <div className="eyebrow">
                          ПРОВЕРКА НА ПОЛНЫХ НАБОРАХ
                        </div>
                        <h2>Три участка · воспроизводимый прогон</h2>
                      </div>
                      <span className="subtle">
                        {new Date(regionReport.generated_at).toLocaleDateString(
                          "ru-RU",
                        )}
                      </span>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Участок</th>
                            <th>Назначено</th>
                            <th>Инженеров</th>
                            <th>Пробег</th>
                            <th>В дороге</th>
                            <th>Расчёт</th>
                          </tr>
                        </thead>
                        <tbody>
                          {regionReport.regions.map((row) => {
                            const base = row.baseline.metrics;
                            const result = row.optimized.metrics;
                            return (
                              <tr key={row.dataset_id}>
                                <td>
                                  <strong>{row.region}</strong>
                                  <small>
                                    {row.jobs} заявок · {row.engineers}{" "}
                                    инженеров
                                  </small>
                                </td>
                                <td>
                                  {base.assigned} /{" "}
                                  <strong>{result.assigned}</strong>
                                  <small>из {row.jobs}</small>
                                </td>
                                <td>
                                  {base.engineers_used} /{" "}
                                  <strong>{result.engineers_used}</strong>
                                </td>
                                <td>
                                  {km(base.distance_m)} /{" "}
                                  <strong>{km(result.distance_m)}</strong> км
                                </td>
                                <td>
                                  {Math.round(base.travel_minutes)} /{" "}
                                  <strong>
                                    {Math.round(result.travel_minutes)}
                                  </strong>{" "}
                                  мин
                                </td>
                                <td>
                                  {row.optimized.calculation_seconds.toLocaleString(
                                    "ru-RU",
                                  )}{" "}
                                  с
                                  <small>
                                    {row.optimized.status === "time_limit"
                                      ? "достигнут лимит"
                                      : "допустимый план"}
                                  </small>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <p className="calculation-note">
                      {regionReport.note} В каждой паре сначала указан базовый
                      план, затем оптимизированный. Пробег может вырасти ради
                      большего числа назначений.
                    </p>
                  </section>
                ) : null}
                <div className="comparison-tools">
                  <label>
                    Левый план
                    <select
                      aria-label="Левый план"
                      value={baseline?.id || ""}
                      disabled={!!busy}
                      onChange={(e) =>
                        work("Открываем план сравнения…", async () =>
                          setBaseline(
                            await api<Plan>(`/plans/${e.target.value}`),
                          ),
                        )
                      }
                    >
                      <option value="">Выберите версию</option>
                      {history.map((h) => (
                        <option key={h.id} value={h.id}>
                          {h.mode === "baseline"
                            ? "Базовый"
                            : h.mode === "manual"
                              ? "Ручной"
                              : "Оптимизированный"}{" "}
                          · v{h.version} · {h.metrics.assigned} заявок ·{" "}
                          {h.id.slice(0, 6)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Правый план
                    <select
                      aria-label="Правый план"
                      value={plan?.id || ""}
                      disabled={!!busy}
                      onChange={(e) =>
                        work("Открываем второй план…", async () =>
                          setPlan(await api<Plan>(`/plans/${e.target.value}`)),
                        )
                      }
                    >
                      <option value="">Выберите версию</option>
                      {history.map((h) => (
                        <option key={h.id} value={h.id}>
                          {h.mode === "baseline"
                            ? "Базовый"
                            : h.mode === "manual"
                              ? "Ручной"
                              : "Оптимизированный"}{" "}
                          · v{h.version} · {h.metrics.assigned} заявок ·{" "}
                          {h.id.slice(0, 6)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="secondary"
                    disabled={!!busy || !!plan?.parent_id}
                    onClick={() =>
                      work("Рассчитываем дополнительный вариант…", async () => {
                        const result = await api<Plan>(
                          "/plans/optimize",
                          json({ dataset_id: ds.id, variant: "thorough" }),
                        );
                        if (plan) setBaseline(plan);
                        setPlan(result);
                        setBefore(null);
                        setNotice(
                          "Дополнительный вариант готов. Увеличен предел числа решений; улучшение не гарантируется.",
                        );
                        await refreshHistory(ds.id);
                      })
                    }
                  >
                    Тщательный вариант
                  </button>
                </div>
                {!plan || !baseline ? (
                  <EmptyPlan text="Постройте базовый и оптимизированный планы для сравнения." />
                ) : (
                  <>
                    <Comparison before={baseline} after={plan} />
                    <div className="section-title">
                      <h2>Пробег по инженерам</h2>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Инженер</th>
                            <th>Левый план</th>
                            <th>Текущий план</th>
                            <th>Разница</th>
                          </tr>
                        </thead>
                        <tbody>
                          {plan.routes.map((r) => {
                            const b = baseline.routes.find(
                              (x) => x.engineer_id === r.engineer_id,
                            );
                            return (
                              <tr key={r.engineer_id}>
                                <td>{r.engineer_name}</td>
                                <td>{km(b?.distance_m || 0)} км</td>
                                <td>{km(r.distance_m)} км</td>
                                <td>
                                  {deltaText(
                                    r.distance_m,
                                    b?.distance_m || 0,
                                    "км",
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="calculation-note">
                      Порядок приоритетов: число назначенных заявок, число
                      инженеров, аварии, подключения, пробег. Ремонт и дозаказ
                      идут после подключений. Снижение пробега не достигается
                      ценой потери назначений.{" "}
                      {JSON.stringify(plan.snapshot) !==
                      JSON.stringify(baseline.snapshot)
                        ? "Входные данные или настройки этих версий различаются - учитывайте это при сравнении."
                        : "Оба алгоритма используют одинаковые данные, матрицы и ограничения."}
                    </div>
                  </>
                )}
              </>
            ) : null}
            {tab === "events" ? (
              <>
                {!plan ? (
                  <EmptyPlan />
                ) : (
                  <>
                    <div className="event-layout">
                      <section className="event-form">
                        <div className="eyebrow">СОБЫТИЕ</div>
                        <h2>Перестроить оставшийся день</h2>
                        <p>
                          Начатые и выполненные работы сохранятся. Уже
                          пройденный путь будет учтён.
                        </p>
                        <p>
                          Автоматический пересчёт использует только состав
                          рабочего дня. Инженер без первоначальных назначений
                          подключается отдельно, через подтверждённое ручное
                          назначение.
                        </p>
                        <label>
                          Тип события
                          <select
                            value={eventType}
                            onChange={(e) => {
                              setEventType(e.target.value);
                              setEventTarget("");
                              setPreviewPlan(null);
                            }}
                          >
                            <option value="new">Новая обычная заявка</option>
                            <option value="urgent">Срочная заявка</option>
                            <option value="status_en_route">
                              Статус: инженер в пути
                            </option>
                            <option value="status_in_progress">
                              Статус: выполнение началось
                            </option>
                            <option value="complete">Завершение заявки</option>
                            <option value="reschedule">
                              Перенос времени клиента
                            </option>
                            <option value="cancel">Отмена заявки</option>
                            <option value="unavailable">
                              Недоступность инженера
                            </option>
                          </select>
                        </label>
                        <label>
                          Время события
                          <input
                            aria-label="Время события"
                            type="time"
                            value={eventTime}
                            onChange={(e) => {
                              setEventTime(e.target.value);
                              setPreviewPlan(null);
                            }}
                          />
                        </label>
                        {!["new", "urgent"].includes(eventType) ? (
                          <label>
                            Объект события
                            <select
                              value={eventTarget}
                              onChange={(e) => {
                                const next = e.target.value;
                                setEventTarget(next);
                                setPreviewPlan(null);
                                const job = shown?.jobs.find(
                                  (item) => item.id === next,
                                );
                                if (job && eventType === "reschedule") {
                                  setEventWindowStart(hm(job.window_start));
                                  setEventWindowEnd(hm(job.window_end));
                                }
                              }}
                            >
                              <option value="">Выберите…</option>
                              {eventType === "unavailable"
                                ? shown?.engineers.map((e) => (
                                    <option key={e.id} value={e.id}>
                                      {e.name}
                                    </option>
                                  ))
                                : shown?.jobs
                                    .filter((j) => {
                                      const status = currentJobStatus(
                                        plan,
                                        j.id,
                                        stops.get(j.id)?.status,
                                      );
                                      const stop = stops.get(j.id);
                                      const eventMinute = minutes(eventTime);
                                      if (eventType === "status_en_route")
                                        return (
                                          status === "sent" &&
                                          !!stop &&
                                          stop.departure <= eventMinute
                                        );
                                      if (eventType === "status_in_progress")
                                        return (
                                          status === "en_route" &&
                                          !!stop &&
                                          stop.start <= eventMinute
                                        );
                                      if (eventType === "complete")
                                        return status === "in_progress";
                                      return true;
                                    })
                                    .map((j) => (
                                      <option key={j.id} value={j.id}>
                                        {j.source_id} · {j.address}
                                      </option>
                                    ))}
                            </select>
                          </label>
                        ) : eventType === "urgent" ? (
                          <div className="event-preview">
                            <strong>Демонстрационная срочная заявка</strong>
                            <div>{shown?.office_address}</div>
                            <small>
                              Аварийные работы ·{" "}
                              {shown?.settings.demo_urgent_duration} мин · окно{" "}
                              {shown?.settings.demo_urgent_window} мин
                            </small>
                          </div>
                        ) : (
                          <div className="event-preview">
                            <strong>Новая обычная заявка</strong>
                            <div>
                              Система попробует вставить её в свободный
                              интервал, не меняя существующие назначения.
                            </div>
                          </div>
                        )}
                        {eventType === "reschedule" ? (
                          <div className="form-row">
                            <label>
                              Новое начало окна
                              <input
                                type="time"
                                value={eventWindowStart}
                                onChange={(e) => {
                                  setEventWindowStart(e.target.value);
                                  setPreviewPlan(null);
                                }}
                              />
                            </label>
                            <label>
                              Новый конец окна
                              <input
                                type="time"
                                value={eventWindowEnd}
                                onChange={(e) => {
                                  setEventWindowEnd(e.target.value);
                                  setPreviewPlan(null);
                                }}
                              />
                            </label>
                          </div>
                        ) : null}
                        {eventType !== "new" ? (
                          <button
                            className="primary full"
                            disabled={
                              !!busy || (eventType !== "urgent" && !eventTarget)
                            }
                            onClick={() =>
                              work(
                                "Перепланируем будущие выезды…",
                                async () => {
                                  const isPreview = [
                                    "urgent",
                                    "reschedule",
                                    "unavailable",
                                  ].includes(eventType);
                                  const result = await api<Plan>(
                                    `/plans/${plan.id}/events${isPreview ? "/preview" : ""}`,
                                    json({
                                      type: eventType.startsWith("status_")
                                        ? "status"
                                        : eventType,
                                      time: minutes(eventTime),
                                      demo: eventType === "urgent",
                                      ...(eventType === "cancel" ||
                                      eventType === "complete" ||
                                      eventType === "reschedule" ||
                                      eventType.startsWith("status_")
                                        ? { job_id: eventTarget }
                                        : eventType === "unavailable"
                                          ? { engineer_id: eventTarget }
                                          : {}),
                                      ...(eventType === "reschedule"
                                        ? {
                                            window_start:
                                              minutes(eventWindowStart),
                                            window_end: minutes(eventWindowEnd),
                                          }
                                        : {}),
                                      ...(eventType.startsWith("status_")
                                        ? {
                                            job_status: eventType.replace(
                                              "status_",
                                              "",
                                            ),
                                          }
                                        : {}),
                                    }),
                                  );
                                  if (isPreview) {
                                    setPreviewPlan(result);
                                    setNotice(
                                      "Черновик рассчитан. Проверьте изменения и подтвердите план.",
                                    );
                                  } else {
                                    setBefore(plan);
                                    setPlan(result);
                                    setPreviewPlan(null);
                                    setEngineerId("");
                                    setNotice(
                                      `Версия ${result.version} готова. Изменений: ${result.changes.length}.`,
                                    );
                                    await refreshHistory(ds.id);
                                  }
                                },
                              )
                            }
                          >
                            {eventType === "urgent"
                              ? "Посмотреть план со срочной заявкой"
                              : eventType === "reschedule" ||
                                  eventType === "unavailable"
                                ? "Посмотреть изменения до подтверждения"
                                : eventType.startsWith("status_")
                                  ? "Зафиксировать статус"
                                  : eventType === "complete"
                                    ? "Завершить и перепланировать"
                                    : "Применить и перепланировать"}
                          </button>
                        ) : null}
                        {["new", "urgent"].includes(eventType) && shown ? (
                          <button
                            className={`${eventType === "new" ? "primary" : "secondary"} full`}
                            disabled={!!busy}
                            onClick={() => {
                              const kind = eventType as "new" | "urgent";
                              setJobEventType(kind);
                              openJobEditor(
                                kind === "urgent"
                                  ? makeUrgent(shown, minutes(eventTime))
                                  : makeOrdinary(shown, minutes(eventTime)),
                              );
                            }}
                          >
                            {eventType === "urgent"
                              ? "Ввести свою срочную заявку"
                              : "Ввести новую заявку"}
                          </button>
                        ) : null}
                      </section>
                      <section className="event-result">
                        <div className="eyebrow">
                          {activePreview
                            ? "ПРЕДПРОСМОТР · НЕ СОХРАНЁН"
                            : "РЕЗУЛЬТАТ"}
                        </div>
                        <h2>
                          {activePreview
                            ? "Что изменится после подтверждения"
                            : plan.parent_id
                              ? `Версия ${plan.version}: что изменилось`
                              : "История рабочего дня"}
                        </h2>
                        {eventResult?.event?.notice ? (
                          <p className="event-notice">
                            {eventResult.event.notice}
                          </p>
                        ) : null}
                        {eventBefore && eventResult ? (
                          <Comparison
                            before={eventBefore}
                            after={eventResult}
                            compact
                          />
                        ) : (
                          <p>
                            После события здесь появится сравнение двух версий
                            плана.
                          </p>
                        )}
                        {activePreview ? (
                          <div className="preview-actions">
                            <button
                              className="primary"
                              disabled={!!busy}
                              onClick={confirmPreview}
                            >
                              Подтвердить этот план
                            </button>
                            <button
                              className="secondary"
                              disabled={!!busy}
                              onClick={() => setPreviewPlan(null)}
                            >
                              Оставить прежний план
                            </button>
                          </div>
                        ) : null}
                        {eventResult?.changes.length ? (
                          <div className="changes-list">
                            {eventResult.changes.map((c) => (
                              <button
                                key={c.job_id}
                                onClick={() => setSelected(c.job_id)}
                              >
                                <strong>
                                  {eventResult.snapshot.jobs.find(
                                    (j) => j.id === c.job_id,
                                  )?.source_id || c.job_id}
                                </strong>
                                <span>
                                  {describeAssignment(
                                    c.before,
                                    shown?.engineers || [],
                                  )}{" "}
                                  /{" "}
                                  {describeAssignment(
                                    c.after,
                                    shown?.engineers || [],
                                  )}
                                </span>
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {eventBefore && eventResult ? (
                          <div className="event-map">
                            <RouteMap
                              dataset={eventResult.snapshot}
                              plan={eventResult}
                              comparePlan={eventBefore}
                              engineerId={engineerId}
                              onSelect={pickJob}
                            />
                          </div>
                        ) : null}
                        <details className="history">
                          <summary>
                            Сохранённые планы · {history.length}
                          </summary>
                          {history.map((h) => (
                            <button
                              key={h.id}
                              onClick={() =>
                                work("Открываем версию…", async () => {
                                  const loaded = await api<Plan>(
                                    `/plans/${h.id}`,
                                  );
                                  setPlan(loaded);
                                  setBefore(
                                    loaded.parent_id
                                      ? await api<Plan>(
                                          `/plans/${loaded.parent_id}`,
                                        )
                                      : null,
                                  );
                                })
                              }
                            >
                              {h.event
                                ? eventHistoryLabel(h.event)
                                : h.mode === "baseline"
                                  ? "Базовый"
                                  : "Оптимизированный"}{" "}
                              · v{h.version} · {h.metrics.assigned} заявок ·{" "}
                              {km(h.metrics.distance_m)} км
                            </button>
                          ))}
                        </details>
                      </section>
                    </div>
                  </>
                )}
              </>
            ) : null}
            {tab === "settings" && settings ? (
              <PlanningSettings
                key={`${ds.id}-${ds.revision}`}
                settings={settings}
                onChange={setSettings}
                busy={!!busy}
                onOpenJson={() =>
                  setEditor({
                    title: "Все настройки в JSON",
                    kind: "settings",
                    value: JSON.stringify(settings, null, 2),
                  })
                }
                onSave={() =>
                  work("Сохраняем настройки…", () =>
                    savePatch({ settings, apply_defaults: true }),
                  )
                }
              />
            ) : null}
          </>
        )}
        <footer className="footer">
          <span>билайн бизнес · маршрут</span>
          <span>Время - Москва · расстояния - км</span>
        </footer>
      </main>
      {selectedJob ? (
        <div className="drawer-backdrop" onClick={() => setSelected(null)}>
          <aside
            className="job-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Карточка заявки"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              onClick={() => setSelected(null)}
              aria-label="Закрыть карточку"
            >
              ×
            </button>
            <div className="eyebrow">ЗАЯВКА № {selectedJob.source_id}</div>
            <h2>{selectedJob.work_type}</h2>
            <p className="drawer-address">{selectedJob.address}</p>
            {selectedJob.geo_note ? (
              <p className="geo-note">{selectedJob.geo_note}</p>
            ) : null}
            <span
              className={`status ${selectedStop ? "assigned" : "unassigned"}`}
            >
              {selectedStatus === "completed" && selectedStop?.completed_at
                ? `Завершена в ${hm(selectedStop.completed_at)}`
                : selectedStop
                  ? jobStatusLabel(selectedStatus)
                  : "Не назначена"}
            </span>
            <dl className="job-properties">
              <dt>Окно начала</dt>
              <dd>
                {hm(selectedJob.window_start)}-{hm(selectedJob.window_end)}
              </dd>
              <dt>Длительность</dt>
              <dd>{selectedJob.duration_minutes} мин</dd>
              <dt>Участок</dt>
              <dd>{selectedJob.service_area}</dd>
              {selectedJob.district ? (
                <>
                  <dt>Район в исходных данных</dt>
                  <dd>{selectedJob.district}</dd>
                </>
              ) : null}
              {selectedJob.source_status ? (
                <>
                  <dt>Статус BK в исходном CSV</dt>
                  <dd>{selectedJob.source_status} · справочно</dd>
                </>
              ) : null}
              <dt>Навык</dt>
              <dd>{skills[selectedJob.required_skill]}</dd>
              <dt>Транспорт</dt>
              <dd>
                {selectedJob.required_transport
                  ? transports[selectedJob.required_transport]
                  : "Любой"}
              </dd>
              <dt>Приоритет</dt>
              <dd>{jobPriorityLabel(selectedJob)}</dd>
              <dt>Координаты</dt>
              <dd>
                {selectedJob.location
                  ? `${selectedJob.location.latitude.toFixed(5)}, ${selectedJob.location.longitude.toFixed(5)}`
                  : "Не заданы"}
              </dd>
            </dl>
            <p>
              Оборудование:{" "}
              {[
                ...new Set([
                  ...selectedJob.required_equipment,
                  ...(shown?.settings.equipment_enabled
                    ? shown.settings.equipment_by_work_type[
                        selectedJob.work_type
                      ] ||
                      shown.settings.equipment_by_work_type[
                        selectedJob.bk_type
                      ] ||
                      []
                    : []),
                ]),
              ].join(", ") || "Не требуется"}
            </p>
            {selectedStop ? (
              <p className="calculation-note">
                До визита: {selectedStop.travel_minutes} мин в пути
                {selectedStop.waiting_minutes
                  ? ` + ${selectedStop.waiting_minutes} мин ожидания`
                  : ""}
                . Работа: {selectedJob.duration_minutes} мин
                {shown?.settings.normative_travel_mode === "included"
                  ? ", включая 20 минут нормативного запаса на дорогу и доступ к объекту."
                  : ". Фиксированные 20 минут исключены; дорога рассчитана отдельно."}
              </p>
            ) : null}
            {selectedJob.sla_deadline !== null ? (
              <p className={`sla ${selectedStop?.sla_status || ""}`}>
                Срок SLA: {hm(selectedJob.sla_deadline)} ·{" "}
                {selectedStop?.sla_status
                  ? `${{ late: "Опоздание", risk: "Риск опоздания", ok: "В пределах срока" }[selectedStop.sla_status]}, запас ${selectedStop.sla_slack_minutes} мин`
                  : "Прогноз появится при включённом SLA после расчёта"}
              </p>
            ) : null}
            {selectedStop?.locked ? (
              <p>Назначение зафиксировано вручную.</p>
            ) : null}
            {plan ? (
              <button
                className="secondary full"
                disabled={!!busy}
                onClick={() => {
                  setManualJob(selectedJob.id);
                  setSelected(null);
                }}
              >
                Назначить вручную
              </button>
            ) : null}
            <h3>
              {selectedStop ? "Почему это назначение" : "Причина неназначения"}
            </h3>
            {selectedStop ? (
              <>
                <p>
                  <strong>
                    {
                      shown?.engineers.find(
                        (e) => e.id === selectedStop.engineer_id,
                      )?.name
                    }
                  </strong>
                  <br />
                  {hm(selectedStop.start)}-{hm(selectedStop.finish)}
                </p>
                <ul className="explanations">
                  {selectedStop.explanation.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </>
            ) : (
              <>
                <ul className="explanations reasons">
                  {(
                    reasons.get(selectedJob.id)?.reasons || [
                      "План ещё не построен",
                    ]
                  ).map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
                {reasons.get(selectedJob.id) ? (
                  <div className="assignment-help">
                    <strong>Что можно проверить</strong>
                    <p>{unassignedAdvice(reasons.get(selectedJob.id)!.code)}</p>
                    {reasons.get(selectedJob.id)!.code === "search_limit" ? (
                      <button
                        className="secondary"
                        onClick={() => {
                          setSelected(null);
                          setTab("compare");
                        }}
                      >
                        Открыть варианты расчёта
                      </button>
                    ) : reasons.get(selectedJob.id)!.code === "resources" ? (
                      <button
                        className="secondary"
                        onClick={() => {
                          setSelected(null);
                          setShowEngineers(true);
                          setTab("data");
                        }}
                      >
                        Проверить профили инженеров
                      </button>
                    ) : (
                      <button
                        className="secondary"
                        onClick={() => {
                          setSelected(null);
                          setTab("events");
                          setEventType("reschedule");
                          setEventTarget(selectedJob.id);
                          setEventWindowStart(hm(selectedJob.window_start));
                          setEventWindowEnd(hm(selectedJob.window_end));
                        }}
                      >
                        Проверить новое окно клиента
                      </button>
                    )}
                    {reasons.get(selectedJob.id)!.evidence.length ? (
                      <details>
                        <summary>Проверка по инженерам</summary>
                        <ul>
                          {reasons
                            .get(selectedJob.id)!
                            .evidence.map((item, index) => (
                              <li key={index}>
                                {shown?.engineers.find(
                                  (engineer) =>
                                    engineer.id === item.engineer_id,
                                )?.name || String(item.engineer_id)}
                                : {evidenceText(item)}
                              </li>
                            ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
            <details className="provenance">
              <summary>Происхождение полей</summary>
              {Object.entries(selectedJob.provenance).map(([key, value]) => (
                <div key={key}>
                  <code>{key}</code>
                  <span>
                    {{
                      provided: "Из CSV",
                      computed: "Вычислено",
                      configured: "Настройка",
                      synthetic: "Демо-данные",
                    }[value] || value}
                  </span>
                </div>
              ))}
            </details>
          </aside>
        </div>
      ) : null}
      {editJob ? (
        <Modal
          title={
            jobEventType === "urgent"
              ? "Новая срочная заявка"
              : jobEventType === "new"
                ? "Новая обычная заявка"
                : `Изменить заявку ${editJob.source_id}`
          }
          close={() => {
            setEditJob(null);
            setJobEventType(null);
          }}
          error={error}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              work("Сохраняем заявку…", async () => {
                if (jobEventType && plan) {
                  const isPreview = jobEventType === "urgent";
                  const result = await api<Plan>(
                    `/plans/${plan.id}/events${isPreview ? "/preview" : ""}`,
                    json({
                      type: jobEventType,
                      time: minutes(eventTime),
                      job: editJob,
                    }),
                  );
                  if (isPreview) {
                    setPreviewPlan(result);
                    setNotice(
                      "Черновик рассчитан. Проверьте изменения и подтвердите план.",
                    );
                  } else {
                    setBefore(plan);
                    setPlan(result);
                    setPreviewPlan(null);
                    setNotice(
                      `Версия ${result.version} готова. Изменений: ${result.changes.length}.`,
                    );
                    await refreshHistory(result.dataset_id);
                  }
                } else
                  await savePatch({
                    jobs: ds?.jobs.map((j) =>
                      j.id === editJob.id ? editJob : j,
                    ),
                  });
                setEditJob(null);
                setJobEventType(null);
              });
            }}
          >
            {jobEventType === "new" ? (
              <label>
                Тип заявки
                <select
                  value={editJob.work_type}
                  onChange={(e) => {
                    const kind = e.target.value;
                    setEditJob({
                      ...editJob,
                      work_type: kind,
                      bk_type: kind,
                      required_skill:
                        kind === "Локальная заявка" ? "local" : "connection",
                      duration_minutes:
                        ds?.settings.normative_service_durations[kind] || 30,
                    });
                  }}
                >
                  <option value="Локальная заявка">Локальная заявка</option>
                  <option value="Подключение">Подключение</option>
                  <option value="Дозаказ">Дозаказ</option>
                </select>
              </label>
            ) : null}
            <label>
              Адрес
              <input
                required
                value={editJob.address}
                onChange={(e) => {
                  setEditJob({
                    ...editJob,
                    address: e.target.value,
                    location: null,
                    geo_quality: "missing",
                    geo_note:
                      "Адрес изменён. Укажите координаты нового адреса.",
                  });
                  setJobCoordinates({ latitude: "", longitude: "" });
                }}
              />
            </label>
            <div className="form-row">
              <label>
                Начало окна
                <input
                  type="time"
                  value={hm(editJob.window_start)}
                  onChange={(e) =>
                    setEditJob({
                      ...editJob,
                      window_start: minutes(e.target.value),
                    })
                  }
                />
              </label>
              <label>
                Конец окна
                <input
                  type="time"
                  value={hm(editJob.window_end)}
                  onChange={(e) =>
                    setEditJob({
                      ...editJob,
                      window_end: minutes(e.target.value),
                    })
                  }
                />
              </label>
            </div>
            <label>
              Длительность, минут
              <input
                type="number"
                min="1"
                max="1440"
                value={editJob.duration_minutes}
                onChange={(e) =>
                  setEditJob({
                    ...editJob,
                    duration_minutes: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Требуемый навык
              <select
                value={editJob.required_skill}
                onChange={(e) =>
                  setEditJob({
                    ...editJob,
                    required_skill: e.target.value as Skill,
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
            <label>
              Транспорт
              <select
                value={editJob.required_transport || ""}
                onChange={(e) =>
                  setEditJob({
                    ...editJob,
                    required_transport: (e.target.value as Transport) || null,
                  })
                }
              >
                <option value="">Любой</option>
                {Object.entries(transports).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            {!editJob.location ? (
              <p className="form-hint" role="status">
                Укажите широту и долготу объекта. Без них маршрут нельзя
                рассчитать.
              </p>
            ) : null}
            <div className="form-row">
              {(["latitude", "longitude"] as const).map((key) => (
                <label key={key}>
                  {key === "latitude" ? "Широта" : "Долгота"}
                  <input
                    type="number"
                    step="any"
                    required
                    min={key === "latitude" ? -90 : -180}
                    max={key === "latitude" ? 90 : 180}
                    value={jobCoordinates[key]}
                    onChange={(e) => changeJobCoordinate(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
            <ExtraJobFields
              job={editJob}
              onChange={setEditJob}
              showPriority={!jobEventType}
            />
            <button className="primary full" disabled={!!busy}>
              {jobEventType === "urgent"
                ? "Добавить и перепланировать"
                : jobEventType === "new"
                  ? "Попробовать вставить в план"
                  : "Сохранить заявку"}
            </button>
          </form>
        </Modal>
      ) : null}
      {editor ? (
        <Modal title={editor.title} close={() => setEditor(null)} error={error}>
          <p>
            Изменения сохраняются в нормализованных данных. Профиль инженера:
            навыки, транспорт, смена, стартовая точка и оборудование.
          </p>
          <textarea
            className="json-editor"
            aria-label="JSON редактор"
            value={editor.value}
            onChange={(e) => setEditor({ ...editor, value: e.target.value })}
          />
          <button
            className="primary full"
            disabled={!!busy}
            onClick={() =>
              work("Проверяем изменения…", async () => {
                const parsed = JSON.parse(editor.value);
                await savePatch(
                  editor.kind === "engineers"
                    ? { engineers: parsed }
                    : editor.kind === "settings"
                      ? { settings: parsed, apply_defaults: true }
                      : parsed,
                );
                setEditor(null);
              })
            }
          >
            Проверить и сохранить
          </button>
        </Modal>
      ) : null}
      {editEngineer && ds ? (
        <Modal
          title="Профиль инженера"
          error={error}
          close={() => setEditEngineer(null)}
        >
          <EngineerForm
            value={editEngineer}
            onChange={setEditEngineer}
            busy={!!busy}
            onSave={() =>
              work("Сохраняем профиль…", async () => {
                await savePatch({
                  engineers: ds.engineers.some((e) => e.id === editEngineer.id)
                    ? ds.engineers.map((e) =>
                        e.id === editEngineer.id ? editEngineer : e,
                      )
                    : [...ds.engineers, editEngineer],
                });
                setEditEngineer(null);
              })
            }
          />
        </Modal>
      ) : null}
      {manualJob && plan ? (
        <Modal
          title="Ручное назначение"
          error={error}
          close={() => setManualJob(null)}
        >
          <ManualForm
            plan={plan}
            jobId={manualJob}
            eventTime={minutes(eventTime)}
            busy={!!busy}
            onSave={(body) =>
              work("Проверяем ручное назначение…", async () => {
                const result = await api<Plan>(
                  `/plans/${plan.id}/manual`,
                  json(body),
                );
                setBefore(plan);
                setPlan(result);
                setManualJob(null);
                setNotice(
                  `Ручное назначение проверено. Версия ${result.version} сохранена.`,
                );
                await refreshHistory(result.dataset_id);
              })
            }
          />
        </Modal>
      ) : null}
      {importOpen ? (
        <Modal
          title="Импорт данных"
          error={error}
          close={() => setImportOpen(false)}
        >
          <p>
            CSV исходного формата или JSON набора/экспорта. Максимум 5 МБ.
            Исходный файл сохранится без изменений.
          </p>
          <label>
            Участок для нового CSV
            <input
              value={importRegion}
              onChange={(e) => setImportRegion(e.target.value)}
              placeholder="Например, Восток"
            />
          </label>
          <p>
            Для CSV участок обязателен: его нет в файле, а заявки другого
            участка нельзя назначить вашим инженерам. Для JSON поле не нужно.
          </p>
          <label>
            Кодировка
            <select
              value={encoding}
              onChange={(e) => setEncoding(e.target.value)}
            >
              <option value="">Автоматически</option>
              <option value="utf-8-sig">UTF-8 / UTF-8 BOM</option>
              <option value="cp1251">Windows-1251</option>
            </select>
          </label>
          <label>
            Разделитель
            <select
              value={delimiter}
              onChange={(e) => setDelimiter(e.target.value)}
            >
              <option value="">Автоматически</option>
              <option value=";">Точка с запятой (;)</option>
              <option value=",">Запятая (,)</option>
            </select>
          </label>
          <p>
            Для нового CSV добавьте инженеров и проверенные координаты через
            форму после импорта. Статусы BK из файла сохраняются для справки и
            сами по себе не исключают заявки из моделируемого дня.
          </p>
          <button
            className="primary full"
            disabled={!!busy}
            onClick={() => upload.current?.click()}
          >
            Выбрать CSV или JSON
          </button>
        </Modal>
      ) : null}
    </div>
  );
}

function Metric({
  Icon,
  tone,
  label,
  value,
  suffix,
  foot,
}: {
  Icon: LucideIcon;
  tone: "yellow" | "green" | "violet" | "blue";
  label: string;
  value: string;
  suffix: string;
  foot: string;
}) {
  return (
    <div className={`metric metric-${tone}`}>
      <div className="metric-head">
        <div className="metric-label">{label}</div>
        <span className="metric-icon" aria-hidden="true">
          <Icon />
        </span>
      </div>
      <div className="metric-value">
        {value}
        <span>{suffix}</span>
      </div>
      <div className="metric-foot">{foot}</div>
    </div>
  );
}
function deltaText(after: number, before: number, unit: string) {
  const d = after - before;
  return `${d > 0 ? "+" : d < 0 ? "−" : ""}${unit === "км" ? km(Math.abs(d)) : Math.abs(d)} ${unit}${d < 0 ? " к базовому" : ""}`;
}
function EmptyPlan({
  text = "Нажмите «Построить планы», чтобы получить маршруты и расписание.",
}: {
  text?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-icon" aria-hidden="true">
        <MapPinned />
      </span>
      <h2>Рабочий день ещё не спланирован</h2>
      <p>{text}</p>
    </div>
  );
}
function describeAssignment(a: Assignment | null, engineers: Engineer[]) {
  const status = a?.status ? ` · ${jobStatusLabel(a.status)}` : "";
  return a
    ? `${engineers.find((e) => e.id === a.engineer_id)?.name || a.engineer_id}, ${hm(a.start)}, №${a.position + 1}${status}`
    : "Без назначения";
}
function currentJobStatus(
  plan: Plan | null,
  jobId: string,
  fallback?: JobStatus,
): JobStatus {
  return plan?.job_states?.[jobId]?.status || fallback || "unassigned";
}
function jobStatusLabel(status?: JobStatus) {
  return (
    {
      unassigned: "Не назначена",
      sent: "Отправлена",
      en_route: "В пути",
      in_progress: "Выполнение",
      completed: "Завершена",
    }[status || "unassigned"] || "Не назначена"
  );
}
function jobPriorityLabel(job: Job) {
  if (job.work_type.trim().toLocaleLowerCase("ru") === "авария") {
    return "1 · Авария";
  }
  if (job.priority === "urgent") {
    return "1 · Срочная";
  }
  if (job.bk_type === "Подключение") {
    return "2 · Подключение";
  }
  return "3 · Остальные работы";
}
function eventHistoryLabel(event: NonNullable<Plan["event"]>) {
  if (event.type === "status" && event.new_status) {
    return `Статус: ${jobStatusLabel(event.new_status as JobStatus)}`;
  }
  return (
    {
      new: "Новая обычная заявка",
      urgent: "Срочная заявка",
      complete: "Завершение",
      cancel: "Отмена",
      reschedule: "Перенос окна",
      unavailable: "Недоступность",
      manual: "Ручное назначение",
    }[event.type] || "Изменение дня"
  );
}
function unassignedAdvice(code: string) {
  switch (code) {
    case "resources":
      return "Проверьте участок, навык, транспорт, дневной комплект и состав рабочего дня. Инженера без первоначальных назначений можно вызвать только отдельно, с подтверждением. Изменяйте профиль только если ресурс действительно доступен.";
    case "time":
      return "Согласуйте с клиентом другое окно или проверьте смену инженера. Доступность после изменения нужно пересчитать.";
    case "search_limit":
      return "Допустимое место в маршруте найдено. Попробуйте тщательный расчёт или ручное назначение.";
    default:
      return "Подходящие инженеры заняты в текущих маршрутах. Проверьте другое окно или дополнительные ресурсы; результат не гарантирован.";
  }
}

function evidenceText(item: Record<string, unknown>) {
  if (Array.isArray(item.reasons)) {
    return item.reasons.length ? item.reasons.join("; ") : "ресурсы подходят";
  }
  if (typeof item.position === "number")
    return `допустимая вставка после ${item.position} работ`;
  if (typeof item.scheduled_jobs === "number")
    return `${item.scheduled_jobs} работ в текущем маршруте`;
  if (
    typeof item.available_from === "number" &&
    typeof item.shift_end === "number"
  ) {
    return `доступен с ${hm(item.available_from)} до ${hm(item.shift_end)}`;
  }
  return "проверьте ограничения маршрута";
}

function Modal({
  title,
  close,
  children,
  error,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
  error?: string;
}) {
  return (
    <div className="modal-backdrop">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <button className="close" onClick={close} aria-label="Закрыть редактор">
          ×
        </button>
        <h2>{title}</h2>
        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}
        {children}
      </section>
    </div>
  );
}
