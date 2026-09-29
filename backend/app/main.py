import csv
import hashlib
import io
import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .importer import apply_defaults, configured_priority, import_csv, normalize_address, validation_issues
from .events import apply_event, assign_manually
from .models import Dataset, DatasetPatch, EventRequest, ManualRequest, PlanRequest, PreviewConfirmRequest
from .planner import build_plan, diff_plans
from .storage import DATA, Storage


def migrate_seed_dataset(existing, source):
    """Refresh bundled fixtures while keeping explicit edits and local assumptions."""
    current = Dataset.model_validate(existing)
    updated = Dataset.model_validate(source)
    bundled_settings = updated.settings
    updated.settings = current.settings
    updated.settings.requirements_version = bundled_settings.requirements_version
    updated.settings.normative_durations = bundled_settings.normative_durations
    updated.settings.normative_service_durations = bundled_settings.normative_service_durations
    updated.settings.normative_travel_mode = bundled_settings.normative_travel_mode
    updated.settings.demo_urgent_duration = bundled_settings.demo_urgent_duration
    updated.settings.demo_urgent_window = bundled_settings.demo_urgent_window
    updated.settings.equipment_enabled = bundled_settings.equipment_enabled
    updated.settings.equipment_catalog = bundled_settings.equipment_catalog
    updated.settings.equipment_by_work_type = bundled_settings.equipment_by_work_type
    updated.revision = current.revision + 1

    old_jobs = {job.id: job for job in current.jobs}
    for job in updated.jobs:
        old = old_jobs.get(job.id)
        if old:
            for field in old.manual_fields:
                setattr(job, field, getattr(old, field))
            job.manual_fields = list(dict.fromkeys([*job.manual_fields, *old.manual_fields]))

    old_engineers = {engineer.id: engineer for engineer in current.engineers}
    for engineer in updated.engineers:
        old = old_engineers.get(engineer.id)
        if old:
            for field in old.manual_fields:
                setattr(engineer, field, getattr(old, field))
            engineer.manual_fields = list(dict.fromkeys([*engineer.manual_fields, *old.manual_fields]))
    return apply_defaults(updated)


