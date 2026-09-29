import pytest
from fastapi.testclient import TestClient

from app.events import apply_event, assign_manually
from app.main import create_app
from app.models import EventRequest, Job, ManualRequest
from app.planner import build_plan, freeze_states, validate_plan


def assert_frozen(before, after, time):
    for route in before["routes"]:
        frozen = [s for s in route["stops"] if s["departure"] < time]
        target = next(r for r in after["routes"] if r["engineer_id"] == route["engineer_id"])
        assert target["stops"][: len(frozen)] == frozen


def test_cancel_future_keeps_history(sample):
    before = build_plan(sample)
    after = apply_event(before, EventRequest(type="cancel", time=645, job_id="j4"), None)
    assert after["metrics"]["total"] == 4
    assert "j4" not in {s["job_id"] for r in after["routes"] for s in r["stops"]}
    assert len(before["snapshot"]["jobs"]) == 5
    assert after["event"]["cancelled_job"]["id"] == "j4"
    assert_frozen(before, after, 645)
    assert not validate_plan(after)


def test_cannot_cancel_started(sample):
    before = build_plan(sample)
    with pytest.raises(ValueError, match="начатую"):
        apply_event(before, EventRequest(type="cancel", time=645, job_id="j0"), None)


def test_complete_started_job_is_recorded_and_excluded(sample):
    before = build_plan(sample)
    stop = next(stop for route in before["routes"] for stop in route["stops"] if stop["job_id"] == "j0")
    event_time = stop["start"] + 2
    en_route = apply_event(
        before,
        EventRequest(type="status", time=stop["departure"], job_id="j0", job_status="en_route"),
        None,
    )
    in_progress = apply_event(
        en_route,
        EventRequest(type="status", time=stop["start"], job_id="j0", job_status="in_progress"),
        None,
    )
    after = apply_event(in_progress, EventRequest(type="complete", time=event_time, job_id="j0"), None)
    completed = next(stop for route in after["routes"] for stop in route["stops"] if stop["job_id"] == "j0")
    assert completed["status"] == "completed"
    assert completed["completed_at"] == event_time
    assert after["event"]["completed_job"]["id"] == "j0"
    assert not validate_plan(after)


def test_cannot_complete_future_job(sample):
    before = build_plan(sample)
    with pytest.raises(ValueError, match="Выполнение"):
        apply_event(before, EventRequest(type="complete", time=540, job_id="j4"), None)


def test_job_statuses_follow_the_operational_sequence(sample):
    before = build_plan(sample)
    assert before["job_states"]["j0"]["status"] == "sent"
    stop = next(stop for route in before["routes"] for stop in route["stops"] if stop["job_id"] == "j0")

    en_route = apply_event(
        before,
        EventRequest(type="status", time=stop["departure"], job_id="j0", job_status="en_route"),
        None,
    )
    assert en_route["job_states"]["j0"]["status"] == "en_route"
    assert en_route["event"]["previous_status"] == "sent"
    assert en_route["locks"]["j0"]["engineer_id"]

    in_progress = apply_event(
        en_route,
        EventRequest(type="status", time=stop["start"], job_id="j0", job_status="in_progress"),
        None,
    )
    assert in_progress["job_states"]["j0"]["status"] == "in_progress"
    assert in_progress["job_states"]["j0"]["started_at"] == stop["start"]

    with pytest.raises(ValueError, match="последовательно"):
        apply_event(
            before,
            EventRequest(type="status", time=stop["start"], job_id="j0", job_status="in_progress"),
            None,
        )

    with pytest.raises(ValueError, match="раньше запланированного"):
        apply_event(
            before,
            EventRequest(
                type="status",
                time=max(0, stop["departure"] - 1),
                job_id="j0",
                job_status="en_route",
            ),
            None,
        )


def test_customer_window_can_be_rescheduled_before_work_starts(sample):
    before = build_plan(sample)
    after = apply_event(
        before,
        EventRequest(
            type="reschedule",
            time=645,
            job_id="j4",
            window_start=800,
            window_end=860,
        ),
        None,
    )
    updated = next(job for job in after["snapshot"]["jobs"] if job["id"] == "j4")
    original = next(job for job in before["snapshot"]["jobs"] if job["id"] == "j4")
    assert (updated["window_start"], updated["window_end"]) == (800, 860)
    assert (original["window_start"], original["window_end"]) != (800, 860)
    assert after["event"]["previous_window"]
    assert not validate_plan(after)


