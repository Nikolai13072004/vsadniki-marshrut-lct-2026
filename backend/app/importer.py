import csv
import hashlib
import io
import re
import uuid
from datetime import datetime

from .models import Dataset, Engineer, Issue, Job, Location, Settings

SKILL_LABELS = {
    "local": "Локальные работы",
    "connection": "Подключение и дозаказы",
    "emergency": "Глобальные проблемы",
}
TRANSPORT_LABELS = {
    "car": "Автомобиль",
    "walk": "Пешком",
    "bicycle": "Велосипед",
    "public": "Общественный транспорт",
}


def defaults():
    settings = Settings()
    for names, duration in [
        (["Информация", "Мониторинг"], 30),
        (
            [
                "Нет линка",
                "Разрывы",
                "Низкая скорость",
                "Рост ошибок на порту",
                "IP-адрес 169...",
                "TVE/ENT. Другие ошибки",
            ],
            45,
        ),
        (["Конвергенция абонента", "Переключение на Гбит/с"], 60),
        (
            [
                "Заявка на подключение",
                "Заказ подключения/Дозаказ оборудования",
                "Дозаказ оборудования",
                "Работа с кабелем",
                "Роутер. Замена техническим специалистом",
                "TVE/ENT. Замена приставки техником",
                "ТВ. Замена приставки техником",
                "Авария",
            ],
            90,
        ),
    ]:
        settings.durations.update(dict.fromkeys(names, duration))
    return settings


def configured_duration(settings, bk_type, work_type):
    """Return the configured BK norm, retaining the older HD fallback for imports."""
    if settings.normative_travel_mode == "separate":
        if bk_type in settings.normative_service_durations:
            return settings.normative_service_durations[bk_type]
    elif bk_type in settings.normative_durations:
        return settings.normative_durations[bk_type]
    return settings.durations[work_type]


def is_emergency(work_type):
    """The HD request type, not the BK category, identifies an accident."""
    return work_type.strip().casefold() == "авария"


def configured_priority(bk_type, work_type):
    return "urgent" if is_emergency(work_type) else "normal"


