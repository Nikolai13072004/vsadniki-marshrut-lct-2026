from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Skill = Literal["local", "connection", "emergency"]
Transport = Literal["car", "walk", "bicycle", "public"]
Origin = Literal["provided", "computed", "configured", "synthetic"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Location(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Job(Model):
    id: str = Field(min_length=1, max_length=150)
    source_id: str = ""
    source_line: int = 0
    address: str = Field(min_length=1, max_length=500)
    raw_address: str = ""
    source_status: str = ""
    district: str = ""
    service_area: str = ""
    location: Location | None = None
    geo_quality: str = "missing"
    geo_note: str = ""
    work_type: str = Field(min_length=1, max_length=150)
    bk_type: str = ""
    window_start: int = Field(ge=0, le=1439)
    window_end: int = Field(ge=0, le=1439)
    duration_minutes: int = Field(ge=1, le=1440)
    required_skill: Skill
    required_transport: Transport | None = None
    required_equipment: list[str] = Field(default_factory=list, max_length=30)
    priority: Literal["normal", "urgent"] = "normal"
    sla_deadline: int | None = Field(default=None, ge=0, le=1439)
    provenance: dict[str, Origin] = Field(default_factory=dict)
    manual_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_window(self):
        if self.window_end < self.window_start:
            raise ValueError("Конец окна раньше начала")
        return self


class Engineer(Model):
    id: str = Field(min_length=1, max_length=150)
    name: str = Field(min_length=1, max_length=150)
    service_area: str = ""
    start_location: Location | None
    start_mode: Literal["office", "home", "custom"] = "office"
    start_address: str = ""
    shift_start: int = Field(default=540, ge=0, le=1439)
    shift_end: int = Field(default=1320, ge=1, le=1440)
    skills: list[Skill] = Field(min_length=1, max_length=3)
    transport: Transport = "car"
    equipment: list[str] = Field(default_factory=list, max_length=30)
    available: bool = True
    unavailable_from: int | None = Field(default=None, ge=0, le=1440)
    provenance: dict[str, Origin] = Field(default_factory=dict)
    manual_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_shift(self):
        if self.shift_end <= self.shift_start or len(set(self.skills)) != len(self.skills):
            raise ValueError("Проверьте смену и уникальность навыков")
        return self


class Settings(Model):
    requirements_version: int = Field(default=8, ge=1)
    seed: int = Field(default=2026, ge=0, le=2147483647)
    time_limit_seconds: int = Field(default=15, ge=1, le=25)
    solution_limit: int = Field(default=80, ge=1, le=1000)
    road_factor: float = Field(default=1.3, ge=1, le=3)
    speeds_kmh: dict[Transport, float] = Field(
        default_factory=lambda: {"car": 30, "walk": 5, "bicycle": 15, "public": 20}
    )
    shift_start: int = Field(default=540, ge=0, le=1439)
    shift_end: int = Field(default=1320, ge=1, le=1440)
    durations: dict[str, int] = Field(default_factory=dict)
    normative_durations: dict[str, int] = Field(
        default_factory=lambda: {
            "Подключение": 90,
            "Глобальная проблема": 100,
            "Дозаказ": 40,
            "Локальная заявка": 50,
        }
    )
    normative_service_durations: dict[str, int] = Field(
        default_factory=lambda: {
            "Подключение": 70,
            "Глобальная проблема": 80,
            "Дозаказ": 20,
            "Локальная заявка": 30,
        }
    )
    normative_travel_mode: Literal["included", "separate"] = "separate"
    skill_mapping: dict[str, Skill] = Field(
        default_factory=lambda: {
            "Локальная заявка": "local",
            "Подключение": "connection",
            "Дозаказ": "connection",
            "Глобальная проблема": "emergency",
        }
    )
    routing_provider: Literal["estimate", "osrm"] = "estimate"
    equipment_enabled: bool = False
    equipment_catalog: list[str] = Field(
        default_factory=lambda: ["Тестер линии", "Роутер", "Приставка", "Кабельный комплект"]
    )
    equipment_by_skill: dict[Skill, list[str]] = Field(
        default_factory=lambda: {
            "local": ["Тестер линии"],
            "connection": ["Роутер", "Кабельный комплект"],
            "emergency": ["Тестер линии", "Кабельный комплект"],
        }
    )
    equipment_by_work_type: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "Подключение": ["Роутер", "Кабельный комплект"],
            "Глобальная проблема": ["Тестер линии", "Кабельный комплект"],
            "Дозаказ": ["Роутер"],
            "Локальная заявка": ["Тестер линии"],
        }
    )
    sla_enabled: bool = False
    sla_basis: Literal["start", "finish"] = "start"
    sla_penalty: int = Field(default=1, ge=0, le=100)
    sla_risk_buffer: int = Field(default=15, ge=0, le=240)
    change_penalty: int = Field(default=1, ge=0, le=100)
    transport_demo_enabled: bool = True
    demo_event_time: int = Field(default=780, ge=0, le=1439)
    demo_urgent_duration: int = Field(default=80, ge=1, le=240)
    demo_urgent_window: int = Field(default=120, ge=15, le=600)

    @model_validator(mode="after")
    def valid_settings(self):
        if self.shift_end <= self.shift_start:
            raise ValueError("Некорректная смена")
        if set(self.speeds_kmh) != {"car", "walk", "bicycle", "public"} or any(
            not 1 <= x <= 150 for x in self.speeds_kmh.values()
        ):
            raise ValueError("Нужны скорости всех четырёх видов транспорта от 1 до 150 км/ч")
        if any(
            not 1 <= x <= 1440
            for x in [
                *self.durations.values(),
                *self.normative_durations.values(),
                *self.normative_service_durations.values(),
            ]
        ):
            raise ValueError("Длительность должна быть от 1 до 1440 минут")
        catalog = set(self.equipment_catalog)
        if any(
            not set(items) <= catalog
            for items in [*self.equipment_by_skill.values(), *self.equipment_by_work_type.values()]
        ):
            raise ValueError("Матрица оборудования ссылается на отсутствующий элемент каталога")
        return self


