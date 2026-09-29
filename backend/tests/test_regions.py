import json
import time

import pytest

from app.importer import configured_duration, validation_issues
from app.models import Dataset
from app.planner import build_plan, validate_plan
from app.storage import DATA


@pytest.mark.parametrize("name,count", [("01-east", 66), ("02-southeast", 83), ("03-southcenter", 56)])
def test_full_region(name, count):
    ds = Dataset.model_validate_json((DATA / "normalized" / f"{name}.json").read_text(encoding="utf-8"))
    assert len(ds.jobs) == count
    assert not [issue for issue in validation_issues(ds) if issue.severity == "error"]
    started = time.monotonic()
    baseline = build_plan(ds, "baseline")
    plan = build_plan(ds)
    assert time.monotonic() - started < 30
    assert not validate_plan(baseline) and not validate_plan(plan)
    assert tuple(plan["objective"]) <= tuple(baseline["objective"])
    assert all(j.location for j in ds.jobs)
    assert all(
        j.duration_minutes == configured_duration(ds.settings, j.bk_type, j.work_type) for j in ds.jobs
    )
    assert all(j.priority == ("urgent" if j.work_type == "Авария" else "normal") for j in ds.jobs)
    assert ds.settings.equipment_enabled
    assert all(engineer.equipment for engineer in ds.engineers)
    assert any(engineer.start_mode == "home" for engineer in ds.engineers)
    for route in plan["routes"]:
        engineer = next(item for item in ds.engineers if item.id == route["engineer_id"])
        assert route["anchor"]["location"] == engineer.start_location.model_dump()
    print(
        json.dumps(
            {
                "region": ds.region,
                "baseline": baseline["metrics"],
                "optimized": plan["metrics"],
                "seconds": plan["calculation_seconds"],
            },
            ensure_ascii=False,
        )
    )
