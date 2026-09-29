"""Rebuild the comparison for the three supplied regional datasets."""

import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Dataset  # noqa: E402
from app.planner import build_plan  # noqa: E402
from app.storage import Storage  # noqa: E402

SOURCES = ROOT / "data" / "normalized"
OUTPUT = ROOT / "data" / "reports" / "region_report.json"
CODE_FILES = ("planner.py", "routing.py", "models.py")


def digest(path, *, normalize_lines=False):
    content = path.read_bytes()
    if normalize_lines:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def report_row(path, storage):
    dataset = Dataset.model_validate_json(path.read_text(encoding="utf-8"))
    raw_input = ROOT / "data" / "raw" / dataset.source_files[0]
    if not raw_input.exists():
        raise FileNotFoundError(raw_input)
    baseline = build_plan(dataset, "baseline", storage)
    optimized = build_plan(dataset, "optimized", storage)
    return {
        "dataset_id": dataset.id,
        "name": dataset.name,
        "region": dataset.region,
        "jobs": len(dataset.jobs),
        "engineers": len(dataset.engineers),
        "source_file": path.name,
        "source_sha256": digest(path, normalize_lines=True),
        "raw_input_file": raw_input.name,
        "raw_input_sha256": digest(raw_input),
        "settings": {
            "seed": dataset.settings.seed,
            "time_limit_seconds": dataset.settings.time_limit_seconds,
            "solution_limit": dataset.settings.solution_limit,
            "routing_provider": dataset.settings.routing_provider,
        },
        "baseline": {
            "metrics": baseline["metrics"],
            "status": baseline["status"],
            "calculation_seconds": baseline["calculation_seconds"],
        },
        "optimized": {
            "metrics": optimized["metrics"],
            "status": optimized["status"],
            "calculation_seconds": optimized["calculation_seconds"],
        },
    }


def main():
    paths = sorted(SOURCES.glob("0[1-3]-*.json"))
    if len(paths) != 3:
        raise SystemExit("Ожидались три подготовленных региональных набора")
    with tempfile.TemporaryDirectory(prefix="routing-report-") as temporary:
        storage = Storage(Path(temporary) / "report.sqlite")
        rows = [report_row(path, storage) for path in paths]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_sha256": {
            name: digest(ROOT / "backend" / "app" / name, normalize_lines=True) for name in CODE_FILES
        },
        "note": (
            "Заявки взяты из предоставленных CSV. Профили инженеров и часть ограничений "
            "подготовлены как синтетические допущения. Базовый алгоритм - простое назначение "
            "в порядке строк, не историческое контрольное распределение."
        ),
        "regions": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        before = row["baseline"]["metrics"]
        after = row["optimized"]["metrics"]
        print(f"{row['dataset_id']}: {before['assigned']} / {after['assigned']} из {row['jobs']} заявок")
    print(f"Report: {OUTPUT}")


if __name__ == "__main__":
    main()
