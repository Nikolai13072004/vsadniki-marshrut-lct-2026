import csv
import hashlib
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.events import apply_event
from app.importer import (
    configured_duration,
    configured_priority,
    decode_csv,
    defaults,
    import_csv,
    normalize_address,
    validation_issues,
)
from app.main import create_app, migrate_seed_dataset
from app.models import Dataset, EventRequest, Job, Location
from app.planner import Context, build_plan, freeze_states, objective, priority_level, validate_plan
from app.routing import Matrix
from app.storage import DATA


@pytest.mark.parametrize("mode", ["baseline", "optimized"])
def test_valid_unique_schedule_and_metrics(sample, mode):
    plan = build_plan(sample, mode)
    assert not validate_plan(plan)
    assert plan["metrics"]["assigned"] == len(sample.jobs)
    assert plan["metrics"]["distance_m"] == sum(r["distance_m"] for r in plan["routes"])
    for route in plan["routes"]:
        for previous, current in zip(route["stops"], route["stops"][1:]):
            assert current["arrival"] >= previous["finish"] + current["travel_minutes"]


@pytest.mark.parametrize(
    "field,value,phrase",
    [
        ("required_skill", "connection", "навык"),
        ("required_transport", "public", "транспорт"),
        ("required_equipment", ["Модем X"], "оборудования"),
    ],
)
def test_resources_never_violated(sample, field, value, phrase):
    for e in sample.engineers:
        e.skills = ["local"]
    setattr(sample.jobs[0], field, value)
    plan = build_plan(sample)
    reason = next(x for x in plan["unassigned"] if x["job_id"] == "j0")
    assert any(phrase in s for s in reason["reasons"])
    assert not validate_plan(plan)


@pytest.mark.parametrize("mode", ["baseline", "optimized"])
def test_engineers_stay_within_their_service_area(sample, mode):
    sample.jobs = sample.jobs[:2]
    sample.jobs[0].district = "Район 1"
    sample.jobs[1].district = "Район 2"
    sample.jobs[1].service_area = "Другой участок"
    sample.engineers[1].service_area = "Другой участок"

    plan = build_plan(sample, mode)
    assignments = {
        stop["job_id"]: route["engineer_id"] for route in plan["routes"] for stop in route["stops"]
    }
    assert assignments == {"j0": "e1", "j1": "e2"}
    assert not validate_plan(plan)


def test_different_districts_and_cities_are_allowed_within_one_service_area(sample):
    sample.jobs = sample.jobs[:2]
    sample.jobs[0].district = "Москва"
    sample.jobs[1].district = "Домодедово"
    sample.engineers = sample.engineers[:1]

    plan = build_plan(sample)
    assert plan["metrics"]["assigned"] == 2


def test_other_service_area_is_explained_and_rejected_by_validator(sample):
    sample.jobs = sample.jobs[:1]
    sample.jobs[0].service_area = "Другой участок"
    plan = build_plan(sample)
    assert plan["metrics"]["assigned"] == 0
    assert "Другой участок" in " ".join(plan["unassigned"][0]["reasons"])

    sample.jobs[0].service_area = "Тест"
    assigned = build_plan(sample)
    assigned["snapshot"]["jobs"][0]["service_area"] = "Другой участок"
    assert "Чужой участок j0" in validate_plan(assigned)


def test_window_is_start_window_not_finish_deadline(sample):
    sample.jobs = [sample.jobs[0]]
    sample.jobs[0].window_start = sample.jobs[0].window_end = 600
    sample.jobs[0].duration_minutes = 90
    plan = build_plan(sample)
    assert plan["metrics"]["assigned"] == 1
    assert next(r for r in plan["routes"] if r["stops"])["stops"][0]["finish"] == 690


def test_work_must_fit_shift(sample):
    sample.jobs[0].duration_minutes = 900
    plan = build_plan(sample)
    assert any(u["job_id"] == "j0" and u["code"] == "time" for u in plan["unassigned"])


