"""Stanowisko pomiaru spójności obrazów (bench/images/consistency) na modelu na niby, bez GPU."""

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent / "bench" / "images" / "consistency"
sys.path.insert(0, str(BENCH))

import report
from models import FakeAdapter
from run import load_testset, run

TS = load_testset(BENCH / "testset.yaml")


def play(out: Path, fake: FakeAdapter, **kwargs):
    return run(TS, ["fake"], [1001], ["text", "anchor", "chain"], out, adapters={"fake": fake}, log=lambda _: None,
               **kwargs)


def records(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]


def test_runs_anchors_then_all_variants(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=4)
    rows = records(tmp_path)
    anchors = [r for r in rows if r["kind"] == "anchor"]
    assert len(anchors) == len(TS["characters"]) + len(TS["locations"])
    assert len(rows) == len(anchors) + 3 * 4
    text = [r for r in rows if r.get("variant") == "text"]
    assert all(r["refs"] == [] for r in text)
    assert all((tmp_path / r["path"]).exists() for r in rows)


def test_anchor_uses_references_and_chain_uses_previous_images(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=3)
    rows = {(r.get("variant"), r.get("scene")): r for r in records(tmp_path)}
    # scena 3: rynek z Arenem i strażnikiem; Aren i rynek byli już w scenie 2
    anchor3, chain3 = rows[("anchor", 3)], rows[("chain", 3)]
    assert anchor3["refs"] == ["fake/seed1001/anchors/aren.png", "fake/seed1001/anchors/guard.png",
                               "fake/seed1001/anchors/market.png"]
    assert chain3["refs"] == ["fake/seed1001/chain/scene02.png", "fake/seed1001/anchors/guard.png",
                              "fake/seed1001/chain/scene02.png"]
    assert chain3["k"] == {"aren": 3, "guard": 1, "market": 2}


def test_rerun_skips_finished_images(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=2)
    second = FakeAdapter()
    play(tmp_path, second, n_scenes=3)
    # dochodzi tylko scena 3 w każdym wariancie
    assert len(second.calls) == 3
    keys = [r["key"] for r in records(tmp_path)]
    assert len(keys) == len(set(keys))


def test_report_renders_without_scores(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=2)
    page = report.build(tmp_path)
    assert "Czas i pamięć" in page and "fake/seed1001/chain/scene02.png" in page
    assert "uruchom score.py" in page
