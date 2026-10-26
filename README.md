# Dynamic Visual Novel

Gra typu Visual Novel, w której fabułę, dialogi i tła tworzą na bieżąco modele AI.
Gracz wpisuje dowolne działanie, a model opowiada, co dzieje się dalej.

Projekt na przedmiot *Eksploracja modeli i metod AI*.

Całość działa w jednym kontenerze Docker, więc u każdego (macOS, Windows, Linux)
uruchamia się tak samo. Nie trzeba instalować Pythona ani bibliotek.

---

## Krok 1. Zainstaluj programy

**macOS**
1. Zainstaluj [Docker Desktop](https://www.docker.com/products/docker-desktop/) i uruchom go.
2. Git zwykle już jest. Sprawdź w terminalu: `git --version`

**Windows**
1. Zainstaluj WSL2. Otwórz PowerShell jako administrator i wpisz: `wsl --install`
2. Zrestartuj komputer. Uruchom aplikację **Ubuntu** i ustaw login oraz hasło.
3. Zainstaluj [Docker Desktop](https://www.docker.com/products/docker-desktop/).
   W ustawieniach zaznacz **Use the WSL 2 based engine** oraz w zakładce
   *Resources > WSL Integration* włącz Ubuntu.
4. **Wszystkie dalsze komendy wpisuj w terminalu Ubuntu**, nie w PowerShellu.

**Linux**
1. Zainstaluj Docker Engine oraz `docker compose` według [instrukcji](https://docs.docker.com/engine/install/).
2. Zainstaluj Git, np. `sudo apt install git`

Sprawdź, czy Docker działa:
```bash
docker --version
docker compose version
```

## Krok 2. Pobierz projekt

```bash
git clone https://github.com/AntttPe/dynamic-visual-novel.git
cd dynamic-visual-novel
```

> **Windows:** rób to w terminalu Ubuntu, w swoim katalogu domowym (np. `cd ~`).
> Nie klonuj na dysk `C:\`, bo wtedy automatyczne przeładowanie kodu nie działa.

## Krok 3. Utwórz plik z ustawieniami

```bash
cp .env.example .env
```

Plik `.env` zawiera ustawienia i klucze API. Na start nie musisz nic w nim zmieniać.
**Nigdy nie wrzucaj `.env` na GitHuba** (jest dodany do `.gitignore`).

## Krok 4. Uruchom aplikację

```bash
docker compose up -d --build
```

Pierwsze uruchomienie trwa kilka minut. Potem otwórz w przeglądarce:

* **http://localhost:8000** to gra (scena, okno narracji i panel badawczy)
* **http://localhost:8000/docs** to dokumentacja API

Bez uruchomionego modelu kliknij **Szybki start w trybie demo**. Tryb demo nie opowiada
prawdziwej historii, ale pokazuje cały przepływ: scenę, stan świata, prompt i JSON.

## Krok 5. Sprawdź, czy wszystko działa

```bash
docker compose exec app pytest -v
```

Poprawny wynik wygląda tak (liczby mogą być inne, ważne, żeby nie było `failed`):
```
21 passed, 1 skipped
```
Jeden test jest pominięty, jeśli nie masz uruchomionej Ollamy (patrz niżej). To normalne.

**Gotowe, środowisko działa.**

---

## Najważniejsze komendy

| Co chcesz zrobić | Komenda |
|---|---|
| Uruchomić aplikację | `docker compose up -d` |
| Wstrzymać aplikację (na przerwę) | `docker compose stop` |
| Wznowić po wstrzymaniu | `docker compose start` |
| Usunąć kontener | `docker compose down` |
| Zobaczyć logi | `docker compose logs -f app` |
| Uruchomić testy | `docker compose exec app pytest -v` |
| Wejść do kontenera | `docker compose exec app bash` |
| Dodać bibliotekę Pythona | `docker compose exec app uv add <nazwa>` a potem `docker compose up -d --build` |

Kod jest połączony z kontenerem. Gdy zmienisz plik `.py`, serwer sam się zrestartuje.
Gdy zmienisz plik w `app/static/`, wystarczy odświeżyć stronę.

Po dodaniu biblioteki wrzuć na GitHuba pliki `pyproject.toml` i `uv.lock`,
żeby reszta zespołu miała te same wersje.

`docker compose down` usuwa kontener, ale nic ważnego nie ginie: kod i `data/` są na twoim
komputerze, a pamięć agenta Claude Code jest w osobnym wolumenie.
Wolumen usuwa dopiero `docker compose down -v`, więc **nie dodawaj `-v`**, chyba że chcesz wyczyścić wszystko.

## Agent Claude Code w kontenerze

Claude Code jest zainstalowany w kontenerze. Wejdź do środka i uruchom go:
```bash
docker compose exec app bash
claude
```
Przy pierwszym uruchomieniu trzeba się zalogować. Logowanie, historia rozmów i pamięć agenta
zapisują się w wolumenie `claude_home`, więc zostają po `docker compose down` i po przebudowie obrazu.

Agent czyta plik `CLAUDE.md` z opisem projektu i zasadami pracy. Gdy zmienia się coś ważnego
w projekcie, zaktualizuj ten plik, bo z niego korzysta cały zespół.

**Commity z kontenera:** w `.env` odkomentuj i uzupełnij linie `GIT_AUTHOR_...` i `GIT_COMMITTER_...`.
Wypychanie na GitHuba (`git push`) rób na swoim komputerze, bo kontener nie ma dostępu do twojego konta GitHub.

## Struktura projektu

```
app/
  main.py            adresy API gry
  config.py          odczyt ustawień z .env
  core/              silnik gry: jedna tura od akcji gracza do zapisu
    engine.py        przebieg tury, ponowienia przy złym JSON
    context.py       składanie promptu
    memory.py        strategie pamięci (pełna historia, okno)
    state.py         stan świata i walidator faktów niezmiennych
    schemas.py       format odpowiedzi narratora (JSON)
    world.py         wczytywanie świata z pliku YAML
  llm/               połączenie z modelami (LiteLLM, tryb demo, model na niby do testów)
  storage/db.py      zapis każdej tury do SQLite
  prompts/           prompt narratora
  worlds/            światy gry (YAML)
  static/            wygląd strony (HTML, CSS, JS)
  eval/              scenariusze badawcze, runner, metryki, raport
tests/               testy (działają bez modelu)
CLAUDE.md            opis projektu i zasady dla agenta Claude Code
data/                baza dvn.sqlite z zapisem gier, nie trafia na GitHuba
```

Każda tura zapisuje się w `data/dvn.sqlite`: prompt, odpowiedź modelu, tokeny, czas,
lokacja i zmiany stanu. To surowe dane do metryk.

---

## Model Llama (Ollama), opcjonalnie

Aplikacja rozmawia z lokalnym modelem przez program **Ollama**.
Ollama działa na komputerze, a nie w kontenerze, bo Docker na Macu nie ma dostępu do karty graficznej.

**macOS**
```bash
brew install ollama
ollama serve               # zostaw ten terminal otwarty
ollama pull llama3.1:8b    # w nowym terminalu, pobiera ok. 5 GB
```

**Windows i Linux:** zainstaluj Ollamę ze strony [ollama.com](https://ollama.com/download)
i pobierz model komendą `ollama pull llama3.1:8b`.

**Linux lub Windows z kartą NVIDIA:** Ollama może działać w kontenerze.
1. Zainstaluj [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
2. W pliku `.env` ustaw `OLLAMA_BASE_URL=http://ollama:11434`
3. Uruchom: `docker compose --profile local-gpu up -d`
4. Pobierz model: `docker compose exec ollama ollama pull llama3.1:8b`

Po uruchomieniu Ollamy odśwież http://localhost:8000. Przy nazwie modelu pojawi się
zielona kropka i można grać.

---

## Wybór modelu narratora

Połączenie z modelami idzie przez bibliotekę **LiteLLM**, więc zmiana modelu to zmiana
jednej linijki w `.env` (`NARRATOR_MODEL`) albo pola „Model narratora” w oknie nowej gry.

| Gdzie działa model | Ustawienia w `.env` |
|---|---|
| Ollama na twoim komputerze | `NARRATOR_MODEL=ollama_chat/llama3.1:8b` |
| Ollama na wynajętym GPU (np. RunPod) | to samo, plus tunel SSH (niżej) |
| vLLM na wynajętym GPU | `NARRATOR_MODEL=hosted_vllm/<nazwa-modelu>` i `NARRATOR_API_BASE=http://host.docker.internal:8001/v1` |
| Model przez API | np. `NARRATOR_MODEL=anthropic/claude-haiku-5-5` i klucz `ANTHROPIC_API_KEY` |
| Bez modelu | `NARRATOR_MODEL=demo` |

**Wynajęte GPU.** Na komputerze otwórz tunel SSH do maszyny z GPU i zostaw terminal otwarty:
```bash
ssh -N -L 11434:localhost:11434 root@<adres-maszyny> -p <port> -i ~/.ssh/<twój-klucz>
```
Model na GPU jest wtedy widoczny tak, jakby działał lokalnie, więc `OLLAMA_BASE_URL` się nie zmienia.
Dla vLLM przekieruj port 8001 (`-L 8001:localhost:8000`).
**Nie wystawiaj portu Ollamy publicznie** w panelu RunPod: Ollama nie ma hasła.

Wersja LiteLLM jest przypięta w `pyproject.toml`. Nie aktualizuj jej bez sprawdzenia
(w marcu 2026 w PyPI pojawiły się złośliwe wersje 1.82.7 i 1.82.8).

---

## Eksperymenty (badanie modeli)

Scenariusze badawcze leżą w `app/eval/scenarios/`. Każdy to z góry napisana lista akcji gracza
z oczekiwaniami (opis pól w `_template.yaml`). Runner przepuszcza scenariusz przez model
tym samym silnikiem co gra, a każda tura trafia do `data/dvn.sqlite`.

Wszystkie komendy wpisuj w kontenerze (`docker compose exec app bash`).

**1. Sprawdź scenariusz** (po każdej zmianie w YAML):
```bash
python -m app.eval.check main_v2
```

**2. Szybki test bez modelu** (tryb demo, ok. minuty):
```bash
python -m app.eval.run --model demo --reps 1 --tag demo
```

**3. Uruchom badanie** (włącz VPN instytutu):
```bash
python -m app.eval.run --model openai/large-reasoning --reps 3 --tag sprint1
python -m app.eval.run --model openai/strata-big --reps 3 --tag sprint1
python -m app.eval.run --model openai/large-reasoning --reps 3 --tag sprint1 --no-state   # bez stanu świata
```
Jedna tura trwa 30 do 90 s, więc 28 tur × 3 powtórzenia to ok. 1 do 2 godzin na konfigurację.
Na krótki test dodaj `--max-turns 3`.

**Gdy coś przerwie badanie** (VPN, Ctrl+C, zamknięty laptop): uruchom **tę samą komendę** jeszcze raz.
Runner wznowi od ostatniej zapisanej tury i pominie ukończone powtórzenia.

**Długie badanie w tle** (na hoście, nie w kontenerze; `caffeinate -di` nie pozwala Macowi zasnąć ani wygasić ekranu, bo wygaszacz rozłącza VPN):
```bash
caffeinate -di docker compose exec app sh -c \
  "python -m app.eval.run --model openai/large-reasoning --reps 3 --tag sprint1 >> data/eval/run.log 2>&1"
```
Postęp: `tail -f data/eval/run.log`. Nie używaj `docker compose down` w trakcie, bo przerwie badanie.

**4. Wyniki:**
```bash
python -m app.eval.report --tag sprint1                 # podsumowanie metryk dla każdej konfiguracji
python -m app.eval.report --tag sprint1 --details       # plus lista nieudanych sprawdzeń
python -m app.eval.report --tag sprint1 --csv data/eval/sprint1.csv   # do analizy i wykresów
python -m app.eval.extra_metrics --tag sprint1 --csv data/eval/sprint1_extra.csv   # metryki X1 do X5 i porównanie ze stanem/bez stanu
```

| Metryka | Co mierzy | Jak liczona |
|---|---|---|
| M1 pamięć faktów | czy model pamięta fakt podany przez gracza k tur wcześniej | w odpowiedzi musi paść słowo z `accept` |
| M2 fakty niezmienne | czy model utrzymuje stałe cechy świata | słowa z `accept`, próby zmiany wykryte przez walidator, gaslighting oceni sędzia |
| M3 dziwne komendy | czy model logicznie reaguje na nietypowe akcje | sędzia LLM (w przygotowaniu) |
| M4 spójność lokacji | czy to samo miejsce ma zawsze ten sam `location_id` | porównanie z oczekiwaną lokacją albo między wizytami |

---

## Gdy coś nie działa

| Problem | Rozwiązanie |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop nie jest uruchomiony. Włącz go. |
| `port is already allocated` | Port 8000 jest zajęty. W `docker-compose.yml` zmień `"8000:8000"` na np. `"8080:8000"` i wejdź na localhost:8080 |
| Zmiany w kodzie nie restartują serwera | W `.env` ustaw `WATCHFILES_FORCE_POLLING=true` i uruchom ponownie |
| „Ollama nie odpowiada” (żółty pasek w grze) | Sprawdź, czy działa `ollama serve` albo tunel SSH do GPU |
| „Narrator nie zwrócił poprawnej odpowiedzi” | Model nie trzyma formatu JSON. Spróbuj jeszcze raz albo użyj większego modelu |
| `model not found` | Pobierz model: `ollama pull llama3.1:8b` |
| `claude: command not found` w kontenerze | Obraz jest stary. Uruchom `docker compose up -d --build` |
| Dziwne błędy po zmianie bibliotek | `docker compose down`, potem `docker compose build --no-cache`, potem `docker compose up -d` |