def normalize_address(value):
    value = re.sub(r",?\s*кв\.?\s*\d+.*$", "", value, flags=re.I)
    value = re.sub(r"(?:г\.?\s*)?Город\s+Москва", "Москва", value, flags=re.I)
    for pattern, replacement in [
        (r"\bул\.", "улица "),
        (r"\bпр-кт\.", "проспект "),
        (r"\bпер\.", "переулок "),
        (r"\bнаб\.", "набережная "),
        (r"\bб-р\.", "бульвар "),
        (r"\bш\.", "шоссе "),
        (r"\bпроезд\.", "проезд "),
        (r"\bд\.\s*", "дом "),
    ]:
        value = re.sub(pattern, replacement, value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def decode_csv(raw: bytes, encoding=None, delimiter=None):
    if b"\x00" in raw:
        raise ValueError("Файл содержит бинарные данные; загрузите CSV в UTF-8 или CP1251")
    if encoding not in (None, "utf-8", "utf-8-sig", "cp1251") or delimiter not in (None, ";", ","):
        raise ValueError("Выберите UTF-8/CP1251 и разделитель ; или ,")
    text = None
    for candidate in [encoding] if encoding else ["utf-8-sig", "cp1251"]:
        try:
            text = raw.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Не удалось определить кодировку; выберите её вручную")
    if delimiter is None:
        first = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        rows.append((reader.line_num, row))
    return rows, reader.fieldnames or [], encoding, delimiter


def parse_minutes(value):
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt.hour * 60 + dt.minute, dt.strftime("%Y-%m-%d") if fmt != "%H:%M" else None
        except ValueError:
            pass
    raise ValueError("Ожидается ДД.ММ.ГГГГ ЧЧ:ММ или ЧЧ:ММ")


def import_csv(raw, name, region, geo=None, settings=None, encoding=None, delimiter=None):
    settings = settings or defaults()
    geo = geo or {}
    rows, headers, enc, sep = decode_csv(raw, encoding, delimiter)
    dataset_id = str(uuid.uuid4())
    ds = Dataset(id=dataset_id, name=name, region=region, settings=settings, source_files=[name])
    required = ["Заявка", "Тип заявки BK", "Тип заявки HD", "Начало", "Окончание", "Адрес"]
    missing = [field for field in required if field not in headers]
    if missing:
        ds.issues = [
            Issue(
                severity="error",
                row=1,
                field=f,
                message="Нет обязательного столбца",
                suggestion="Добавьте столбец или выберите правильный разделитель",
            )
            for f in missing
        ]
        return ds
    seen = set()
    dates = set()
    historical_statuses = {"Выполнена": 0, "Отменена": 0}
    for number, row in rows:
        if all(not str(value or "").strip() for value in row.values()):
            continue
        if (row.get("Заявка") or "").strip().lower() == "адрес офиса":
            ds.office_address = normalize_address(row.get("Тип заявки BK") or "")
            entry = geo.get(ds.office_address)
            ds.office_location = Location(**entry["location"]) if entry and entry.get("location") else None
            ds.office_geo_quality = entry.get("quality", "missing") if entry else "missing"
            ds.office_geo_note = entry.get("note", "") if entry else ""
            continue
        bad = [f for f in required if not (row.get(f) or "").strip()]
        if None in row or bad:
            ds.issues.append(
                Issue(
                    severity="error",
                    row=number,
                    field=", ".join(bad),
                    message="Некорректная строка CSV",
                    suggestion="Заполните поля и проверьте число колонок",
                )
            )
            continue
        try:
            start, date = parse_minutes(row["Начало"])
            end, end_date = parse_minutes(row["Окончание"])
            if date and end_date and date != end_date:
                raise ValueError("Временное окно должно принадлежать одному рабочему дню")
            if date:
                dates.add(date)
                ds.date = date
            bk = row["Тип заявки BK"].strip()
            work = row["Тип заявки HD"].strip()
            source_status = (row.get("Статус BK") or "").strip()
            if bk not in settings.skill_mapping:
                raise ValueError(f"Добавьте навык для типа BK: {bk}")
            if bk not in settings.normative_durations and work not in settings.durations:
                raise ValueError(f"Добавьте длительность для типа HD: {work}")
            source_id = row["Заявка"].strip()
            if source_id in seen:
                ds.issues.append(
                    Issue(
                        severity="warning",
                        row=number,
                        field="Заявка",
                        value=source_id,
                        message="Повтор исходного ID: строки сохранены раздельно",
                        suggestion="Проверьте историю заявки",
                    )
                )
            seen.add(source_id)
            address = normalize_address(row["Адрес"])
            entry = geo.get(address, {})
            job = Job(
                id=f"{hashlib.sha256(raw).hexdigest()[:10]}-{number}",
                source_id=source_id,
                source_line=number,
                address=address,
                raw_address=row["Адрес"],
                source_status=source_status,
                district=row.get("Район", ""),
                service_area=region,
                location=entry.get("location"),
                geo_quality=entry.get("quality", "missing"),
                geo_note=entry.get("note", ""),
                work_type=work,
                bk_type=bk,
                window_start=start,
                window_end=end,
                duration_minutes=configured_duration(settings, bk, work),
                required_skill=settings.skill_mapping[bk],
                priority=configured_priority(bk, work),
                provenance={
                    "source_id": "provided",
                    **({"source_status": "provided"} if source_status else {}),
                    "window_start": "provided",
                    "window_end": "provided",
                    "address": "computed",
                    "location": "computed",
                    "duration_minutes": "configured",
                    "required_skill": "configured",
                    "priority": "configured",
                },
            )
            ds.jobs.append(job)
            if source_status in historical_statuses:
                historical_statuses[source_status] += 1
        except (ValueError, TypeError) as error:
            ds.issues.append(
                Issue(
                    severity="error",
                    row=number,
                    field="Заявка",
                    value=row.get("Заявка", ""),
                    message=str(error),
                    suggestion="Исправьте строку и импортируйте повторно",
                )
            )
    if len(dates) > 1:
        ds.issues.append(
            Issue(
                severity="error",
                field="Начало",
                message="Набор содержит несколько рабочих дней",
                suggestion="Загрузите один рабочий день",
            )
        )
    if any(historical_statuses.values()):
        counts = ", ".join(
            f"{status.lower()} - {count}" for status, count in historical_statuses.items() if count
        )
        ds.issues.append(
            Issue(
                severity="warning",
                field="Статус BK",
                message=f"В исходном CSV есть заявки со статусами: {counts}",
                suggestion=(
                    "Это исторические статусы. Все строки сохранены для моделирования дня; "
                    "проверьте состав заявок перед расчётом"
                ),
            )
        )
    if len(ds.jobs) > 150:
        raise ValueError("Максимум 150 заявок на регион")
    return ds


def generate_engineers(names, office, settings, service_area=""):
    combinations = [
        ["local", "connection", "emergency"],
        ["connection", "local"],
        ["local"],
        ["connection", "emergency"],
        ["local", "emergency"],
        ["connection"],
    ]
    # Q&A: most field engineers travel on foot and by public transport.
    # The exact split is synthetic and remains editable in engineer profiles.
    transports = [
        "public",
        "public",
        "car",
        "public",
        "walk",
        "public",
        "public",
        "bicycle",
        "public",
        "car",
        "public",
        "public",
    ]
    engineers = []
    for i, name in enumerate(names):
        skills = combinations[i % len(combinations)]
        equipment = sorted({item for skill in skills for item in settings.equipment_by_skill.get(skill, [])})
        engineers.append(
            Engineer(
                id=f"engineer-{i + 1:02d}",
                name=name,
                service_area=service_area,
                start_location=office,
                start_mode="office",
                shift_start=settings.shift_start,
                shift_end=settings.shift_end,
                skills=skills,
                transport=transports[i % len(transports)],
                equipment=equipment,
                provenance={
                    "name": "provided",
                    "start_location": "configured",
                    "shift_start": "synthetic",
                    "shift_end": "synthetic",
                    "skills": "synthetic",
                    "transport": "synthetic",
                    "equipment": "synthetic",
                },
            )
        )
    return engineers


def validation_issues(ds):
    issues = list(ds.issues)
    if not ds.jobs:
        issues.append(Issue(severity="error", field="jobs", message="В наборе нет заявок"))
    if not ds.engineers:
        issues.append(Issue(severity="error", field="engineers", message="Добавьте хотя бы одного инженера"))
    if ds.office_location and ds.office_geo_quality == "address_variant":
        issues.append(
            Issue(
                severity="warning",
                field="office_location",
                value=ds.office_address,
                message=ds.office_geo_note,
                suggestion="При необходимости исправьте стартовые точки инженеров",
            )
        )
    for job in ds.jobs:
        if not job.service_area:
            issues.append(
                Issue(
                    severity="error",
                    row=job.source_line,
                    field="service_area",
                    value=job.source_id,
                    message="Не указан участок заявки",
                )
            )
        if job.location is None:
            issues.append(
                Issue(
                    severity="error",
                    row=job.source_line,
                    field="location",
                    value=job.source_id,
                    message="Адрес не геокодирован",
                    suggestion="Укажите проверенные широту и долготу в редакторе",
                )
            )
        elif job.geo_quality not in ("house", "verified", "manual"):
            issues.append(
                Issue(
                    severity="warning",
                    row=job.source_line,
                    field="location",
                    value=job.source_id,
                    message=job.geo_note or "Координаты требуют проверки: " + job.geo_quality,
                )
            )
    for engineer in ds.engineers:
        if not engineer.service_area:
            issues.append(
                Issue(
                    severity="error",
                    field="service_area",
                    value=engineer.name,
                    message="Не указан участок инженера",
                )
            )
        if engineer.start_location is None:
            issues.append(
                Issue(
                    severity="error",
                    field="start_location",
                    value=engineer.name,
                    message="Нет стартовой точки инженера",
                )
            )
    return issues


def apply_defaults(ds):
    for job in ds.jobs:
        if (
            "duration_minutes" not in job.manual_fields
            and job.provenance.get("duration_minutes") == "configured"
            and (job.bk_type in ds.settings.normative_durations or job.work_type in ds.settings.durations)
        ):
            job.duration_minutes = configured_duration(ds.settings, job.bk_type, job.work_type)
        if (
            "required_skill" not in job.manual_fields
            and job.provenance.get("required_skill") == "configured"
            and job.bk_type in ds.settings.skill_mapping
        ):
            job.required_skill = ds.settings.skill_mapping[job.bk_type]
        if "priority" not in job.manual_fields and job.provenance.get("priority") == "configured":
            job.priority = configured_priority(job.bk_type, job.work_type)
        if (
            not ds.settings.transport_demo_enabled
            and "required_transport" not in job.manual_fields
            and job.provenance.get("required_transport") == "synthetic"
        ):
            job.required_transport = None
    for engineer in ds.engineers:
        for field in ("shift_start", "shift_end"):
            if field not in engineer.manual_fields and engineer.provenance.get(field) in (
                "synthetic",
                "configured",
            ):
                setattr(engineer, field, getattr(ds.settings, field))
    return ds
