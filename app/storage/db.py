"""Zapis gier i tur do SQLite. To surowe dane do wszystkich metryk."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.core.schemas import TurnRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    world_id        TEXT NOT NULL,
    model           TEXT NOT NULL,
    history         TEXT NOT NULL,
    memory_window   INTEGER NOT NULL,
    state_in_prompt INTEGER NOT NULL,
    temperature     REAL NOT NULL,
    seed            INTEGER,
    prompt_version  TEXT NOT NULL,
    config          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    run_id            TEXT NOT NULL REFERENCES runs(run_id),
    t                 INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    player_action     TEXT NOT NULL,
    prompt            TEXT NOT NULL,
    raw_output        TEXT NOT NULL,
    json_ok_first_try INTEGER NOT NULL,
    retries           INTEGER NOT NULL,
    tokens_in         INTEGER NOT NULL,
    tokens_out        INTEGER NOT NULL,
    latency_ms        REAL NOT NULL,
    narration         TEXT,
    dialogue          TEXT,
    location_id       TEXT,
    location          TEXT NOT NULL,
    scene_description TEXT,
    state_updates     TEXT,
    rejected_updates  TEXT NOT NULL,
    state_after       TEXT NOT NULL,
    error             TEXT,
    PRIMARY KEY (run_id, t)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_run(self, run_id: str, config: dict) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, _now(), config["mode"], config["world_id"], config["model"],
                 config["history"], config["memory_window"], int(config["state_in_prompt"]),
                 config["temperature"], config["seed"], config["prompt_version"], _json(config)),
            )

    def save_turn(self, run_id: str, rec: TurnRecord) -> None:
        r = rec.response
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, rec.t, _now(), rec.player_action, _json(rec.prompt), rec.raw_output,
                 int(rec.json_ok_first_try), rec.retries, rec.tokens_in, rec.tokens_out,
                 rec.latency_ms,
                 r.narration if r else None,
                 _json([d.model_dump() for d in r.dialogue]) if r else None,
                 r.scene.location_id if r else None,
                 rec.location,
                 r.scene.description if r else None,
                 _json([u.model_dump() for u in r.state_updates]) if r else None,
                 _json([x.model_dump() for x in rec.rejected_updates]),
                 _json([f.model_dump() for f in rec.state_after]),
                 rec.error),
            )

    def turns(self, run_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM turns WHERE run_id = ? ORDER BY t", (run_id,))
            return [dict(row) for row in rows]