def test_base_uses_input_order_first_eligible_engineer(sample):
    sample.jobs[0].window_start = 960
    sample.jobs[0].window_end = 1020
    base = build_plan(sample, "baseline")
    assert base["routes"][0]["stops"][0]["job_id"] == "j0"
    assert base["routes"][1]["stops"][0]["job_id"] == "j1"
    optimized = build_plan(sample)
    assert tuple(optimized["objective"]) <= tuple(base["objective"])


def test_objective_prefers_fewer_engineers_before_urgent_tiebreak(sample):
    sample.jobs[1].priority = "urgent"
    context = Context(sample)
    one_engineer = [[0, 2], []]
    two_engineers_with_urgent = [[1], [2]]
    assert objective(context, one_engineer) < objective(context, two_engineers_with_urgent)


def test_official_priority_order_breaks_equal_assignment_ties(sample):
    sample.jobs[0].bk_type = "Локальная заявка"
    sample.jobs[1].bk_type = "Подключение"
    sample.jobs[2].bk_type = "Глобальная проблема"
    sample.jobs[2].work_type = "Информация"
    sample.jobs[2].priority = "normal"
    assert priority_level(sample.jobs[2]) == 0
    sample.jobs[2].work_type = "Авария"
    context = Context(sample)
    assert priority_level(sample.jobs[2]) > priority_level(sample.jobs[1]) > priority_level(sample.jobs[0])
    assert objective(context, [[2], []]) < objective(context, [[1], []])
    assert objective(context, [[1], []]) < objective(context, [[0], []])


def test_global_problem_without_hd_accident_is_not_counted_as_accident(sample):
    job = sample.jobs[0]
    job.bk_type = "Глобальная проблема"
    job.work_type = "Информация"
    job.priority = "normal"
    sample.jobs = [job]

    plan = build_plan(sample)

    assert plan["metrics"]["assigned"] == 1
    assert plan["metrics"]["accident_assigned"] == 0
    assert plan["metrics"]["urgent_assigned"] == 0

    job.priority = "urgent"
    urgent_plan = build_plan(sample)
    assert urgent_plan["metrics"]["accident_assigned"] == 0
    assert urgent_plan["metrics"]["urgent_assigned"] == 1
    urgent_stop = next(stop for route in urgent_plan["routes"] for stop in route["stops"])
    assert "Приоритет 1: срочность диспетчера" in urgent_stop["explanation"]


def test_deterministic_search(sample):
    a, b = build_plan(sample), build_plan(sample)
    assert a["routes"] == b["routes"]
    assert a["unassigned"] == b["unassigned"]


def test_duplicate_addresses_are_distinct_jobs(sample):
    sample.jobs[1].address = sample.jobs[0].address
    sample.jobs[1].location = sample.jobs[0].location
    plan = build_plan(sample)
    assert plan["metrics"]["assigned"] == 5


def test_no_return_to_office(sample):
    sample.jobs = [sample.jobs[-1]]
    plan = build_plan(sample)
    route = next(r for r in plan["routes"] if r["stops"])
    assert len(route["legs"]) == 1
    assert route["distance_m"] == route["stops"][0]["distance_m"]


@pytest.mark.parametrize("encoding", ["cp1251", "utf-8", "utf-8-sig"])
@pytest.mark.parametrize("delimiter", [";", ","])
def test_csv_formats_and_office(encoding, delimiter):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter)
    writer.writerow(["Заявка", "Тип заявки BK", "Тип заявки HD", "Начало", "Окончание", "Адрес"])
    writer.writerow(
        [
            "42",
            "Локальная заявка",
            "Информация",
            "17.08.2026 10:00",
            "17.08.2026 12:00",
            "Москва, ул.Тестовая, д. 1",
        ]
    )
    writer.writerow([""] * 6)
    writer.writerow([""] * 6)
    writer.writerow(["Адрес Офиса", "Москва, ул.Тестовая, д. 2", "", "", "", ""])
    ds = import_csv(out.getvalue().encode(encoding), "file.csv", "test")
    assert len(ds.jobs) == 1
    assert "дом 2" in ds.office_address
    assert ds.jobs[0].source_line == 2
    assert ds.jobs[0].duration_minutes == 30


