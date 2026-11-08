"""Obrazy w trakcie gry, liczone na osobnym serwerze (bench/images/consistency/serve.py).

Trzy rodzaje obrazów:
- tło lokacji: jedno na lokację w grze, stały wzorzec miejsca, bez postaci,
- portret postaci: jeden na postać w grze, stały wzorzec jej wyglądu,
- scena tury: to, co dzieje się w tej turze, rysowane na podstawie tła i portretów.

Gra nie czeka na obraz: tura wraca od razu, a obrazy powstają w tle. Nieudane tło ponawiamy przy następnej
turze w tej lokacji. Bez adresu serwera (IMAGE_SERVER_URL) moduł jest wyłączony i gra działa jak wcześniej.
"""

import asyncio
import base64
import re
import time
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

APPEARANCE_ATTRIBUTES = ("wygląd", "znak szczególny")
PORTRAIT_ATTRIBUTES = (*APPEARANCE_ATTRIBUTES, "zawód")
MAX_PORTRAITS = 3  # FLUX.2 klein przyjmuje 4 obrazy wejściowe: tło i 3 postacie
MAX_SENTENCES = 2
# Zdania o tym, co ktoś mówi, FLUX rysuje jako dymki i napisy na obrazie (instrukcja „no text” nie pomaga),
# więc do promptu trafia tylko to, co widać. Sprawdzone na tych samych turach: z mową napisy 9 na 9 obrazów, bez 0 na 12.
SPEECH = re.compile(r"mówi|powiedz|pyta|odpowiad|odpowiedz|szepcz|szept|krzycz|\brzek[łl]|\brzecze|woła|\bprosi|"
                    r"zapyt|rozmaw|[?„”\":]", re.IGNORECASE)
TALKING = "The characters are talking to each other with natural gestures."
GOING_TOGETHER = re.compile(r"\b(?:razem|wspólnie|wraz)\b|\b\w+(?:imy|emy|amy|ymy)\b", re.IGNORECASE)


class ImageClient(Protocol):
    async def generate(self, prompt: str, seed: int, refs: Sequence[bytes] = (),
                       model: str | None = None) -> tuple[bytes, str]:
        """Zwraca plik PNG i nazwę modelu. refs to obrazy wejściowe (PNG), model to wybrany generator."""
        ...


class HttpImageClient:
    def __init__(self, base_url: str, timeout_s: float):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def generate(self, prompt: str, seed: int, refs: Sequence[bytes] = (),
                       model: str | None = None) -> tuple[bytes, str]:
        payload = {"prompt": prompt, "seed": seed, "refs": [base64.b64encode(r).decode() for r in refs],
                   "model": model}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(f"{self.base_url}/generate", json=payload)
            resp.raise_for_status()
        return resp.content, resp.headers.get("x-image-model", "")


@dataclass
class Job:
    game_id: str
    location: str
    t: int
    kind: str  # background albo scene
    url: str
    prompt: str
    seed: int
    path: Path
    after: list["Job"] = field(default_factory=list)  # obrazy wejściowe sceny: tło lokacji, potem portrety
    status: str = "pending"
    error: str | None = None
    task: asyncio.Task | None = None  # silna referencja, inaczej zadanie może zniknąć w trakcie


def location_seed(game_seed: int | None, location: str) -> int:
    """Stały seed lokacji: ta sama gra i lokacja dają zawsze ten sam seed."""
    return (game_seed or 0) + zlib.crc32(location.encode()) % 1_000_000


def character_key(name: str) -> str:
    """Zapis imienia niezależny od wielkości liter i znaków: „geralt_z_rivii” i „Geralt z Rivii” to ta sama postać."""
    return " ".join(re.sub(r"\W+", " ", name.lower()).replace("_", " ").split())


def present_characters(player: str, characters: Sequence[str]) -> list[str]:
    """Postacie obecne w scenie bez bohatera i bez powtórzeń, w kolejności od narratora."""
    skip = {"bohater", "ty", character_key(player.split(",")[0])}
    result: list[str] = []
    for name in characters:
        key = character_key(name)
        if key and key not in skip:
            skip.add(key)
            result.append(name)
    return result


def _looks(facts: list, entity: str, attributes: tuple[str, ...]) -> str:
    key = character_key(entity)
    return ", ".join(f.value for f in facts if character_key(f.entity) == key and f.attribute.lower() in attributes)


