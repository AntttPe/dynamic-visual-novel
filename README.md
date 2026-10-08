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

* **http://localhost:8000** to aplikacja (czat z narratorem)
* **http://localhost:8000/docs** to dokumentacja API

## Krok 5. Sprawdź, czy wszystko działa

```bash
docker compose exec app pytest -v
```

Poprawny wynik wygląda tak:
```
3 passed, 1 skipped
```
Jeden test jest pominięty, jeśli nie masz uruchomionej Ollamy (patrz niżej). To normalne.

**Gotowe, środowisko działa.**

---

## Najważniejsze komendy

| Co chcesz zrobić | Komenda |
|---|---|
| Uruchomić aplikację | `docker compose up -d` |
| Zatrzymać aplikację | `docker compose down` |
| Zobaczyć logi | `docker compose logs -f app` |
| Uruchomić testy | `docker compose exec app pytest -v` |
| Wejść do kontenera | `docker compose exec app bash` |
| Dodać bibliotekę Pythona | `docker compose exec app uv add <nazwa>` a potem `docker compose up -d --build` |

Kod jest połączony z kontenerem. Gdy zmienisz plik `.py`, serwer sam się zrestartuje.
Gdy zmienisz plik w `app/static/`, wystarczy odświeżyć stronę.

Po dodaniu biblioteki wrzuć na GitHuba pliki `pyproject.toml` i `uv.lock`,
żeby reszta zespołu miała te same wersje.

## Struktura projektu

```
app/
  main.py        adresy API aplikacji
  llm.py         połączenie z modelem językowym
  config.py      odczyt ustawień z .env
  static/        wygląd strony (HTML, CSS, JS)
tests/
  test_app.py    testy sprawdzające, czy środowisko działa
data/            dane lokalne, nie trafiają na GitHuba
```

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

Po uruchomieniu Ollamy odśwież http://localhost:8000. Przy „ollama” pojawi się ✅
i można pisać z narratorem.

---

## Gdy coś nie działa

| Problem | Rozwiązanie |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop nie jest uruchomiony. Włącz go. |
| `port is already allocated` | Port 8000 jest zajęty. W `docker-compose.yml` zmień `"8000:8000"` na np. `"8080:8000"` i wejdź na localhost:8080 |
| Zmiany w kodzie nie restartują serwera | W `.env` ustaw `WATCHFILES_FORCE_POLLING=true` i uruchom ponownie |
| „Ollama niedostępna” | Sprawdź, czy działa `ollama serve` |
| `model not found` | Pobierz model: `ollama pull llama3.1:8b` |
| Dziwne błędy po zmianie bibliotek | `docker compose down`, potem `docker compose build --no-cache`, potem `docker compose up -d` |