def test_customer_window_rejects_started_job_and_expired_window(sample):
    before = build_plan(sample)
    with pytest.raises(ValueError, match="начатую"):
        apply_event(
            before,
            EventRequest(
                type="reschedule",
                time=645,
                job_id="j0",
                window_start=700,
                window_end=800,
            ),
            None,
        )
    with pytest.raises(ValueError, match="завершилось"):
        apply_event(
            before,
            EventRequest(
                type="reschedule",
                time=645,
                job_id="j4",
                window_start=500,
                window_end=600,
            ),
            None,
        )


def test_unavailability_keeps_ongoing_job_finishes_no_future_work(sample):
    before = build_plan(sample)
    route = next(r for r in before["routes"] if r["stops"])
    time = route["stops"][0]["start"] + 10
    after = apply_event(
        before, EventRequest(type="unavailable", time=time, engineer_id=route["engineer_id"]), None
    )
    target = next(r for r in after["routes"] if r["engineer_id"] == route["engineer_id"])
    assert len(target["stops"]) == 1 and target["stops"][0]["finish"] > time
    assert_frozen(before, after, time)
    assert not validate_plan(after)


def test_manual_valid_and_lock_survives_event(sample):
    before = build_plan(sample)
    after = assign_manually(
        before,
        ManualRequest(job_id="j0", engineer_id="e2", position=0, time=540, activate_engineer=True),
        None,
    )
    assert after["locks"]["j0"]["engineer_id"] == "e2"
    assert before["locks"] == {}
    event = apply_event(after, EventRequest(type="urgent", time=545, demo=True), None)
    assert event["locks"] == after["locks"]
    assert not validate_plan(event)


def test_manual_assignment_rejects_another_service_area(sample):
    sample.engineers[1].service_area = "Другой участок"
    before = build_plan(sample)
    with pytest.raises(ValueError, match="Другой участок"):
        assign_manually(before, ManualRequest(job_id="j0", engineer_id="e2", position=0, time=540), None)


def test_demo_accident_uses_official_norm(sample):
    before = build_plan(sample)
    after = apply_event(before, EventRequest(type="urgent", time=645, demo=True), None)
    urgent = after["event"]["job"]
    assert urgent["duration_minutes"] == 80
    assert urgent["window_start"] == 645
    assert urgent["window_end"] == 765


def test_demo_accident_uses_the_existing_service_area(sample):
    sample.region = "Демонстрация"
    before = build_plan(sample)
    after = apply_event(before, EventRequest(type="urgent", time=645, demo=True), None)
    assert after["event"]["job"]["service_area"] == "Тест"


def test_ordinary_job_is_inserted_without_changing_existing_assignments(sample):
    before = build_plan(sample)
    job = Job(
        id="new-local",
        source_id="НОВАЯ-1",
        address="Москва, новая заявка",
        location=sample.office_location,
        geo_quality="manual",
        work_type="Локальная заявка",
        bk_type="Локальная заявка",
        window_start=900,
        window_end=1000,
        duration_minutes=20,
        required_skill="local",
    )
    after = apply_event(before, EventRequest(type="new", time=545, job=job), None)

    old_assignments = {
        stop["job_id"]: (route["engineer_id"], stop["start"])
        for route in before["routes"]
        for stop in route["stops"]
    }
    new_assignments = {
        stop["job_id"]: (route["engineer_id"], stop["start"])
        for route in after["routes"]
        for stop in route["stops"]
    }
    assert after["event"]["inserted"] is True
    assert new_assignments["new-local"]
    assert all(new_assignments[job_id] == assignment for job_id, assignment in old_assignments.items())
    assert after["locks"] == before["locks"]
    assert not validate_plan(after)


