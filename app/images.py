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
import difflib
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


class LiteLLMImageClient:
    """Dowolne API obrazów obsługiwane przez LiteLLM (np. openai/gpt-image-1 albo serwer zgodny z API OpenAI).

    Takie API rysuje tylko z opisu: obrazów wejściowych (tła i portretów) nie dostaje, więc spójność
    postaci między turami jest słabsza niż z serwerem obrazów projektu.
    """

    def __init__(self, model: str, api_base: str | None, api_key: str | None, timeout_s: float,
                 size: str = "1536x1024"):
        self.model = model
        self.api_base = api_base or None
        self.api_key = api_key or None
        self.timeout_s = timeout_s
        self.size = size

    async def generate(self, prompt: str, seed: int, refs: Sequence[bytes] = (),
                       model: str | None = None) -> tuple[bytes, str]:
        import litellm  # import tutaj, bo LiteLLM wczytuje się długo, a bez własnego API nie jest potrzebny

        try:
            resp = await litellm.aimage_generation(
                model=self.model, prompt=prompt, n=1, size=self.size,
                api_base=self.api_base, api_key=self.api_key, timeout=self.timeout_s,
            )
        except Exception as e:  # noqa: BLE001  dostawca potrafi powtórzyć klucz w treści błędu, a błąd trafia do bazy
            message = str(e).replace(self.api_key, "***") if self.api_key else str(e)
            raise RuntimeError(f"{type(e).__name__}: {message}") from None
        item = resp.data[0]
        b64 = getattr(item, "b64_json", None)
        if b64:
            return base64.b64decode(b64), self.model
        url = getattr(item, "url", None)
        if not url:
            raise ValueError("API obrazów nie zwróciło ani pliku, ani adresu")
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            got = await client.get(url)
            got.raise_for_status()
        return got.content, self.model


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


def short_error(error: str | None) -> str:
    """Krótka przyczyna nieudanego obrazu dla gracza. Pełny błąd zostaje w tabeli images."""
    text = error or ""
    low = text.lower()
    if "free_tier" in low and "limit: 0" in low:
        return "ten model nie działa w darmowym planie dostawcy, potrzebny jest klucz z płatnościami"
    if "ratelimit" in low or "429" in text or "quota" in low:
        return "przekroczony limit zapytań u dostawcy (429), spróbuj później albo sprawdź plan"
    if "authentication" in low or "401" in text or "api key" in low or "api_key" in low:
        return "zły albo brakujący klucz API"
    if "notfound" in low or "404" in text:
        return "nie ma takiego modelu u dostawcy, sprawdź nazwę"
    if "connect" in low or "timeout" in low:
        return "serwer obrazów nie odpowiada, sprawdź adres albo tunel"
    first = text.splitlines()[0] if text else "nieznany błąd"
    return first[:200]


DEFAULT_ERA = "medieval"


def styled(template: str, era: str) -> str:
    """Styl obrazów dla świata: {era} z app/config.py zamienia się na epokę i klimat świata (visual_style)."""
    return template.replace("{era}", era.strip() or DEFAULT_ERA)


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


def scene_prompt(style: str, place: str, people: Sequence[str], picture: str) -> str:
    """Opis sceny po angielsku. people: wygląd postaci w tej samej kolejności, co ich portrety na wejściu modelu
    (bohater pierwszy). Bez imion, bo model obrazów rysuje je jako napisy."""
    shown = [look.strip().rstrip(".") for look in people if look.strip()]
    cast = ""
    if shown:
        listed = "; ".join(f"{i}) {look}" for i, look in enumerate(shown, 1))
        cast = (f" Characters in the order of the reference images: {listed}. "
                f"Exactly {len(shown)} {'character' if len(shown) == 1 else 'characters'} in the picture, "
                "each one only once.")
    return f"{style} {place.strip().rstrip('.')}.{cast} {picture.strip()}".strip()


def portrait_prompt(style: str, look: str) -> str:
    """Opis portretu postaci po angielsku, bez imienia (model obrazów wypisywał je na obrazie)."""
    return f"{style} {look.strip().rstrip('.') or 'A person'}."


def legacy_look(facts: Iterable, entity: str) -> str:
    """Wygląd z faktów świata (po polsku): tylko stare gry i światy bez opisów po angielsku."""
    return _looks(list(facts), entity, PORTRAIT_ATTRIBUTES)


# Słowa, które nie wyróżniają postaci przy szukaniu po imieniu („pani Beata” i „pani Halina” to dwie osoby)
_TITLES = {"pan", "pani", "panie", "panna", "mistrz", "mistrzyni", "stary", "stara", "młody", "młoda", "the"}


def _name_stems(name: str) -> set[str]:
    words = [w for w in character_key(name).split() if len(w) >= 3 and w not in _TITLES]
    return {w[:max(4, len(w) - 2)] for w in words}