def _stem(name: str) -> str:
    """Początek pierwszego słowa nazwy, odporny na odmianę („Borwin” i „Borwinem”)."""
    word = character_key(name).split(" ")[0]
    return word[:max(4, len(word) - 2)]


def mentioned(name: str, text: str) -> bool:
    stem = _stem(name)
    return bool(stem) and re.search(rf"\b{re.escape(stem)}", text, re.IGNORECASE) is not None


class SceneCast:
    """Kto jest przy bohaterze. Tylko na potrzeby obrazów: narrator i jego dane się nie zmieniają.

    Narrator potrafi po zmianie lokacji dalej wymieniać osoby z poprzedniego miejsca. Dlatego po przejściu
    gracza te osoby zostają tam, gdzie były, chyba że komenda je wymienia albo mówi o pójściu razem.
    """

    def __init__(self, location: str):
        self.location = location
        self.present: set[str] = set()
        self.left: dict[str, str] = {}  # postać -> miejsce, w którym została

    def update(self, location: str, characters: Sequence[str], action: str) -> tuple[list[str], list[str]]:
        """Zwraca postacie widoczne w scenie i te, które zostały gdzie indziej."""
        if location != self.location and not GOING_TOGETHER.search(action):
            for key in self.present:
                self.left[key] = self.location
        visible, hidden = [], []
        for name in characters:
            key = character_key(name)
            if mentioned(name, action) or self.left.get(key) == location:
                self.left.pop(key, None)
            elif key in self.left:
                hidden.append(name)
                continue
            visible.append(name)
        self.location = location
        self.present = {character_key(name) for name in visible}
        return visible, hidden


def visual_text(action: str, narration: str, hidden: Sequence[str] = ()) -> str:
    """Działanie gracza i zdania narracji bez mowy i bez osób, których w scenie nie ma."""
    sentences = [s for s in re.split(r"(?<=[.!?…”\"])\s+", narration.strip())
                 if s and not SPEECH.search(s) and not any(mentioned(name, s) for name in hidden)]
    first = TALKING if SPEECH.search(action) else f"{action.strip().rstrip('.!…')}."
    return " ".join([first, *sentences[:MAX_SENTENCES]])


def scene_prompt(style: str, place: str, player: str, facts: Iterable, characters: Sequence[str], action: str,
                 narration: str, hidden: Sequence[str] = ()) -> str:
    """Opis sceny z danych tury. Postacie w tej samej kolejności, co ich portrety na wejściu modelu."""
    facts = list(facts)
    hero_look = _looks(facts, "bohater", APPEARANCE_ATTRIBUTES)
    people = [f"{player} ({hero_look})" if hero_look else player]
    for name in present_characters(player, characters):
        look = _looks(facts, name, APPEARANCE_ATTRIBUTES)
        shown = name.replace("_", " ")
        people.append(f"{shown} ({look})" if look else shown)
    return f"{style} {place}. {'; '.join(people)}. {visual_text(action, narration, hidden)}"


def portrait_prompt(style: str, name: str, facts: Iterable, entity: str | None = None) -> str:
    """Opis portretu postaci. entity to nazwa postaci w stanie świata, jeśli inna niż name."""
    details = _looks(list(facts), entity or name, PORTRAIT_ATTRIBUTES)
    shown = name.replace("_", " ")
    return f"{style} {shown} ({details})." if details else f"{style} {shown}."