class Issue(Model):
    severity: Literal["error", "warning"]
    row: int = 0
    field: str = ""
    value: str = ""
    message: str
    suggestion: str = ""


class Dataset(Model):
    id: str
    name: str
    region: str
    date: str = "2026-08-17"
    timezone: str = "Europe/Moscow"
    revision: int = 1
    jobs: list[Job] = Field(default_factory=list, max_length=150)
    engineers: list[Engineer] = Field(default_factory=list, max_length=15)
    office_address: str = ""
    office_location: Location | None = None
    office_geo_quality: str = "missing"
    office_geo_note: str = ""
    settings: Settings = Field(default_factory=Settings)
    issues: list[Issue] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    historical: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        for record in [*self.jobs, *self.engineers]:
            record.service_area = record.service_area.strip() or self.region.strip()
        for records in (self.jobs, self.engineers):
            if len({r.id for r in records}) != len(records):
                raise ValueError("Внутренние идентификаторы должны быть уникальными")
        return self


class PlanRequest(Model):
    dataset_id: str
    settings: Settings | None = None
    variant: Literal["standard", "thorough"] = "standard"


class EventRequest(Model):
    type: Literal["new", "urgent", "cancel", "complete", "status", "reschedule", "unavailable"]
    time: int = Field(ge=0, le=1439)
    job_id: str | None = None
    engineer_id: str | None = None
    job: Job | None = None
    demo: bool = False
    window_start: int | None = Field(default=None, ge=0, le=1439)
    window_end: int | None = Field(default=None, ge=0, le=1439)
    job_status: Literal["en_route", "in_progress"] | None = None

    @model_validator(mode="after")
    def valid_reschedule(self):
        if self.type == "reschedule":
            if self.window_start is None or self.window_end is None:
                raise ValueError("Для переноса укажите новое временное окно")
            if self.window_end < self.window_start:
                raise ValueError("Конец нового окна раньше начала")
        if self.type == "status" and self.job_status is None:
            raise ValueError("Для изменения статуса укажите новое состояние")
        return self


class PreviewConfirmRequest(Model):
    preview_id: str


class ManualRequest(Model):
    job_id: str
    engineer_id: str
    time: int = Field(ge=0, le=1439)
    position: int = Field(default=0, ge=0, le=150)
    lock: bool = True
    activate_engineer: bool = False


class DatasetPatch(Model):
    revision: int
    jobs: list[Job] | None = None
    engineers: list[Engineer] | None = None
    settings: Settings | None = None
    apply_defaults: bool = False
    issues: list[Issue] | None = None