class Looks:
    """Wygląd postaci jednej gry po angielsku: ze świata (World.hero_look, World.characters) i od narratora
    (new_characters). Znajduje postać także po innej formie imienia: „Senna” i „Senne”, „Bodo” i „szkiełkarz Bodo”."""

    HERO = "bohater"

    def __init__(self):
        self.entries: dict[str, tuple[str, str]] = {}  # klucz imienia -> (imię, wygląd)

    @classmethod
    def of_world(cls, world) -> "Looks":
        looks = cls()
        if world.hero_look.strip():
            looks.add(cls.HERO, world.hero_look)
            looks.add(world.player.split(",")[0], world.hero_look)
        for character in world.characters:
            looks.add(character.name, character.look)
        return looks

    def add(self, name: str, look: str) -> None:
        """Pierwszy opis postaci zostaje: wygląd się nie zmienia, nawet gdy narrator opisze go drugi raz."""
        key = character_key(name)
        if key and look.strip() and self.match(name) is None:
            self.entries[key] = (name.strip(), look.strip())

    def match(self, name: str) -> str | None:
        """Klucz znanej postaci o tym imieniu albo podobnym. None = postać bez opisu."""
        key = character_key(name)
        if not key:
            return None
        if key in self.entries:
            return key
        stems = _name_stems(name)
        for known in self.entries:
            if stems & _name_stems(known):
                return known
        close = difflib.get_close_matches(key, list(self.entries), n=1, cutoff=0.8)
        return close[0] if close else None

    def find(self, name: str) -> str:
        known = self.match(name)
        return self.entries[known][1] if known else ""

    def canonical(self, name: str) -> str:
        """Imię, pod którym postać jest zapisana (ten sam portret dla „Senna” i „Senne”)."""
        known = self.match(name)
        return self.entries[known][0] if known else name


class BackgroundImages:
    def __init__(self, client: ImageClient | None, root: str | Path, store=None, style: str = ""):
        self.client = client
        self.root = Path(root)
        self.store = store
        self.style = style
        self.jobs: dict[tuple[str, str], Job] = {}
        self.casts: dict[str, SceneCast] = {}
        self.models: dict[str, str] = {}  # gra -> generator wybrany przy jej tworzeniu
        self.clients: dict[str, ImageClient] = {}  # gra -> własne API obrazów z okna „Nowa gra”
        self.disabled: set[str] = set()  # gry bez obrazów (konto gracza z wyłączoną grafiką)
        self.looks: dict[str, Looks] = {}  # gra -> wygląd postaci po angielsku

    def client_for(self, game_id: str) -> ImageClient | None:
        """Własne API obrazów tej gry, a bez niego serwer z .env (IMAGE_SERVER_URL)."""
        if game_id in self.disabled:
            return None
        return self.clients.get(game_id) or self.client

    def cast(self, game_id: str, start_location: str) -> SceneCast:
        return self.casts.setdefault(game_id, SceneCast(start_location))

    def _start(self, key: str, job: Job) -> None:
        self.jobs[(job.game_id, key)] = job
        job.task = asyncio.create_task(self._run(job))

    def request(self, game_id: str, location: str, description: str, game_seed: int | None, t: int,
                era: str = "") -> None:
        """Zamawia tło, jeśli tej lokacji jeszcze nie ma. Wymaga działającej pętli asyncio.
        era: epoka i klimat świata (World.visual_style), wstawiane w styl w miejsce {era}."""
        if self.client_for(game_id) is None:
            return
        job = self.jobs.get((game_id, location))
        if job and job.status != "failed":
            return
        crc = zlib.crc32(location.encode())
        self._start(location, Job(
            game_id, location, t, "background",
            f"/api/games/{game_id}/image/file?location={quote(location, safe='')}",
            f"{styled(self.style, era)} {description}".strip(), location_seed(game_seed, location),
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
        if self.client_for(game_id) is None:
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
        if self.client_for(game_id) is None:
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
            client = self.client_for(job.game_id)
            data, model = await client.generate(job.prompt, job.seed, refs, self.models.get(job.game_id))
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

    def restore(self, game_id: str, rows: Sequence[dict]) -> None:
        """Gotowe obrazy zapisanej gry (tabela images), żeby było je widać po restarcie serwera."""
        for row in rows:
            path = Path(row["path"] or "")
            if row["status"] != "ready" or not path.is_file():
                continue
            loc, t = row["location_id"], row["t"]
            key, url = {
                "background": (loc, f"/api/games/{game_id}/image/file?location={quote(loc, safe='')}"),
                "portrait": (f"char:{loc}", ""),
                "scene": (f"turn:{t}", f"/api/games/{game_id}/scene/file?t={t}"),
            }.get(row["kind"], (None, ""))
            if key and (game_id, key) not in self.jobs:
                self.jobs[(game_id, key)] = Job(game_id, loc, t, row["kind"], url, row["prompt"], row["seed"], path,
                                                status="ready")
            if row["model"]:
                self.models.setdefault(game_id, row["model"])

    def _status(self, game_id: str, key: str) -> dict:
        job = self.jobs.get((game_id, key))
        if job and job.status == "ready":  # zapisany obraz widać także bez serwera obrazów
            return {"status": job.status, "url": job.url}
        if self.client_for(game_id) is None:
            return {"status": "off"}
        if job is None:
            return {"status": "none"}
        if job.status == "failed":
            return {"status": job.status, "error": short_error(job.error)}
        return {"status": job.status}

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
