"""Stanowisko pomiaru spójności obrazów (bench/images/consistency) na modelu na niby, bez GPU."""

import csv
import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench" / "images" / "consistency"
sys.path.insert(0, str(BENCH))

import report
import score
from compose import FakeComposer
from models import FakeAdapter
from run import VARIANTS, load_testset, run

TS = load_testset(BENCH / "testset.yaml")


def play(out: Path, fake: FakeAdapter, composer: FakeComposer | None = None, **kwargs):
    return run(TS, ["fake"], [1001], list(VARIANTS), out, adapters={"fake": fake},
               composer=composer or FakeComposer(), log=lambda _: None, **kwargs)


def records(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]


def test_testset_has_long_story_with_returns():
    scenes = TS["scenes"]
    assert len(scenes) >= 20
    assert all("aren" in s["characters"] for s in scenes)
    assert {(i + 1, s["return_of"]) for i, s in enumerate(scenes) if "return_of" in s} >= {(20, 1)}


def test_return_must_repeat_the_scene(tmp_path):
    bad = TS | {"scenes": [*TS["scenes"][:2], {**TS["scenes"][1], "action": "inna akcja", "return_of": 1}]}
    path = tmp_path / "ts.yaml"
    import yaml
    path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_testset(path)


def test_runs_anchors_then_all_variants(tmp_path):
    fake, composer = FakeAdapter(), FakeComposer()
    play(tmp_path, fake, composer, n_scenes=4)
    rows = records(tmp_path)
    anchors = [r for r in rows if r["kind"] == "anchor"]
    assert len(anchors) == len(TS["characters"]) + len(TS["locations"])
    scenes = [r for r in rows if r["kind"] == "scene"]
    assert len(scenes) == len(VARIANTS) * 4
    sprites = [r for r in rows if r["kind"] == "sprite"]
    assert len(sprites) == sum(len(s["characters"]) for s in TS["scenes"][:4])
    assert len(composer.calls) == 4
    assert all(r["refs"] == [] for r in scenes if r["variant"] == "text")
    assert all((tmp_path / r["path"]).exists() for r in rows)


def test_each_scene_has_its_own_seed_same_across_variants(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=3)
    rows = [r for r in records(tmp_path) if r["kind"] == "scene" and r["variant"] != "layers"]
    seeds = {(r["variant"], r["scene"]): r["image_seed"] for r in rows}
    assert len({seeds[("text", i)] for i in (1, 2, 3)}) == 3
    assert seeds[("text", 2)] == seeds[("anchor", 2)] == seeds[("chain", 2)]


def test_anchor_uses_references_and_chain_uses_previous_images(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=3)
    rows = {(r.get("variant"), r.get("scene"), r["kind"]): r for r in records(tmp_path)}
    # scena 3: rynek z Arenem i strażnikiem; Aren i rynek byli już w scenie 2
    anchor3, chain3 = rows[("anchor", 3, "scene")], rows[("chain", 3, "scene")]
    assert anchor3["refs"] == ["fake/seed1001/anchors/aren.png", "fake/seed1001/anchors/guard.png",
                               "fake/seed1001/anchors/market.png"]
    assert chain3["refs"] == ["fake/seed1001/chain/scene02.png", "fake/seed1001/anchors/guard.png",
                              "fake/seed1001/chain/scene02.png"]
    assert chain3["k"] == {"aren": 3, "guard": 1, "market": 2}


def test_layers_uses_location_anchor_as_background_and_character_anchors_for_sprites(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=3)
    rows = records(tmp_path)
    sprites = [r for r in rows if r["kind"] == "sprite" and r["scene"] == 3]
    assert [r["refs"] for r in sprites] == [["fake/seed1001/anchors/aren.png"], ["fake/seed1001/anchors/guard.png"]]
    scene = next(r for r in rows if r["kind"] == "scene" and r["variant"] == "layers" and r["scene"] == 3)
    assert scene["refs"][0] == "fake/seed1001/anchors/market.png"
    assert scene["seconds_total"] >= scene["seconds"]


def test_rerun_skips_finished_images(tmp_path):
    play(tmp_path, FakeAdapter(), n_scenes=2)
    second, composer = FakeAdapter(), FakeComposer()
    play(tmp_path, second, composer, n_scenes=3)
    # dochodzi tylko scena 3: po jednym obrazie w 3 wariantach i 2 postacie w layers
    assert len(second.calls) == 3 + 2
    assert len(composer.calls) == 1
    keys = [r["key"] for r in records(tmp_path)]
    assert len(keys) == len(set(keys))


def test_assign_matches_crops_to_characters():
    # 2 postacie, 3 wycinki: postać 0 najbardziej podobna do wycinka 2, postać 1 do wycinka 0
    assert score.assign([[0.1, 0.2, 0.9], [0.8, 0.1, 0.3]]) == {0: 2, 1: 0}
    # mniej wycinków niż postaci: jedna postać zostaje bez wycinka
    assert score.assign([[0.9], [0.5]]) == {0: 0}


def test_nms_drops_overlapping_boxes():
    boxes = [(0.9, [0, 0, 10, 10]), (0.8, [1, 1, 10, 10]), (0.7, [20, 20, 30, 30])]
    assert score.nms(boxes) == [[0, 0, 10, 10], [20, 20, 30, 30]]


def test_report_renders_with_and_without_scores(tmp_path):
    play(tmp_path, FakeAdapter())
    page = report.build(tmp_path)
    assert "Czas i pamięć" in page and "uruchom score.py" in page
    assert "Runda 1 i runda 20" in page
    rows = [{"model": "fake", "variant": "anchor", "seed": 1001, "scene": 20, "entity": "aren",
             "entity_kind": "character", "k": 20, "detected": 1, "dino_anchor": 0.8, "clip_anchor": 0.9,
             "dino_first": 0.7, "clip_first": 0.8, "clipscore": 30, "seconds": 1, "vram_peak_gb": 0}]
    with (tmp_path / "scores.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    page = report.build(tmp_path)
    assert "Postać w kolejnych rundach" in page and "0.700" in page


def test_short_game_returns_to_first_scene(tmp_path):
    short = load_testset(BENCH / "testset_short.yaml")
    run(short, ["fake"], [1001], list(VARIANTS), tmp_path, adapters={"fake": FakeAdapter()},
        composer=FakeComposer(), log=lambda _: None)
    rows = records(tmp_path)
    assert len(rows) == 39  # 33 obrazy z modelu i 6 scen złożonych z warstw
    assert {r["scene"] for r in rows if r.get("return_of") == 1 and r["kind"] == "scene"} == {6}
    assert "Runda 1 i runda 6" in report.build(tmp_path)
