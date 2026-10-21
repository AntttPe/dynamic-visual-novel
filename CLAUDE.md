# Dynamic Visual Novel

Projekt studencki na przedmiot "Eksploracja modeli i metod AI".
Repo: https://github.com/AntttPe/dynamic-visual-novel (PUBLICZNE).
Zespół pracuje na macOS, Windows (WSL2) i Linux. Wszystko działa w jednym kontenerze Docker.

## Cel
Visual Novel, w której fabuła, dialogi i tła są generowane na żywo przez modele AI
na podstawie swobodnych komend gracza. Brak predefiniowanych wyborów.
LLM jest narratorem, a na podstawie opisu sceny powstaje tło lokacji.

## Pytania badawcze (najważniejsze, prowadzący ocenia głównie metryki)
1. Spójność narracyjna: logiczne reakcje na nietypowe pomysły gracza bez gubienia wątku głównego.
2. Spójność stanu świata i faktów: niezmienne atrybuty przedmiotów, postaci i lokacji.
3. Spójność wizualna: tła tej samej lokacji i styl spójne w czasie.

Planowane metryki:
- Narracja: LLM-as-judge z rubryką (1-5), utrzymanie wątku głównego, zestaw "dziwnych" komend,
  mała ewaluacja ludzka do walidacji sędziego.
- Stan świata: contradiction rate (model NLI względem bazy faktów), fact recall
  (fakt wstrzyknięty, pytanie po k turach), liczba naruszeń faktów niezmiennych.
- Wizualnie: CLIPScore, podobieństwo embeddingów CLIP/DINOv2 dla tej samej lokacji, wariancja stylu.
- Techniczne: latencja, tokeny, koszt, % poprawnych odpowiedzi JSON.
Eksperymenty mają być powtarzalne: skryptowe scenariusze gracza, stała temperatura i seed,
macierz: modele x strategie pamięci x scenariusze.

## Architektura (stan obecny)
- `app/main.py`: FastAPI. `/api/health`, `/api/config`, `/api/games`, `/api/games/{id}`,
  `/api/games/{id}/turns`. UI serwowane pod `/`.
- `app/core/`: silnik tury. `engine.py` (przebieg tury, ponowienia przy złym JSON),
  `context.py` (prompt), `memory.py` (strategie pamięci: full, window),
  `state.py` (stan świata, walidator faktów niezmiennych), `schemas.py` (Pydantic, JSON narratora),
  `world.py` (światy z YAML w `app/worlds/`).
- `app/llm/`: LiteLLM (`litellm_client.py`), tryb `demo` i model na niby do testów (`fake.py`).
  Model wybiera `NARRATOR_MODEL` w `.env` (format LiteLLM `<provider>/<model>`).
- `app/storage/db.py`: każda tura w `data/dvn.sqlite` (prompt, odpowiedź, tokeny, czas, stan).
  To surowe dane do metryk, loguj wszystko.
- `app/prompts/narrator_system.md`: prompt narratora.
- `app/static/`: UI w czystym HTML/CSS/JS.
- `app/eval/`: scenariusze badawcze. `scenario.py` (format YAML i walidator), `check.py`
  (`python -m app.eval.check`), `run.py` (runner, wznawianie po przerwaniu, tabela `eval_runs`),
  `metrics.py` (M1, M2 bez gaslightingu, M4), `report.py`, `scenarios/_template.yaml` (opis pól),
  `scenarios/main_v1.yaml`. Sędzia LLM (M2 gaslighting, M3) jeszcze nie istnieje.
  Metryki sprintu: 1 recall@k, 2 naruszenia faktów niezmiennych, 3 dziwne komendy, 4 spójność location_id.
- `bench/images/`: osobny benchmark modeli obrazów na wynajętym GPU (torch/diffusers, poza kontenerem gry).

Dalsze kroki: pipeline obrazów (cache po location_id, stały styl i seed), kolejne strategie pamięci
(streszczenie, RAG), sędzia LLM, raport z wykresami.

## Środowisko
- Jesteś w kontenerze, kod jest w `/app` (bind mount z hosta). venv: `/opt/venv`.
- Zależności: `uv add <paczka>`, potem przebudowa obrazu na hoście. Commituj `pyproject.toml` i `uv.lock`.
- Serwer działa z `--reload`, zmiany w `app/*.py` restartują go same.
- Testy: `pytest -v`. Uruchamiaj po każdej zmianie. Testy muszą działać bez modelu.
- Ollama działa NA HOŚCIE (Docker na macOS nie ma GPU): `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- LiteLLM jest przypięty (`litellm==...`). Nie aktualizuj bez sprawdzenia (złośliwe wersje 1.82.7 i 1.82.8).
- Musi działać na arm64 (Mac M) i amd64.

## Zasady
- Sekrety tylko w `.env`. Repo jest publiczne, nigdy nie commituj kluczy ani adresów serwerów uczelni.
- Jeden kontener i Python. Bez Node i frameworków JS.
- Warstwa LLM ma łatwo podmieniać providera, bo porównanie modeli to sedno projektu.
- Commity: krótkie, po angielsku. NIE dodawaj "Co-Authored-By" ani wzmianek o AI/Claude
  w commitach i PR-ach.
- Dokumentacja (README itp.) po polsku, prostym językiem, bez długich myślników (— i –).
  Aktualizuj README, gdy zmienia się sposób uruchamiania.
- Przed dużymi decyzjami (nowy provider, zmiana architektury, ciężkie zależności typu torch)
  zaproponuj plan i zapytaj.
- Bez force push i przepisywania historii bez pytania. Push robi użytkownik.