def test_ordinary_job_stays_unassigned_when_no_free_interval(sample):
    before = build_plan(sample)
    job = Job(
        id="new-long",
        source_id="НОВАЯ-2",
        address="Москва, длинная заявка",
        location=sample.office_location,
        geo_quality="manual",
        work_type="Локальная заявка",
        bk_type="Локальная заявка",
        window_start=545,
        window_end=545,
        duration_minutes=540,
        required_skill="local",
    )
    after = apply_event(before, EventRequest(type="new", time=545, job=job), None)

    assert after["event"]["inserted"] is False
    assert any(item["job_id"] == "new-long" for item in after["unassigned"])
    assert after["changes"] == []
    assert not validate_plan(after)


def test_engineer_finishes_current_trip_and_job_before_replanning(sample):
    before = build_plan(sample)
    stop = next(
        stop for route in before["routes"] for stop in route["stops"] if stop["arrival"] > stop["departure"]
    )
    event_time = stop["departure"] + 1
    states = freeze_states(before, event_time)
    state = states[stop["engineer_id"]]

    assert state["stops"][-1]["job_id"] == stop["job_id"]
    assert state["time"] >= stop["finish"]
    assert state["location"] == next(
        job["location"] for job in before["snapshot"]["jobs"] if job["id"] == stop["job_id"]
    )


def test_manual_invalid_resource_and_ongoing(sample):
    sample.jobs[0].required_skill = "connection"
    before = build_plan(sample)
    with pytest.raises(ValueError, match="невыполним"):
        assign_manually(before, ManualRequest(job_id="j0", engineer_id="e2", time=540), None)
    with pytest.raises(ValueError, match="начатую"):
        assign_manually(before, ManualRequest(job_id="j0", engineer_id="e1", time=645), None)


def test_unavailability_releases_only_future_manual_locks(sample):
    before = build_plan(sample)
    manual = assign_manually(
        before, ManualRequest(job_id="j0", engineer_id="e2", time=540, activate_engineer=True), None
    )
    after = apply_event(manual, EventRequest(type="unavailable", engineer_id="e2", time=540), None)
    assert "j0" in after["event"]["released_locks"]
    assert "j0" not in after["locks"]
    assert not validate_plan(after)


def test_equipment_matrix_and_sla(sample):
    sample.settings.equipment_enabled = True
    sample.settings.equipment_by_work_type = {"Информация": ["Тестер линии"]}
    plan = build_plan(sample)
    assert plan["metrics"]["assigned"] == 0
    sample.engineers[0].equipment = ["Тестер линии"]
    sample.settings.sla_enabled = True
    sample.settings.sla_basis = "finish"
    sample.jobs[0].sla_deadline = 615
    sample.jobs[1].sla_deadline = sample.jobs[1].window_start + 40
    plan = build_plan(sample)
    assert plan["metrics"]["assigned"] == 5
    assert plan["metrics"]["sla_late"] >= 1
    assert plan["metrics"]["sla_risk"] >= 1
    assert not validate_plan(plan)


def test_user_overrides_survive_defaults_and_api_manual(sample, tmp_path):
    sample.jobs[0].provenance["duration_minutes"] = "configured"
    app = create_app(tmp_path / "test.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        jobs = sample.model_dump()["jobs"]
        jobs[0]["duration_minutes"] = 42
        assert client.patch("/api/datasets/test", json={"revision": 1, "jobs": jobs}).status_code == 200
        settings = sample.settings.model_dump()
        settings["durations"]["Информация"] = 60
        updated = client.patch(
            "/api/datasets/test", json={"revision": 2, "settings": settings, "apply_defaults": True}
        )
        assert updated.json()["jobs"][0]["duration_minutes"] == 42
        before = client.post("/api/plans/optimize", json={"dataset_id": "test"}).json()
        manual = client.post(
            f"/api/plans/{before['id']}/manual",
            json={"job_id": "j0", "engineer_id": "e2", "time": 540, "activate_engineer": True},
        )
        assert manual.status_code == 200, manual.text
        assert client.get(f"/api/plans/{before['id']}").json() == before


def test_event_rejects_time_travel(sample):
    before = apply_event(build_plan(sample), EventRequest(type="urgent", time=645, demo=True), None)
    with pytest.raises(ValueError, match="предшествовать"):
        apply_event(before, EventRequest(type="cancel", time=540, job_id="j4"), None)