class BackgroundImages:
    def __init__(self, client: ImageClient | None, root: str | Path, store=None, style: str = ""):
        self.client = client
        self.root = Path(root)
        self.store = store
        self.style = style
        self.jobs: dict[tuple[str, str], Job] = {}
        self.casts: dict[str, SceneCast] = {}
        self.models: dict[str, str] = {}  # gra -> generator wybrany przy jej tworzeniu

    def cast(self, game_id: str, start_location: str) -> SceneCast:
        return self.casts.setdefault(game_id, SceneCast(start_location))

    def _start(self, key: str, job: Job) -> None:
        self.jobs[(job.game_id, key)] = job
        job.task = asyncio.create_task(self._run(job))

    def request(self, game_id: str, location: str, description: str, game_seed: int | None, t: int) -> None:
        """Zamawia tło, jeśli tej lokacji jeszcze nie ma. Wymaga działającej pętli asyncio."""
        if self.client is None:
            return
        job = self.jobs.get((game_id, location))
        if job and job.status != "failed":
            return
        crc = zlib.crc32(location.encode())
        self._start(location, Job(
            game_id, location, t, "background",
            f"/api/games/{game_id}/image/file?location={quote(location, safe='')}",
            f"{self.style} {description}".strip(), location_seed(game_seed, location),
            self.root / game_id / f"{location[:80]}-{crc:08x}.png",
        ))

    def _portrait_key(self, game_id: str, name: str) -> str:
        """Klucz portretu. „Borwin” i „Borwin karczmarz” to jedna postać (krótsza nazwa jest początkiem dłuższej)."""
        key = character_key(name)
        words = key.split()
        for job_game, job_key in self.jobs:
            if job_game == game_id and job_key.startswith("char:"):
                other = job_key.removeprefix("char:").split()
                common = min(len(words), len(other))
                if common and words[:common] == other[:common]:
                    return job_key
        return f"char:{key}"

    def request_portrait(self, game_id: str, name: str, prompt: str, game_seed: int | None, t: int) -> None:
        """Zamawia portret, jeśli tej postaci jeszcze nie ma. Portret zostaje na całą grę."""
        if self.client is None:
            return
        key = self._portrait_key(game_id, name)
        job = self.jobs.get((game_id, key))
        if job and job.status != "failed":
            return
        character = key.removeprefix("char:")
        slug = re.sub(r"[^a-z0-9]+", "_", character)[:60]
        self._start(key, Job(
            game_id, character, t, "portrait", "", prompt, location_seed(game_seed, key),
            self.root / game_id / f"portrait-{slug}-{zlib.crc32(key.encode()):08x}.png",
        ))

    def request_scene(self, game_id: str, t: int, location: str, prompt: str, game_seed: int | None,
                      characters: Sequence[str] = ()) -> None:
        """Zamawia obraz tury. Powstaje po tle i portretach postaci, na ich podstawie (characters: bohater pierwszy)."""
        if self.client is None:
            return
        keys = [location, *(self._portrait_key(game_id, name) for name in characters[:MAX_PORTRAITS])]
        self._start(f"turn:{t}", Job(
            game_id, location, t, "scene", f"/api/games/{game_id}/scene/file?t={t}", prompt,
            location_seed(game_seed, location) + t, self.root / game_id / f"turn-{t:04d}.png",
            after=[self.jobs[(game_id, k)] for k in keys if (game_id, k) in self.jobs],
        ))

    async def _run(self, job: Job) -> None:
        started = time.perf_counter()  # z oczekiwaniem na tło: to czas od komendy gracza do obrazu
        model = ""
        try:
            for needed in job.after:
                if needed.task:
                    await needed.task
            refs = [needed.path.read_bytes() for needed in job.after if needed.status == "ready"]
            data, model = await self.client.generate(job.prompt, job.seed, refs, self.models.get(job.game_id))
            if not data:
                raise ValueError("pusta odpowiedź serwera obrazów")
            job.path.parent.mkdir(parents=True, exist_ok=True)
            job.path.write_bytes(data)
            job.status = "ready"
        except Exception as e:  # gra ma działać dalej bez obrazu, np. gdy tunel do GPU jest wyłączony
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
        if self.store:
            self.store.save_image(job.game_id, job.location, job.t, job.kind, job.prompt, job.seed, model, job.status,
                                  round(time.perf_counter() - started, 3),
                                  str(job.path) if job.status == "ready" else None, job.error)

    def _status(self, game_id: str, key: str) -> dict:
        if self.client is None:
            return {"status": "off"}
        job = self.jobs.get((game_id, key))
        if job is None:
            return {"status": "none"}
        return {"status": job.status, "url": job.url} if job.status == "ready" else {"status": job.status}

    def _path(self, game_id: str, key: str) -> Path | None:
        job = self.jobs.get((game_id, key))
        return job.path if job and job.status == "ready" else None

    def status(self, game_id: str, location: str) -> dict:
        return self._status(game_id, location)

    def path(self, game_id: str, location: str) -> Path | None:
        return self._path(game_id, location)

    def scene_status(self, game_id: str, t: int) -> dict:
        return self._status(game_id, f"turn:{t}")

    def scene_path(self, game_id: str, t: int) -> Path | None:
        return self._path(game_id, f"turn:{t}")
