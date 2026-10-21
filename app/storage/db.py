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
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id           TEXT PRIMARY KEY REFERENCES runs(run_id),
    config_key       TEXT NOT NULL,
    scenario_id      TEXT NOT NULL,
    scenario_version INTEGER NOT NULL,
    rep              INTEGER NOT NULL,
    tag              TEXT NOT NULL,
    status           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    note             TEXT
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

    # --- Eksperymenty (app/eval) ---

    def create_eval_run(self, run_id: str, config_key: str, scenario_id: str, scenario_version: int,
                        rep: int, tag: str) -> None:
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO eval_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, config_key, scenario_id, scenario_version, rep, tag, "running", now, now, None),
            )

    def find_eval_run(self, config_key: str, rep: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM eval_runs WHERE config_key = ? AND rep = ?", (config_key, rep)
            ).fetchone()
            return dict(row) if row else None

    def set_eval_status(self, run_id: str, status: str, note: str | None = None) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE eval_runs SET status = ?, note = ?, updated_at = ? WHERE run_id = ?",
                (status, note, _now(), run_id),
            )

    def eval_runs(self, scenario_id: str | None = None, tag: str | None = None) -> list[dict]:
        """Uruchomienia eksperymentów razem z konfiguracją gry."""
        query = ("SELECT e.*, r.model, r.history, r.memory_window, r.state_in_prompt, r.temperature, "
                 "r.seed, r.prompt_version, r.config FROM eval_runs e JOIN runs r USING (run_id) WHERE 1=1")
        params: list = []
        if scenario_id:
            query += " AND e.scenario_id = ?"
            params.append(scenario_id)
        if tag is not None:
            query += " AND e.tag = ?"
            params.append(tag)
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(query + " ORDER BY e.started_at, e.rep", params)]
