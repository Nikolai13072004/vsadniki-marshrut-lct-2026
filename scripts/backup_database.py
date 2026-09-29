"""Create a consistent SQLite snapshot, including committed WAL transactions."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Database not found: {source}")
    if source == destination or destination.exists():
        raise FileExistsError("Choose a new backup filename; existing files are never overwritten")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        original.execute("PRAGMA schema_version").fetchone()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.touch(exist_ok=False)
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed; do not use this snapshot")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    print(backup_database(arguments.source, arguments.destination))