def test_csv_preserves_historical_statuses_and_accepts_102_rows():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Заявка", "Тип заявки BK", "Статус BK", "Тип заявки HD", "Начало", "Окончание", "Адрес"])
    for index in range(102):
        status = "Выполнена" if index == 0 else "Отменена" if index == 1 else "Отправлена"
        writer.writerow(
            [
                str(index),
                "Локальная заявка",
                status,
                "Информация",
                "29.09.2026 10:00",
                "29.09.2026 12:00",
                f"Москва, улица Тестовая, дом {index}",
            ]
        )

    dataset = import_csv(output.getvalue().encode("cp1251"), "день 3.csv", "Восток")

    assert len(dataset.jobs) == 102
    assert dataset.date == "2026-09-29"
    assert dataset.jobs[0].source_status == "Выполнена"
    assert dataset.jobs[1].source_status == "Отменена"
    assert dataset.jobs[0].provenance["source_status"] == "provided"
    assert any(issue.field == "Статус BK" and issue.severity == "warning" for issue in dataset.issues)
    assert not any(issue.severity == "error" for issue in dataset.issues)
    Dataset.model_validate(dataset.model_dump())

    for index in range(102, 151):
        writer.writerow(
            [
                str(index),
                "Локальная заявка",
                "Отправлена",
                "Информация",
                "29.09.2026 10:00",
                "29.09.2026 12:00",
                "Москва",
            ]
        )
    with pytest.raises(ValueError, match="Максимум 150"):
        import_csv(output.getvalue().encode("cp1251"), "слишком много.csv", "Восток")


def test_mixed_engineer_shifts_and_explicit_late_finish(sample):
    early = sample.jobs[0]
    early.location = sample.office_location
    early.window_start = early.window_end = 540
    early.duration_minutes = 30
    late = sample.jobs[1]
    late.location = sample.office_location
    late.required_skill = "connection"
    late.window_start = late.window_end = 1260
    late.duration_minutes = 30
    sample.jobs = [early, late]
    sample.engineers[0].skills = ["local"]
    sample.engineers[0].shift_start = 540
    sample.engineers[0].shift_end = 1080
    sample.engineers[1].skills = ["connection"]
    sample.engineers[1].shift_start = 600
    sample.engineers[1].shift_end = 1320

    plan = build_plan(sample)

    assert plan["metrics"]["assigned"] == 2
    assert not validate_plan(plan)
    assert {route["engineer_id"]: len(route["stops"]) for route in plan["routes"]} == {
        "e1": 1,
        "e2": 1,
    }

    sample.jobs = [late]
    sample.engineers[0].skills = ["connection"]
    sample.engineers[0].shift_start = 570
    sample.engineers[0].shift_end = 1380
    sample.engineers[1].skills = ["local"]
    late.window_start = late.window_end = 1320
    late.duration_minutes = 60

    extended = build_plan(sample)

    assert extended["metrics"]["assigned"] == 1
    assert extended["routes"][0]["stops"][0]["finish"] == 1380
    assert not validate_plan(extended)


@pytest.mark.parametrize(
    "bk_type,work_type,total,service,priority",
    [
        ("Подключение", "Заявка на подключение", 90, 70, "normal"),
        ("Глобальная проблема", "Авария", 100, 80, "urgent"),
        ("Глобальная проблема", "Информация", 100, 80, "normal"),
        ("Дозаказ", "Дозаказ оборудования", 40, 20, "normal"),
        ("Локальная заявка", "Нет линка", 50, 30, "normal"),
    ],
)
def test_official_normatives_and_emergency_priority(bk_type, work_type, total, service, priority):
    settings = defaults()
    assert settings.normative_durations[bk_type] == total
    assert configured_duration(settings, bk_type, work_type) == service
    assert configured_priority(bk_type, work_type) == priority


@pytest.mark.parametrize(
    "bk_type,work_type,duration",
    [
        ("Подключение", "Заявка на подключение", 70),
        ("Глобальная проблема", "Авария", 80),
        ("Дозаказ", "Дозаказ оборудования", 20),
        ("Локальная заявка", "Нет линка", 30),
    ],
)
def test_legacy_mode_can_keep_fixed_travel(bk_type, work_type, duration):
    settings = defaults()
    settings.normative_travel_mode = "included"
    duration += 20
    assert configured_duration(settings, bk_type, work_type) == duration


