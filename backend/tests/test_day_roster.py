import copy

import pytest
from fastapi.testclient import TestClient

from app.events import apply_event, assign_manually
from app.main import create_app
from app.models import EventRequest, Job, ManualRequest
from app.planner import build_plan, validate_plan


def single_worker_day(sample):
    sample.jobs = sample.jobs[:1]
    sample.jobs[0].location = sample.office_location
    sample.jobs[0].window_start = 600
    sample.engineers[0].skills = ["local"]
    sample.engineers[1].skills = ["connection", "emergency"]
    sample.settings.equipment_enabled = False
    return sample


def incoming_job(sample, skill="connection"):
    return Job(
        id="incoming",
        address="Москва, новый объект",
        location=sample.office_location,
        work_type="Авария" if skill == "emergency" else "Подключение",
        bk_type="Глобальная проблема" if skill == "emergency" else "Подключение",
        window_start=650,
        window_end=1000,
        duration_minutes=80 if skill == "emergency" else 70,
        required_skill=skill,
    )


@pytest.mark.parametrize("event_type,skill", [("new", "connection"), ("urgent", "emergency")])
def test_new_events_do_not_call_initially_idle_engineer(sample, event_type, skill):
    single_worker_day(sample)
    before = build_plan(sample)
    original = copy.deepcopy(before)
    after = apply_event(
        before, EventRequest(type=event_type, time=545, job=incoming_job(sample, skill)), None
    )
    assert before == original
    assert before["working_engineer_ids"] == after["working_engineer_ids"] == ["e1"]
    assert next(route for route in after["routes"] if route["engineer_id"] == "e2")["stops"] == []
    reason = next(item for item in after["unassigned"] if item["job_id"] == "incoming")
    assert any("первоначальном плане" in text for text in reason["reasons"])
    assert not validate_plan(after)


def test_cancelled_last_job_does_not_remove_worker_from_day(sample):
    single_worker_day(sample)
    before = build_plan(sample)
    cancelled = apply_event(before, EventRequest(type="cancel", time=540, job_id="j0"), None)
    assert cancelled["metrics"]["engineers_used"] == 0
    assert cancelled["working_engineer_ids"] == ["e1"]
    job = incoming_job(sample, "local")
    after = apply_event(cancelled, EventRequest(type="new", time=550, job=job), None)
    assert after["event"]["inserted"] is True
    assert after["routes"][0]["stops"][0]["job_id"] == "incoming"
    assert not validate_plan(after)


def test_empty_initial_plan_does_not_start_engineers_automatically(sample):
    sample.jobs = []
    before = build_plan(sample)
    assert before["working_engineer_ids"] == []
    after = apply_event(before, EventRequest(type="urgent", time=545, demo=True), None)
    assert after["metrics"]["assigned"] == 0
    assert after["working_engineer_ids"] == []
    assert not validate_plan(after)


def test_manual_call_requires_confirmation_and_keeps_roster_in_later_versions(sample):
    sample.jobs = sample.jobs[:1]
    before = build_plan(sample)
    assert before["working_engineer_ids"] == ["e1"]
    request = ManualRequest(job_id="j0", engineer_id="e2", time=540)
    with pytest.raises(ValueError, match="Подтвердите"):
        assign_manually(before, request, None)
    assert before["working_engineer_ids"] == ["e1"]
    request.activate_engineer = True
    manual = assign_manually(before, request, None)
    assert manual["working_engineer_ids"] == ["e1", "e2"]
    assert manual["event"]["engineer_activated"] is True
    assert "подтвердил" in manual["event"]["notice"]
    cancelled = apply_event(manual, EventRequest(type="cancel", time=540, job_id="j0"), None)
    assert cancelled["working_engineer_ids"] == ["e1", "e2"]
    after = apply_event(
        cancelled, EventRequest(type="new", time=550, job=incoming_job(sample, "local")), None
    )
    assert after["metrics"]["assigned"] == 1
    assert not validate_plan(after)


