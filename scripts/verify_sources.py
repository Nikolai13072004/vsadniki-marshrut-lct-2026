"""Verify shipped raw copies and original files when they remain alongside the project."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
    checked = 0
    for item in manifest:
        candidates = [ROOT / "data" / "raw" / item["file"]]
        original = ROOT.parent / "Обезличивание" / item["file"]
        if original.exists():
            candidates.append(original)
        for path in candidates:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise RuntimeError(f"Hash mismatch: {path.name}")
            checked += 1
    print(f"OK: {checked} source files checked; all bytes unchanged.")


if __name__ == "__main__":
    main()
