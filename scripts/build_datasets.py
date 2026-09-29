"""Build normalized fixtures from immutable CSV and audited geocoder output."""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.importer import (  # noqa: E402
    configured_duration,
    configured_priority,
    defaults,
    generate_engineers,
    import_csv,
    validation_issues,
)
from app.models import Dataset, Engineer  # noqa: E402


def main():
    geo = json.loads((ROOT / "data" / "geocodes.json").read_text(encoding="utf-8"))
    for override in json.loads((ROOT / "data" / "coordinate-overrides.json").read_text(encoding="utf-8")):
        for address in geo:
            if override["contains"] in address:
                geo[address] = {key: value for key, value in override.items() if key != "contains"}
    (ROOT / "data" / "geocodes.json").write_text(
        json.dumps(geo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    target = ROOT / "data" / "normalized"
    target.mkdir(exist_ok=True)
    datasets = []
    for i, (prefix, identifier) in enumerate(
        [("Восток", "east"), ("Юго-восток", "southeast"), ("Югоцентр", "southcenter")], 1
    ):
        source = next((ROOT / "data" / "raw").glob(f"{prefix} Синтетические*.csv"))
        control = next((ROOT / "data" / "raw").glob(f"{prefix} Контрольное*.csv"))
        rows = list(csv.DictReader(control.read_text(encoding="cp1251").splitlines(), delimiter=";"))
        names = list(dict.fromkeys(r["Бригада"] for r in rows if r["Бригада"]))
        ds = import_csv(source.read_bytes(), prefix, prefix, geo)
        ds.settings.equipment_enabled = True
        ds.id = identifier
        ds.source_files = [source.name, control.name]
        ds.historical = [
            {
                "source_id": r["Заявка"],
                "engineer": r["Бригада"],
                "status": r["Статус BK"],
                "window_start": r["Начало"],
                "window_end": r["Окончание"],
            }
            for r in rows
        ]
        ds.engineers = generate_engineers(names, ds.office_location, ds.settings, prefix)
        if ds.engineers and ds.jobs:
            # One reproducible home start demonstrates the supported suburban workflow.
            home_engineer = ds.engineers[-1]
            home_job = next(job for job in reversed(ds.jobs) if job.location is not None)
            home_engineer.start_location = home_job.location
            home_engineer.start_mode = "home"
            home_engineer.start_address = "Домашняя стартовая точка (синтетика)"
            home_engineer.provenance["start_location"] = "synthetic"
        # Explicit deterministic synthetic transport requirements, separate from raw fields.
        for index, job in enumerate(ds.jobs):
            if index % 12 == 0:
                job.required_transport = "car"
                job.provenance["required_transport"] = "synthetic"
        datasets.append(ds)
        (target / f"{i:02d}-{identifier}.json").write_text(ds.model_dump_json(indent=2), encoding="utf-8")
        issues = validation_issues(ds)
        print(
            f"{identifier}: {len(ds.jobs)} jobs, {len(ds.engineers)} engineers, {sum(j.location is not None for j in ds.jobs)} coordinates; errors={sum(x.severity == 'error' for x in issues)}"
        )
    # Dedicated 12-job reproducible acceptance fixture, based on real, geocoded building addresses.
    base = datasets[2]
    available = [j for j in base.jobs if j.location is not None]
    if len(available) < 12 or base.office_location is None:
        print("Demo awaits verified office and 12 building coordinates")
        return
    settings = defaults()
    settings.equipment_enabled = True
    office = base.office_location
    engineers = [
        Engineer(
            id="demo-e1",
            name="Соколов Алексей",
            service_area=base.region,
            start_location=office,
            start_mode="office",
            skills=["local", "connection", "emergency"],
            transport="car",
            equipment=settings.equipment_catalog,
        ),
        Engineer(
            id="demo-e2",
            name="Волкова Мария",
            service_area=base.region,
            start_location=office,
            start_mode="office",
            skills=["local", "connection"],
            transport="public",
            equipment=["Тестер линии", "Роутер", "Кабельный комплект"],
        ),
        Engineer(
            id="demo-e3",
            name="Мельников Илья",
            service_area=base.region,
            start_location=office,
            start_mode="office",
            skills=["local", "emergency"],
            transport="public",
            equipment=["Тестер линии", "Кабельный комплект"],
        ),
        Engineer(
            id="demo-e4",
            name="Орлова Анна",
            service_area=base.region,
            start_location=available[-1].location,
            start_mode="home",
            start_address="Домашняя стартовая точка (синтетика)",
            skills=["local"],
            transport="walk",
            equipment=["Тестер линии"],
        ),
    ]
    # Deliberately unsorted windows make the input-order baseline meaningfully different.
    starts = [1080, 1020, 960, 600, 660, 720, 780, 840, 900, 600, 720, 540]
    pattern = [
        "Подключение",
        "Локальная заявка",
        "Дозаказ",
        "Подключение",
        "Локальная заявка",
        "Глобальная проблема",
        "Локальная заявка",
        "Подключение",
        "Локальная заявка",
        "Дозаказ",
        "Подключение",
        "Локальная заявка",
    ]
    selected, used = [], set()
    for bk_type in pattern:
        original = next(job for job in available if job.bk_type == bk_type and job.id not in used)
        selected.append(original)
        used.add(original.id)
    jobs = []
    for index, original in enumerate(selected):
        job = original.model_copy(deep=True)
        job.id = f"demo-j{index + 1:02d}"
        job.source_id = f"Д-{index + 1:03d}"
        job.window_start = starts[index]
        job.window_end = starts[index] + 120 if index < 11 else 540
        job.duration_minutes = configured_duration(settings, job.bk_type, job.work_type)
        job.required_skill = settings.skill_mapping[job.bk_type]
        job.required_transport = "car" if index in (0, 3, 6) else None
        job.priority = configured_priority(job.bk_type, job.work_type)
        job.provenance.update(
            {
                key: "synthetic"
                for key in [
                    "source_id",
                    "window_start",
                    "window_end",
                    "duration_minutes",
                    "required_skill",
                    "required_transport",
                ]
            }
        )
        jobs.append(job)
    for e in engineers:
        e.provenance = {key: "synthetic" for key in e.model_dump() if key not in ["id", "provenance"]}
    demo = Dataset(
        id="demo",
        name="Демонстрация · 12 заявок",
        region="Демо / Югоцентр",
        jobs=jobs,
        engineers=engineers,
        office_address=base.office_address,
        office_location=office,
        office_geo_quality=base.office_geo_quality,
        office_geo_note=base.office_geo_note,
        settings=settings,
        source_files=base.source_files,
    )
    (target / "00-demo.json").write_text(demo.model_dump_json(indent=2), encoding="utf-8")
    print("demo: 12 jobs, 4 engineers, one intentional time conflict")


if __name__ == "__main__":
    main()