@pytest.mark.parametrize("constraint", ["area", "skill", "transport", "equipment", "availability", "time"])
def test_manual_call_does_not_bypass_other_constraints(sample, constraint):
    sample.jobs = sample.jobs[:1]
    engineer = sample.engineers[1]
    job = sample.jobs[0]
    if constraint == "area":
        engineer.service_area = "Другой участок"
    elif constraint == "skill":
        engineer.skills = ["emergency"]
    elif constraint == "transport":
        job.required_transport = "car"
    elif constraint == "equipment":
        job.required_equipment = ["Тестер линии"]
        sample.engineers[0].equipment = ["Тестер линии"]
    elif constraint == "availability":
        engineer.available = False
    else:
        engineer.shift_end = 550
    before = build_plan(sample)
    original = copy.deepcopy(before)
    with pytest.raises(ValueError, match="невыполнимо"):
        assign_manually(
            before, ManualRequest(job_id="j0", engineer_id="e2", time=540, activate_engineer=True), None
        )
    assert before == original


def test_legacy_plan_gets_roster_from_existing_work(sample):
    single_worker_day(sample)
    before = build_plan(sample)
    before.pop("working_engineer_ids")
    after = apply_event(before, EventRequest(type="urgent", time=545, demo=True), None)
    assert after["working_engineer_ids"] == ["e1"]
    assert after["metrics"]["urgent_assigned"] == 0


def test_validator_rejects_assignment_outside_roster_even_at_event_time(sample):
    before = build_plan(sample)
    before["working_engineer_ids"] = []
    before["event"] = {"type": "manual", "time": before["routes"][0]["stops"][0]["start"]}
    assert any("вне состава" in error for error in validate_plan(before))


def test_roster_survives_preview_confirmation_and_database_reopen(sample, tmp_path):
    single_worker_day(sample)
    database = tmp_path / "roster.sqlite"
    app = create_app(database, seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        initial = client.post("/api/plans/optimize", json={"dataset_id": sample.id}).json()
        path = f"/api/plans/{initial['id']}/events"
        preview_response = client.post(path + "/preview", json={"type": "urgent", "time": 545, "demo": True})
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["working_engineer_ids"] == ["e1"]
        assert preview["metrics"]["urgent_assigned"] == 0
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 1
        confirmed = client.post(path + "/confirm", json={"preview_id": preview["id"]}).json()
        assert confirmed["working_engineer_ids"] == ["e1"]
        manual_path = f"/api/plans/{confirmed['id']}/manual"
        manual_body = {"job_id": preview["event"]["job"]["id"], "engineer_id": "e2", "time": 545}
        rejected = client.post(manual_path, json=manual_body)
        assert rejected.status_code == 422
        assert "Подтвердите" in rejected.json()["detail"]
        assert len(client.get("/api/plans", params={"dataset_id": sample.id}).json()) == 2
        called_response = client.post(manual_path, json={**manual_body, "activate_engineer": True})
        assert called_response.status_code == 200
        called = called_response.json()
        assert called["working_engineer_ids"] == ["e1", "e2"]
        assert called["event"]["engineer_activated"] is True
    with TestClient(create_app(database, seed=False)) as reopened:
        saved = reopened.get(f"/api/plans/{confirmed['id']}").json()
        assert saved["working_engineer_ids"] == ["e1"]
        assert not validate_plan(saved)
        saved_call = reopened.get(f"/api/plans/{called['id']}").json()
        assert saved_call["working_engineer_ids"] == ["e1", "e2"]
        assert not validate_plan(saved_call)


def test_current_coverage_policy_in_conflict_with_one_long_emergency(sample):
    """Document the unresolved policy, not a claim that emergency priority is absolute."""
    sample.engineers = sample.engineers[:1]
    sample.engineers[0].shift_end = 620
    sample.jobs = sample.jobs[:2]
    for job, start in zip(sample.jobs, [550, 580]):
        job.location = sample.office_location
        job.window_start = job.window_end = start
        job.duration_minutes = 30
    before = build_plan(sample)
    urgent = incoming_job(sample, "emergency")
    urgent.window_start = 540
    urgent.window_end = 600
    after = apply_event(before, EventRequest(type="urgent", time=540, job=urgent), None)
    assert after["metrics"]["assigned"] == 2
    assert after["metrics"]["urgent_assigned"] == 0
    assert not validate_plan(after)
