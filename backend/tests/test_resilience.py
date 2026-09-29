import copy
import csv
import io
import json
import runpy
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.planner import build_plan, validate_plan
from app.routing import Matrix
from app.storage import Storage


def test_validator_detects_overlap_and_corrupt_counters(sample):
    plan = build_plan(sample)
    bad = copy.deepcopy(plan)
    route = next(r for r in bad["routes"] if len(r["stops"]) > 1)
    route["stops"][1]["departure"] = route["stops"][0]["finish"] - 1
    bad["metrics"]["assigned"] += 1
    violations = validate_plan(bad)
    assert any("переезда" in message for message in violations)
    assert "Счётчики заявок" in violations


@pytest.mark.parametrize(
    "body",
    [
        {"code": "Ok", "distances": [[1]], "durations": [[1]]},
        {"code": "Ok", "distances": [[0, 1], [1, 0]], "durations": [[0, None], [1, 0]]},
        {"code": "Ok", "distances": [[0, -1], [1, 0]], "durations": [[0, 1], [1, 0]]},
    ],
)
def test_bad_provider_payload_falls_back(sample, monkeypatch, body):
    monkeypatch.setattr(
        "app.routing.httpx.get",
        lambda *a, **kw: httpx.Response(200, json=body, request=httpx.Request("GET", "https://example.test")),
    )
    sample.settings.routing_provider = "osrm"
    matrix = Matrix([sample.jobs[0].location, sample.jobs[-1].location], sample.settings)
    assert matrix.method == "estimate" and matrix.minutes("car", 0, 1) > 0


def test_road_matrix_cache_and_provider_recovery(sample, tmp_path, monkeypatch):
    store = Storage(tmp_path / "matrix.sqlite")
    sample.settings.routing_provider = "osrm"
    loc = [sample.jobs[0].location, sample.jobs[-1].location]
    calls = []

    def response(*a, **kw):
        calls.append(True)
        return httpx.Response(
            200,
            json={"code": "Ok", "distances": [[0, 4321], [4567, 0]], "durations": [[0, 121], [181, 0]]},
            request=httpx.Request("GET", "https://example.test"),
        )

    def fail(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("app.routing.httpx.get", fail)
    assert Matrix(loc, sample.settings, store).method == "estimate"
    monkeypatch.setattr("app.routing.httpx.get", response)
    first = Matrix(loc, sample.settings, store)
    second = Matrix(loc, sample.settings, store)
    assert len(calls) == 1
    assert first.meters("car", 0, 1) == second.meters("car", 0, 1) == 4321
    assert first.minutes("car", 0, 1) == second.minutes("car", 0, 1) == 3
    assert first.meters("walk", 0, 1) != 4321


def test_roundtrip_export_formula_safety_and_reopen_database(sample, tmp_path):
    path = tmp_path / "persistent.sqlite"
    app = create_app(path, seed=False)
    sample.jobs[0].source_id = "=1+1"
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        p = client.post("/api/plans/optimize", json={"dataset_id": "test"}).json()
        csv_data = client.get(f"/api/plans/{p['id']}/export?format=csv").content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(csv_data), delimiter=";"))
        assert next(row for row in rows if row["job_id"] == "j0")["source_id"] == "'=1+1"
        raw = client.get(f"/api/plans/{p['id']}/export?format=json").content
        imported = client.post("/api/datasets/import", files={"file": ("plan.json", raw, "application/json")})
        assert imported.status_code == 201
        new = imported.json()
        assert len(new["jobs"]) == len(sample.jobs) and new["id"] != "test"
    with TestClient(create_app(path, seed=False)) as reopened:
        assert reopened.get(f"/api/plans/{p['id']}").json()["routes"] == p["routes"]
        assert len(reopened.get("/api/datasets").json()) == 2


def test_bad_file_limits_and_structure(sample, tmp_path):
    with TestClient(create_app(tmp_path / "files.sqlite", seed=False)) as client:
        assert (
            client.post(
                "/api/datasets/import", files={"file": ("huge.csv", b"a" * (5 * 1024 * 1024 + 1))}
            ).status_code
            == 413
        )
        assert (
            client.post("/api/datasets/import", files={"file": ("invalid.json", b"not-json")}).status_code
            == 422
        )
        ds = sample.model_dump()
        ds["jobs"][0]["window_end"] = ds["jobs"][0]["window_start"] - 1
        assert (
            client.post(
                "/api/datasets/import", files={"file": ("invalid.json", json.dumps(ds).encode())}
            ).status_code
            == 422
        )


def test_local_security_headers_and_cross_site_write_block(sample, tmp_path):
    app = create_app(tmp_path / "security.sqlite", seed=False)
    app.state.storage.save_dataset(sample.model_dump())
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        for origin in ("https://foreign.example", "null", "http://localhost.attacker.example", "http://["):
            assert (
                client.post(
                    "/api/plans/optimize", json={"dataset_id": "test"}, headers={"origin": origin}
                ).status_code
                == 403
            )
        assert (
            client.post(
                "/api/plans/optimize",
                json={"dataset_id": "test"},
                headers={"origin": "http://localhost:3000"},
            ).status_code
            == 200
        )
        assert client.get("/api/datasets", headers={"host": "foreign.example"}).status_code == 400


def test_backup_includes_wal_and_refuses_overwrite(sample, tmp_path):
    backup = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "backup_database.py"))[
        "backup_database"
    ]
    source, destination = tmp_path / "live.sqlite", tmp_path / "backup.sqlite"
    store = Storage(source)
    # Keep a connection alive so committed transactions remain in the WAL file.
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        store.save_dataset(sample.model_dump())
        plan = build_plan(sample)
        store.save_plan(plan)
        backup(source, destination)
        restored = Storage(destination)
        assert restored.get_dataset("test") == sample.model_dump()
        assert restored.get_plan(plan["id"]) == plan
        with pytest.raises(FileExistsError):
            backup(source, destination)
        with pytest.raises(FileExistsError):
            backup(source, source)
        with pytest.raises(FileNotFoundError):
            backup(tmp_path / "missing.sqlite", tmp_path / "unused.sqlite")
    finally:
        connection.close()
