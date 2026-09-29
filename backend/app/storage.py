import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


class Storage:
    def __init__(self, path=None):
        self.path = str(path or os.environ.get("DATABASE_PATH", ROOT / "output" / "routing.sqlite"))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, cache_key TEXT, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plan_previews (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, created_at REAL NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS plans_dataset ON plans(dataset_id);
                CREATE INDEX IF NOT EXISTS plans_cache ON plans(cache_key);
                CREATE TABLE IF NOT EXISTS matrices (key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS raw_uploads (id TEXT PRIMARY KEY, filename TEXT, sha256 TEXT, content BLOB);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_dataset(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT body FROM datasets WHERE id=?", (identifier,)).fetchone()
        return json.loads(row["body"]) if row else None

    def save_dataset(self, body, expected_revision=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected_revision is not None:
                row = db.execute("SELECT body FROM datasets WHERE id=?", (body["id"],)).fetchone()
                if not row or json.loads(row["body"])["revision"] != expected_revision:
                    raise ValueError("Набор уже изменён. Обновите страницу и повторите правку")
            db.execute(
                "INSERT INTO datasets VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (body["id"], json.dumps(body, ensure_ascii=False)),
            )

    def list_datasets(self):
        with self.connect() as db:
            return [json.loads(row["body"]) for row in db.execute("SELECT body FROM datasets ORDER BY rowid")]

    def save_plan(self, plan, key=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_dataset_revision(db, plan)
            db.execute(
                "INSERT INTO plans VALUES (?,?,?,?)",
                (plan["id"], plan["dataset_id"], key, json.dumps(plan, ensure_ascii=False)),
            )

    def save_preview(self, plan):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_dataset_revision(db, plan)
            db.execute("DELETE FROM plan_previews WHERE created_at < ?", (time.time() - 1800,))
            db.execute(
                "INSERT INTO plan_previews VALUES (?,?,?,?)",
                (plan["id"], plan["parent_id"], time.time(), json.dumps(plan, ensure_ascii=False)),
            )

    @staticmethod
    def _check_dataset_revision(db, plan):
        row = db.execute("SELECT body FROM datasets WHERE id=?", (plan["dataset_id"],)).fetchone()
        if not row or json.loads(row["body"])["revision"] != plan["dataset_revision"]:
            raise ValueError("Набор данных изменился. Постройте план заново перед изменением дня")

    def confirm_preview(self, preview_id, parent_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body, created_at FROM plan_previews WHERE id=? AND parent_id=?",
                (preview_id, parent_id),
            ).fetchone()
            if not row or row["created_at"] < time.time() - 1800:
                raise ValueError("Предпросмотр устарел. Рассчитайте его ещё раз")
            preview = json.loads(row["body"])
            current = db.execute("SELECT body FROM datasets WHERE id=?", (preview["dataset_id"],)).fetchone()
            if not current or json.loads(current["body"])["revision"] != preview["dataset_revision"]:
                raise ValueError("Данные изменились после предпросмотра. Рассчитайте план ещё раз")
            db.execute(
                "INSERT INTO plans VALUES (?,?,?,?)",
                (preview["id"], preview["dataset_id"], None, row["body"]),
            )
            db.execute("DELETE FROM plan_previews WHERE id=?", (preview_id,))
            return preview

    def get_plan(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT body FROM plans WHERE id=?", (identifier,)).fetchone()
        return json.loads(row["body"]) if row else None

    def cached_plan(self, key, dataset_id=None, revision=None):
        with self.connect() as db:
            if dataset_id is not None:
                self._check_dataset_revision(db, {"dataset_id": dataset_id, "dataset_revision": revision})
            row = db.execute(
                "SELECT body FROM plans WHERE cache_key=? ORDER BY rowid DESC LIMIT 1", (key,)
            ).fetchone()
        return json.loads(row["body"]) if row else None

    def list_plans(self, dataset_id):
        with self.connect() as db:
            return [
                json.loads(r["body"])
                for r in db.execute(
                    "SELECT body FROM plans WHERE dataset_id=? ORDER BY rowid DESC", (dataset_id,)
                )
            ]

    def matrix(self, key):
        with self.connect() as db:
            row = db.execute("SELECT body FROM matrices WHERE key=?", (key,)).fetchone()
        return json.loads(row["body"]) if row else None

    def save_matrix(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO matrices VALUES (?,?)", (key, json.dumps(value)))

    def save_upload(self, identifier, filename, digest, content):
        with self.connect() as db:
            db.execute("INSERT INTO raw_uploads VALUES (?,?,?,?)", (identifier, filename, digest, content))
