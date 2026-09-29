export type Location = { latitude: number; longitude: number };
export type Skill = "local" | "connection" | "emergency";
export type Transport = "car" | "walk" | "bicycle" | "public";
export type Job = {
  id: string;
  source_id: string;
  source_line: number;
  address: string;
  raw_address: string;
  source_status?: string;
  district: string;
  service_area: string;
  location: Location | null;
  geo_quality: string;
  geo_note: string;
  work_type: string;
  bk_type: string;
  window_start: number;
  window_end: number;
  duration_minutes: number;
  required_skill: Skill;
  required_transport: Transport | null;
  required_equipment: string[];
  priority: "normal" | "urgent";
  sla_deadline: number | null;
  provenance: Record<string, string>;
};
export type Engineer = {
  id: string;
  name: string;
  service_area: string;
  start_location: Location | null;
  start_mode: "office" | "home" | "custom";
  start_address: string;
  shift_start: number;
  shift_end: number;
  skills: Skill[];
  transport: Transport;
  equipment: string[];
  available: boolean;
  unavailable_from: number | null;
  provenance: Record<string, string>;
};
export type Settings = {
  requirements_version: number;
  seed: number;
  time_limit_seconds: number;
  solution_limit: number;
  road_factor: number;
  speeds_kmh: Record<Transport, number>;
  shift_start: number;
  shift_end: number;
  durations: Record<string, number>;
  normative_durations: Record<string, number>;
  normative_service_durations: Record<string, number>;
  normative_travel_mode: "included" | "separate";
  skill_mapping: Record<string, Skill>;
  routing_provider: "estimate" | "osrm";
  equipment_enabled: boolean;
  equipment_catalog: string[];
  equipment_by_skill: Record<Skill, string[]>;
  equipment_by_work_type: Record<string, string[]>;
  sla_enabled: boolean;
  sla_basis: "start" | "finish";
  sla_penalty: number;
  sla_risk_buffer: number;
  change_penalty: number;
  transport_demo_enabled: boolean;
  demo_event_time: number;
  demo_urgent_duration: number;
  demo_urgent_window: number;
};
export type Issue = {
  severity: "error" | "warning";
  row: number;
  field: string;
  value: string;
  message: string;
  suggestion: string;
};
export type Dataset = {
  id: string;
  name: string;
  region: string;
  date: string;
  timezone: string;
  revision: number;
  jobs: Job[];
  engineers: Engineer[];
  office_address: string;
  office_location: Location | null;
  office_geo_quality: string;
  office_geo_note: string;
  settings: Settings;
  issues: Issue[];
  validation?: Issue[];
  source_files: string[];
  historical: Record<string, string>[];
};
export type Summary = Pick<
  Dataset,
  "id" | "name" | "region" | "date" | "revision"
> & { jobs_count: number; engineers_count: number };
export type Stop = {
  job_id: string;
  engineer_id: string;
  arrival: number;
  start: number;
  finish: number;
  departure: number;
  travel_minutes: number;
  distance_m: number;
  waiting_minutes: number;
  explanation: string[];
  locked: boolean;
  sla_status?: "late" | "risk" | "ok";
  sla_slack_minutes?: number;
  status?: JobStatus;
  started_at?: number;
  completed_at?: number;
};
export type JobStatus =
  "unassigned" | "sent" | "en_route" | "in_progress" | "completed";
export type JobState = {
  status: JobStatus;
  updated_at: number | null;
  started_at?: number;
  completed_at?: number;
};
export type Leg = {
  from: Location;
  to: Location;
  departure: number;
  arrival: number;
  distance_m: number;
  job_id: string;
  partial?: boolean;
};
export type Route = {
  engineer_id: string;
  engineer_name: string;
  transport: Transport;
  stops: Stop[];
  legs: Leg[];
  distance_m: number;
  travel_minutes: number;
  work_minutes: number;
  waiting_minutes: number;
  frozen_count: number;
  anchor: { location: Location; time: number };
};
export type Metrics = {
  sla_late?: number;
  sla_risk?: number;
  assigned: number;
  unassigned: number;
  total: number;
  urgent_assigned: number;
  accident_assigned?: number;
  connection_assigned?: number;
  engineers_used: number;
  distance_m: number;
  travel_minutes: number;
  work_minutes: number;
};
export type RegionReport = {
  generated_at: string;
  code_sha256: Record<string, string>;
  note: string;
  regions: {
    dataset_id: string;
    name: string;
    region: string;
    jobs: number;
    engineers: number;
    source_file: string;
    source_sha256: string;
    raw_input_file: string;
    raw_input_sha256: string;
    settings: {
      seed: number;
      time_limit_seconds: number;
      solution_limit: number;
      routing_provider: string;
    };
    baseline: { metrics: Metrics; status: string; calculation_seconds: number };
    optimized: {
      metrics: Metrics;
      status: string;
      calculation_seconds: number;
    };
  }[];
};
export type Assignment = {
  engineer_id: string;
  start: number;
  position: number;
  status?: JobStatus;
};
export type Change = {
  job_id: string;
  kind: string;
  before: Assignment | null;
  after: Assignment | null;
};
export type Plan = {
  id: string;
  dataset_id: string;
  dataset_revision: number;
  mode: string;
  version: number;
  parent_id: string | null;
  status: string;
  search_seconds: number;
  calculation_seconds: number;
  routing_method: string;
  routing_notice: string;
  snapshot: Dataset;
  routes: Route[];
  working_engineer_ids?: string[];
  unassigned: {
    job_id: string;
    code: string;
    reasons: string[];
    evidence: Record<string, unknown>[];
  }[];
  metrics: Metrics;
  event: {
    type: string;
    time: number;
    notice?: string;
    inserted?: boolean;
    job?: Job;
    previous_status?: JobStatus;
    new_status?: JobStatus | "cancelled";
  } | null;
  changes: Change[];
  locks: Record<string, unknown>;
  job_states: Record<string, JobState>;
  cached?: boolean;
};
export function workingEngineerIds(plan: Plan): Set<string> {
  return new Set(
    plan.working_engineer_ids ??
      plan.routes
        .filter((route) => route.stops.length || route.legs.length)
        .map((route) => route.engineer_id),
  );
}
export const skills: Record<Skill, string> = {
  local: "Локальные работы",
  connection: "Подключение и дозаказы",
  emergency: "Глобальные проблемы",
};
export const transports: Record<Transport, string> = {
  car: "Автомобиль",
  walk: "Пешком",
  bicycle: "Велосипед",
  public: "Общ. транспорт",
};
export const colors = [
  "#237666",
  "#965d24",
  "#3e6eac",
  "#944468",
  "#626522",
  "#815cad",
  "#9b4634",
  "#23727a",
  "#76614e",
  "#4f619d",
  "#806e20",
  "#53664c",
];
export const hm = (n: number) =>
  `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
export const minutes = (s: string) => {
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
};
export const km = (n: number) =>
  (n / 1000).toLocaleString("ru-RU", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new Error(
      "Нет связи с сервисом. Проверьте соединение и повторите действие.",
    );
  }
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "Сервис временно недоступен" }));
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || JSON.stringify(detail),
    );
  }
  return response.json();
}
export const json = (body: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