def test_seed_migration_refreshes_fixture_and_keeps_manual_fields(sample):
    old = sample.model_copy(deep=True)
    old.settings.requirements_version = 1
    old.jobs[0].duration_minutes = 77
    old.jobs[0].manual_fields = ["duration_minutes"]
    old.jobs[1].priority = "urgent"
    source = sample.model_copy(deep=True)
    source.settings.equipment_enabled = True
    source.jobs[0].duration_minutes = 90
    source.jobs[1].bk_type = "Глобальная проблема"
    source.jobs[1].work_type = "Информация"
    source.jobs[1].priority = "normal"

    migrated = migrate_seed_dataset(old.model_dump(), source.model_dump())

    assert migrated.settings.requirements_version == 8
    assert migrated.settings.demo_urgent_window == 120
    assert migrated.settings.normative_travel_mode == "separate"
    assert migrated.settings.equipment_enabled
    assert migrated.settings.equipment_by_work_type["Подключение"]
    assert migrated.jobs[0].duration_minutes == 77
    assert migrated.jobs[1].bk_type == "Глобальная проблема"
    assert migrated.jobs[1].priority == "normal"


def test_saved_import_migrates_hd_priority_without_overwriting_manual_choice(sample, tmp_path):
    sample.settings.requirements_version = 7
    for job in sample.jobs[:2]:
        job.bk_type = "Глобальная проблема"
        job.work_type = "Информация"
        job.priority = "urgent"
        job.provenance["priority"] = "configured"
    sample.jobs[1].manual_fields.append("priority")
    app = create_app(tmp_path / "migration.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())

    with TestClient(app) as client:
        response = client.get(f"/api/datasets/{sample.id}")

    assert response.status_code == 200
    migrated = response.json()
    assert migrated["revision"] == sample.revision + 1
    assert migrated["settings"]["requirements_version"] == 8
    assert migrated["jobs"][0]["priority"] == "normal"
    assert migrated["jobs"][1]["priority"] == "urgent"


def test_import_error_reports_line_and_field():
    ds = import_csv("Заявка;Адрес\n42;Москва".encode(), "x.csv", "x")
    assert ds.issues and all(i.severity == "error" and i.field for i in ds.issues)
    with pytest.raises(ValueError):
        decode_csv(b"\x00\x01")


def test_import_incomplete_csv_row_reports_error():
    ds = import_csv("Заявка;Адрес\n42".encode(), "x.csv", "x")
    assert ds.issues
    assert all(issue.severity == "error" for issue in ds.issues)


def test_source_integrity_and_counts():
    manifest = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
    for entry in manifest:
        raw = (DATA / "raw" / entry["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        ds = import_csv(raw, entry["file"], "test")
        assert len(ds.jobs) == entry["rows"]
        assert not any(i.severity == "error" for i in ds.issues)
    assert len(manifest) == 6


def test_source_duplicate_id_preserved():
    path = DATA / "raw" / "Юго-восток Контрольное распределение.csv"
    ds = import_csv(path.read_bytes(), path.name, "test")
    assert len(ds.jobs) == 83
    assert len({j.id for j in ds.jobs}) == 83
    assert len({j.source_id for j in ds.jobs}) == 82


def test_missing_coords_block_calculation(sample):
    sample.jobs[0].location = None
    assert any(i.field == "location" and i.severity == "error" for i in validation_issues(sample))


def test_transport_matrix_and_offline_fallback(sample, monkeypatch):
    def fail(*args, **kwargs):
        import httpx

        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("app.routing.httpx.get", fail)
    sample.settings.routing_provider = "osrm"
    matrix = Matrix([sample.jobs[0].location, sample.jobs[-1].location], sample.settings)
    assert matrix.method == "estimate"
    assert matrix.minutes("walk", 0, 1) > matrix.minutes("car", 0, 1)
    assert "резервный" in matrix.notice


def test_urgent_keeps_started_work_and_travel(sample):
    before = build_plan(sample)
    t = 645
    states = freeze_states(before, t)
    new = sample.model_copy(deep=True)
    new.jobs.append(
        Job(
            id="urgent",
            source_id="U",
            address="Офис",
            location=new.office_location,
            work_type="Авария",
            required_skill="emergency",
            window_start=t,
            window_end=950,
            duration_minutes=45,
            priority="urgent",
        )
    )
    after = build_plan(new, states=states, parent=before, event={"type": "urgent", "time": t})
    assert after["metrics"]["urgent_assigned"] == 1
    for route in before["routes"]:
        frozen = [s for s in route["stops"] if s["start"] <= t]
        new_route = next(r for r in after["routes"] if r["engineer_id"] == route["engineer_id"])
        assert new_route["stops"][: len(frozen)] == frozen
    assert after["parent_id"] == before["id"]
    assert not validate_plan(after)


def test_freezes_current_trip_and_destination_job(sample):
    sample.jobs = [sample.jobs[-1]]
    before = build_plan(sample)
    route = next(r for r in before["routes"] if r["stops"])
    leg = route["legs"][0]
    t = leg["departure"] + 1
    state = freeze_states(before, t)[route["engineer_id"]]
    assert state["time"] == route["stops"][0]["finish"]
    assert state["legs"][0] == leg
    assert state["stops"][0] == route["stops"][0]


def test_unavailable_engineer_finishes_trip_started_before_event():
    dataset = Dataset.model_validate_json((DATA / "normalized" / "00-demo.json").read_text(encoding="utf-8"))
    first = build_plan(dataset)
    second = apply_event(first, EventRequest(type="cancel", time=780, job_id="demo-j01"), None)

    third = apply_event(second, EventRequest(type="unavailable", time=780, engineer_id="demo-e1"), None)

    engineer_route = next(route for route in third["routes"] if route["engineer_id"] == "demo-e1")
    assert engineer_route["frozen_count"] > 0
    assert engineer_route["stops"][engineer_route["frozen_count"] - 1]["finish"] > 780
    assert not validate_plan(third)


def test_api_demo_export_patch_and_history(sample, tmp_path):
    app = create_app(tmp_path / "api.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        baseline = client.post("/api/plans/baseline", json={"dataset_id": sample.id})
        assert baseline.status_code == 200, baseline.text
        optimized = client.post("/api/plans/optimize", json={"dataset_id": sample.id})
        assert optimized.status_code == 200, optimized.text
        p = optimized.json()
        cached = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        assert cached["id"] == p["id"] and cached["cached"]
        after = client.post(
            f"/api/plans/{p['id']}/events", json={"type": "urgent", "time": 645, "demo": True}
        )
        assert after.status_code == 200, after.text
        a = after.json()
        assert a["metrics"]["urgent_assigned"] == 1
        assert client.get(f"/api/plans/{a['id']}/compare").status_code == 200
        exported = client.get(f"/api/plans/{a['id']}/export?format=csv")
        assert exported.status_code == 200 and b"source_id" in exported.content
        assert client.get(f"/api/plans/{a['id']}/export?format=json").json()["id"] == a["id"]
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 3
        response = client.patch(
            f"/api/datasets/{sample.id}", json={"revision": 1, "settings": sample.settings.model_dump()}
        )
        assert response.status_code == 200
        conflict = client.patch(
            f"/api/datasets/{sample.id}", json={"revision": 1, "settings": sample.settings.model_dump()}
        )
        assert conflict.status_code == 422
        assert client.post("/api/datasets/import", files={"file": ("bad.exe", b"MZ")}).status_code == 415


def test_editing_address_requires_fresh_coordinates(sample, tmp_path):
    app = create_app(tmp_path / "address.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    path = f"/api/datasets/{sample.id}"
    original = sample.model_dump()
    updated_jobs = original["jobs"]
    updated_jobs[0]["address"] = "Москва, улица Тестовая, дом 99"

    with TestClient(app) as client:
        rejected = client.patch(path, json={"revision": sample.revision, "jobs": updated_jobs})
        assert rejected.status_code == 422
        assert "координаты остались прежними" in rejected.json()["detail"]
        assert client.get(path).json()["revision"] == sample.revision

        updated_jobs[0]["location"] = {"latitude": 55.75, "longitude": 37.62}
        updated_jobs[0]["geo_quality"] = "manual"
        updated_jobs[0]["geo_note"] = "Проверено диспетчером"
        accepted = client.patch(path, json={"revision": sample.revision, "jobs": updated_jobs})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["jobs"][0]["location"] == updated_jobs[0]["location"]


def test_event_preview_keeps_history_unchanged_until_confirmation(sample, tmp_path):
    app = create_app(tmp_path / "preview.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        path = f"/api/plans/{parent['id']}/events"
        preview_response = client.post(path + "/preview", json={"type": "urgent", "time": 645, "demo": True})
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["parent_id"] == parent["id"]
        assert client.get(f"/api/plans/{preview['id']}").status_code == 404
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 1

        confirmed = client.post(path + "/confirm", json={"preview_id": preview["id"]})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json() == preview
        assert client.get(f"/api/plans/{preview['id']}").status_code == 200
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 2
        assert client.post(path + "/confirm", json={"preview_id": preview["id"]}).status_code == 422


def test_event_preview_rejects_changed_dataset(sample, tmp_path):
    app = create_app(tmp_path / "preview-stale.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        path = f"/api/plans/{parent['id']}/events"
        preview = client.post(path + "/preview", json={"type": "urgent", "time": 645, "demo": True}).json()
        updated = client.patch(
            f"/api/datasets/{sample.id}",
            json={"revision": sample.revision, "settings": sample.settings.model_dump()},
        )
        assert updated.status_code == 200, updated.text
        rejected = client.post(path + "/confirm", json={"preview_id": preview["id"]})
        assert rejected.status_code == 422
        assert client.get(f"/api/plans/{preview['id']}").status_code == 404


@pytest.mark.parametrize("suffix", ["", "/preview"])
def test_new_event_rejects_stale_plan(sample, tmp_path, suffix):
    app = create_app(tmp_path / "stale-event.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        changed = client.patch(
            f"/api/datasets/{sample.id}",
            json={"revision": sample.revision, "settings": sample.settings.model_dump()},
        )
        assert changed.status_code == 200, changed.text

        response = client.post(
            f"/api/plans/{parent['id']}/events{suffix}",
            json={"type": "urgent", "time": 645, "demo": True},
        )
        assert response.status_code == 422
        assert "Постройте план заново" in response.json()["detail"]
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 1


def test_manual_change_rejects_stale_plan(sample, tmp_path):
    app = create_app(tmp_path / "stale-manual.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        stop = next(stop for route in parent["routes"] for stop in route["stops"])
        changed = client.patch(
            f"/api/datasets/{sample.id}",
            json={"revision": sample.revision, "settings": sample.settings.model_dump()},
        )
        assert changed.status_code == 200, changed.text

        response = client.post(
            f"/api/plans/{parent['id']}/manual",
            json={
                "job_id": stop["job_id"],
                "engineer_id": stop["engineer_id"],
                "time": 540,
                "position": 0,
            },
        )
        assert response.status_code == 422
        assert "Постройте план заново" in response.json()["detail"]


@pytest.mark.parametrize("completion_offset", [-5, 20])
def test_actual_completion_releases_engineer_at_actual_time(sample, tmp_path, completion_offset):
    app = create_app(tmp_path / "actual-completion.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        route = next(route for route in parent["routes"] if len(route["stops"]) > 1)
        stop = route["stops"][0]
        path = f"/api/plans/{parent['id']}/events"
        en_route = client.post(
            path,
            json={
                "type": "status",
                "time": stop["departure"],
                "job_id": stop["job_id"],
                "job_status": "en_route",
            },
        )
        assert en_route.status_code == 200, en_route.text
        in_progress = client.post(
            f"/api/plans/{en_route.json()['id']}/events",
            json={
                "type": "status",
                "time": stop["start"],
                "job_id": stop["job_id"],
                "job_status": "in_progress",
            },
        )
        assert in_progress.status_code == 200, in_progress.text

        actual_finish = stop["finish"] + completion_offset
        completed = client.post(
            f"/api/plans/{in_progress.json()['id']}/events",
            json={"type": "complete", "time": actual_finish, "job_id": stop["job_id"]},
        )
        assert completed.status_code == 200, completed.text
        result = completed.json()
        updated_route = next(item for item in result["routes"] if item["engineer_id"] == route["engineer_id"])
        assert updated_route["stops"][0]["finish"] == actual_finish
        assert updated_route["stops"][0]["completed_at"] == actual_finish
        assert all(item["departure"] >= actual_finish for item in updated_route["stops"][1:])
        assert not validate_plan(result)


def test_status_cannot_start_before_window_but_can_be_recorded_late(sample, tmp_path):
    app = create_app(tmp_path / "status-times.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        stop = next(stop for route in parent["routes"] for stop in route["stops"])
        en_route = client.post(
            f"/api/plans/{parent['id']}/events",
            json={
                "type": "status",
                "time": stop["departure"],
                "job_id": stop["job_id"],
                "job_status": "en_route",
            },
        )
        assert en_route.status_code == 200, en_route.text
        early = client.post(
            f"/api/plans/{en_route.json()['id']}/events",
            json={
                "type": "status",
                "time": stop["start"] - 1,
                "job_id": stop["job_id"],
                "job_status": "in_progress",
            },
        )
        assert early.status_code == 422

        late_time = stop["finish"] + 5
        late = client.post(
            f"/api/plans/{en_route.json()['id']}/events",
            json={"type": "status", "time": late_time, "job_id": stop["job_id"], "job_status": "in_progress"},
        )
        assert late.status_code == 200, late.text
        assert not validate_plan(late.json())


@pytest.mark.parametrize(
    "event",
    [
        {"type": "reschedule", "time": 645, "job_id": "j4", "window_start": 840, "window_end": 960},
        {"type": "unavailable", "time": 645, "engineer_id": "e1"},
    ],
)
def test_other_replanning_events_can_be_previewed(sample, tmp_path, event):
    app = create_app(tmp_path / "other-preview.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        parent = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        path = f"/api/plans/{parent['id']}/events"
        preview_response = client.post(path + "/preview", json=event)
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["event"]["type"] == event["type"]
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 1
        confirmed = client.post(path + "/confirm", json={"preview_id": preview["id"]})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json() == preview
        assert not validate_plan(confirmed.json())


def test_region_report_uses_three_unchanged_input_files(tmp_path):
    app = create_app(tmp_path / "report.sqlite", seed=False)
    with TestClient(app) as client:
        response = client.get("/api/reports/regions")
    assert response.status_code == 200, response.text
    rows = response.json()["regions"]
    assert {row["dataset_id"] for row in rows} == {"east", "southeast", "southcenter"}
    assert all(row["raw_input_sha256"] and row["source_sha256"] for row in rows)
    assert all(
        row["optimized"]["metrics"]["assigned"] >= row["baseline"]["metrics"]["assigned"] for row in rows
    )


def test_hundred_jobs_under_thirty_seconds(sample):
    sample.engineers = [
        sample.engineers[0].model_copy(update={"id": f"e{i}", "name": f"Инженер {i}"}) for i in range(15)
    ]
    sample.jobs = [
        sample.jobs[0].model_copy(
            update={
                "id": f"j{i}",
                "window_start": 600,
                "window_end": 960,
                "location": Location(latitude=55.7 + (i % 10) * 0.004, longitude=37.7 + (i // 10) * 0.004),
            }
        )
        for i in range(100)
    ]
    start = time.monotonic()
    plan = build_plan(sample)
    assert time.monotonic() - start < 30
    assert not validate_plan(plan)
    assert plan["metrics"]["assigned"] == 100


def test_address_normalization_keeps_house_details():
    assert (
        normalize_address("г.Город Москва, ул.Ташкентская, д. 16к2, кв. 42")
        == "Москва, улица Ташкентская, дом 16к2"
    )