def create_app(database_path=None, seed=True):
    storage = Storage(database_path)
    calculation_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        if seed:
            for path in sorted((DATA / "normalized").glob("*.json")):
                body = json.loads(path.read_text(encoding="utf-8"))
                existing = storage.get_dataset(body["id"])
                if existing is None:
                    storage.save_dataset(Dataset.model_validate(body).model_dump())
                elif (
                    existing.get("settings", {}).get("requirements_version", 1)
                    < body["settings"]["requirements_version"]
                ):
                    dataset = migrate_seed_dataset(existing, body)
                    storage.save_dataset(dataset.model_dump())
        for body in storage.list_datasets():
            if body.get("settings", {}).get("requirements_version", 1) >= 8:
                continue
            dataset = Dataset.model_validate(body)
            for job in dataset.jobs:
                if "priority" not in job.manual_fields and job.provenance.get("priority") == "configured":
                    job.priority = configured_priority(job.bk_type, job.work_type)
            dataset.settings.requirements_version = 8
            dataset.revision += 1
            storage.save_dataset(dataset.model_dump(), body["revision"])
        yield

    app = FastAPI(title="Маршрут - сервис диспетчера", version="1.0.0", lifespan=lifespan)
    app.state.storage = storage

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]} for e in exc.errors()
                ]
            },
        )

    @app.exception_handler(ValueError)
    async def domain_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)[:1200]})

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logging.getLogger("routing").error("Request failed: %s", type(exc).__name__)
        # Do not expose paths, stack traces, database internals or secrets.
        return JSONResponse(
            status_code=500,
            content={"detail": "Расчёт не завершён. Предыдущий план сохранён. Повторите операцию."},
        )

    @app.middleware("http")
    async def secure_headers(request, call_next):
        if request.url.hostname not in {"localhost", "127.0.0.1", "::1", "api", "testserver"}:
            return JSONResponse(status_code=400, content={"detail": "Недопустимый адрес локального сервиса"})
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            try:
                parsed = urlsplit(origin)
                trusted = parsed.scheme in {"http", "https"} and parsed.hostname in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }
            except ValueError:
                trusted = False
            if not trusted:
                return JSONResponse(
                    status_code=403, content={"detail": "Изменение данных со стороннего сайта запрещено"}
                )
        length = request.headers.get("content-length", "0")
        if length.isdigit() and int(length) > 6 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"detail": "Максимальный размер файла - 5 МБ"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def dataset(identifier):
        body = storage.get_dataset(identifier)
        if body is None:
            raise HTTPException(404, "Набор данных не найден")
        return Dataset.model_validate(body)

    def plan(identifier):
        body = storage.get_plan(identifier)
        if body is None:
            raise HTTPException(404, "План не найден")
        return body

    def checked(ds):
        issues = validation_issues(ds)
        if any(i.severity == "error" for i in issues):
            raise HTTPException(
                422,
                {"message": "Исправьте ошибки данных до расчёта", "issues": [i.model_dump() for i in issues]},
            )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "database": "sqlite", "version": "1.0.0"}

    @app.get("/api/reports/regions")
    def region_report():
        path = DATA / "reports" / "region_report.json"
        if not path.exists():
            raise HTTPException(503, "Отчёт ещё не рассчитан")
        report = json.loads(path.read_text(encoding="utf-8"))
        for name, expected in report["code_sha256"].items():
            source_code = Path(__file__).with_name(name)
            if (
                not source_code.exists()
                or hashlib.sha256(source_code.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected
            ):
                raise HTTPException(503, "Алгоритм изменился. Пересчитайте отчёт")
        for row in report["regions"]:
            source = DATA / "normalized" / row["source_file"]
            raw_input = DATA / "raw" / row["raw_input_file"]
            if (
                not source.exists()
                or hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                != row["source_sha256"]
            ):
                raise HTTPException(503, "Исходный набор изменился. Пересчитайте отчёт")
            if (
                not raw_input.exists()
                or hashlib.sha256(raw_input.read_bytes()).hexdigest() != row["raw_input_sha256"]
            ):
                raise HTTPException(503, "Исходный CSV изменился. Пересчитайте отчёт")
        return report

    @app.get("/api/datasets")
    def list_datasets():
        return [
            {
                "id": d["id"],
                "name": d["name"],
                "region": d["region"],
                "date": d["date"],
                "revision": d["revision"],
                "jobs_count": len(d["jobs"]),
                "engineers_count": len(d["engineers"]),
            }
            for d in storage.list_datasets()
        ]

    @app.get("/api/datasets/{identifier}")
    def get_dataset(identifier: str):
        ds = dataset(identifier)
        return {**ds.model_dump(), "validation": [i.model_dump() for i in validation_issues(ds)]}

    @app.post("/api/datasets/import", status_code=201)
    async def import_data(
        file: UploadFile = File(...),
        region: str = Form("Импорт"),
        encoding: str | None = Form(None),
        delimiter: str | None = Form(None),
    ):
        name = (file.filename or "dataset").replace("\\", "/").split("/")[-1][:200]
        if Path(name).suffix.lower() not in (".csv", ".json"):
            raise HTTPException(415, "Разрешены только CSV и JSON")
        raw = await file.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(413, "Максимальный размер файла - 5 МБ")
        if name.lower().endswith(".json"):
            try:
                body = json.loads(raw.decode("utf-8-sig"))
                body = body.get("snapshot", body)
                body["id"] = str(uuid.uuid4())
                body["revision"] = 1
                ds = Dataset.model_validate(body)
            except (ValueError, TypeError, AttributeError) as error:
                raise HTTPException(
                    422, "JSON не соответствует схеме Dataset: " + str(error)[:500]
                ) from error
        else:
            geo_path = DATA / "geocodes.json"
            geo = json.loads(geo_path.read_text(encoding="utf-8")) if geo_path.exists() else {}
            ds = import_csv(raw, name, region, geo, encoding=encoding or None, delimiter=delimiter or None)
        storage.save_upload(ds.id, name, hashlib.sha256(raw).hexdigest(), raw)
        storage.save_dataset(ds.model_dump())
        return {**ds.model_dump(), "validation": [i.model_dump() for i in validation_issues(ds)]}

    @app.patch("/api/datasets/{identifier}")
    def patch_dataset(identifier: str, patch: DatasetPatch):
        ds = dataset(identifier)
        original = ds.model_dump()
        updates = patch.model_dump(exclude_unset=True, exclude={"revision", "apply_defaults"})
        ds = Dataset.model_validate({**original, **updates, "revision": ds.revision + 1})
        previous_jobs = {item["id"]: item for item in original["jobs"]}
        for job in ds.jobs:
            old = previous_jobs.get(job.id)
            if not old or not job.location:
                continue
            address_changed = (
                normalize_address(old["address"]).casefold() != normalize_address(job.address).casefold()
            )
            coordinates_unchanged = old["location"] == job.location.model_dump()
            location_not_confirmed = old["geo_quality"] == job.geo_quality and old["geo_note"] == job.geo_note
            if address_changed and coordinates_unchanged and location_not_confirmed:
                raise HTTPException(
                    422,
                    f"Адрес заявки {job.source_id} изменён, но координаты остались прежними. "
                    "Укажите координаты нового адреса или подтвердите прежнюю точку в примечании к геокодированию.",
                )
        for collection in ("jobs", "engineers"):
            previous = {item["id"]: item for item in original[collection]}
            for item in getattr(ds, collection):
                old = previous.get(item.id)
                if old:
                    for field, value in item.model_dump(exclude={"provenance", "manual_fields"}).items():
                        if old.get(field) != value:
                            item.provenance[field] = "configured"
                            if field not in item.manual_fields:
                                item.manual_fields.append(field)
        if patch.apply_defaults:
            ds = Dataset.model_validate(apply_defaults(ds).model_dump())
        storage.save_dataset(ds.model_dump(), patch.revision)
        return {**ds.model_dump(), "validation": [i.model_dump() for i in validation_issues(ds)]}

    def calculate(request, mode):
        ds = dataset(request.dataset_id)
        if request.settings:
            ds.settings = request.settings
        if request.variant == "thorough":
            ds.settings.solution_limit = min(1000, ds.settings.solution_limit * 3)
        checked(ds)
        key = hashlib.sha256(
            json.dumps(
                {"dataset": ds.model_dump(), "mode": mode, "variant": request.variant, "solver_version": 4},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = storage.cached_plan(key, ds.id, ds.revision)
        if cached:
            return {**cached, "cached": True}
        if not calculation_lock.acquire(blocking=False):
            raise HTTPException(409, "Другой расчёт уже выполняется. Дождитесь его завершения")
        try:
            result = build_plan(ds, mode, storage)
            result["variant"] = request.variant
            storage.save_plan(result, key)
            return result
        finally:
            calculation_lock.release()

    @app.post("/api/plans/baseline")
    def baseline(request: PlanRequest):
        return calculate(request, "baseline")

    @app.post("/api/plans/optimize")
    def optimize(request: PlanRequest):
        return calculate(request, "optimized")

    @app.get("/api/plans")
    def list_plans(dataset_id: str):
        return [
            {
                key: p[key]
                for key in (
                    "id",
                    "mode",
                    "version",
                    "parent_id",
                    "status",
                    "metrics",
                    "dataset_revision",
                    "event",
                )
            }
            for p in storage.list_plans(dataset_id)
        ]

    @app.get("/api/plans/{identifier}")
    def get_plan(identifier: str):
        return plan(identifier)

    @app.post("/api/plans/{identifier}/events")
    def event_plan(identifier: str, event: EventRequest):
        parent = plan(identifier)
        if not calculation_lock.acquire(blocking=False):
            raise HTTPException(409, "Расчёт уже выполняется")
        try:
            result = apply_event(parent, event, storage)
            storage.save_plan(result)
            return result
        finally:
            calculation_lock.release()

    @app.post("/api/plans/{identifier}/events/preview")
    def preview_event(identifier: str, event: EventRequest):
        parent = plan(identifier)
        if not calculation_lock.acquire(blocking=False):
            raise HTTPException(409, "Расчёт уже выполняется")
        try:
            result = apply_event(parent, event, storage)
            storage.save_preview(result)
            return result
        finally:
            calculation_lock.release()

    @app.post("/api/plans/{identifier}/events/confirm")
    def confirm_event(identifier: str, request: PreviewConfirmRequest):
        plan(identifier)
        return storage.confirm_preview(request.preview_id, identifier)

    @app.post("/api/plans/{identifier}/manual")
    def manual_plan(identifier: str, request: ManualRequest):
        parent = plan(identifier)
        if not calculation_lock.acquire(blocking=False):
            raise HTTPException(409, "Расчёт уже выполняется")
        try:
            result = assign_manually(parent, request, storage)
            storage.save_plan(result)
            return result
        finally:
            calculation_lock.release()

    @app.get("/api/plans/{identifier}/compare")
    def compare(identifier: str, other_id: str | None = None):
        current = plan(identifier)
        target = other_id or current["parent_id"]
        if not target:
            raise HTTPException(422, "Укажите план для сравнения")
        other = plan(target)
        if current["dataset_id"] != other["dataset_id"]:
            raise HTTPException(422, "Сравнивайте планы одного набора")
        return {
            "before": other["metrics"],
            "after": current["metrics"],
            "delta": {
                key: current["metrics"][key] - other["metrics"].get(key, 0) for key in current["metrics"]
            },
            "changes": diff_plans(other, current),
            "same_inputs": current["snapshot"] == other["snapshot"],
        }

    @app.get("/api/plans/{identifier}/export")
    def export(identifier: str, format: str = Query("json", pattern="^(json|csv)$")):
        result = plan(identifier)
        headers = {"Content-Disposition": f'attachment; filename="plan-{identifier}.{format}"'}
        if format == "json":
            return Response(
                json.dumps(result, ensure_ascii=False, indent=2),
                media_type="application/json",
                headers=headers,
            )
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(
            [
                "job_id",
                "source_id",
                "address",
                "engineer",
                "order",
                "arrival",
                "start",
                "finish",
                "travel_minutes",
                "distance_km",
                "status",
                "reasons",
                "total_distance_km",
                "engineers_used",
                "provenance",
            ]
        )
        jobs = {j["id"]: j for j in result["snapshot"]["jobs"]}

        def safe(value):
            text = str(value)
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

        for route in result["routes"]:
            for order, stop in enumerate(route["stops"], 1):
                job = jobs[stop["job_id"]]
                from .planner import hhmm

                writer.writerow(
                    [
                        safe(job["id"]),
                        safe(job["source_id"]),
                        safe(job["address"]),
                        safe(route["engineer_name"]),
                        order,
                        hhmm(stop["arrival"]),
                        hhmm(stop["start"]),
                        hhmm(stop["finish"]),
                        stop["travel_minutes"],
                        stop["distance_m"] / 1000,
                        stop.get("status", "assigned"),
                        "",
                        result["metrics"]["distance_m"] / 1000,
                        result["metrics"]["engineers_used"],
                        json.dumps(job["provenance"], ensure_ascii=False),
                    ]
                )
        for item in result["unassigned"]:
            job = jobs[item["job_id"]]
            writer.writerow(
                [
                    safe(job["id"]),
                    safe(job["source_id"]),
                    safe(job["address"]),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "unassigned",
                    safe("; ".join(item["reasons"])),
                    result["metrics"]["distance_m"] / 1000,
                    result["metrics"]["engineers_used"],
                    json.dumps(job["provenance"], ensure_ascii=False),
                ]
            )
        return Response(
            output.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers=headers
        )

    return app


app = create_app()
