"""Copy source bytes once; capture hashes. Never writes to the supplied source directory."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "Обезличивание"


def main():
    target = ROOT / "data" / "raw"
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path in sorted(SOURCE.glob("*.csv")):
        content = path.read_bytes()
        dest = target / path.name
        if dest.exists() and dest.read_bytes() != content:
            raise RuntimeError(f"Existing raw copy differs: {path.name}")
        if not dest.exists():
            dest.write_bytes(content)
        rows = list(csv.DictReader(content.decode("cp1251").splitlines(), delimiter=";"))
        real = [r for r in rows if r["Заявка"].strip() and r["Заявка"].lower() != "адрес офиса"]
        manifest.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "rows": len(real),
                "unique_ids": len({r["Заявка"] for r in real}),
                "encoding": "cp1251",
                "delimiter": ";",
            }
        )
    (ROOT / "data" / "sources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
