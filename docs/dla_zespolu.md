# Dynamic Visual Novel: dokumentacja dla zespołu

Szczegóły, których nie trzeba do samego grania. Jak uruchomić grę, opisuje [README](../README.md) i [poradnik PDF](poradnik.pdf).

## Spis treści

* [Własny świat](#własny-świat)
* [Wygrana, przegrana i limit tur](#wygrana-przegrana-i-limit-tur)
* [Testy](#testy)
* [Agent Claude Code w kontenerze](#agent-claude-code-w-kontenerze)
* [Struktura projektu](#struktura-projektu)
* [Model Llama (Ollama), opcjonalnie](#model-llama-ollama-opcjonalnie)
* [Wybór modelu narratora](#wybór-modelu-narratora)
* [Własne API do tekstu i obrazów](#własne-api-do-tekstu-i-obrazów)
* [Gra z obrazami (serwer GPU instytutu)](#gra-z-obrazami-serwer-gpu-instytutu)
* [Eksperymenty (badanie modeli)](#eksperymenty-badanie-modeli)

## Własny świat

W menu wybierz kartę **Własny świat** i wpisz kilka zdań w polu po prawej (albo kliknij jeden z przykładów), np.
`Cyberpunkowy Kraków w 2090 roku, jestem detektywką i szukam zaginionego androida`.
Wybrany model narratora zamieni pomysł w pełny świat: bohatera, cel, zasady, 4 do 6 lokacji,
fakty niezmienne (wygląd postaci, materiały przedmiotów) i scenę otwierającą. Potem ten sam model prowadzi grę.

* Wytyczne dla modelu są w `app/prompts/world_builder.md`, a wzorem jest świat „Zaginiona korona”
  (`app/worlds/zaginiona_korona.yaml`). Zmiana wytycznych zmienia każdy kolejny świat.
* Tworzenie świata trwa od kilku sekund do kilku minut (`strata-big`: 1 do 5 minut, `large-reasoning` dłużej,
  bo najpierw myśli). W trakcie czekania można kliknąć **Anuluj**. Mały model czasem nie trzyma formatu,
  wtedy gra ponawia prośbę, a po kilku nieudanych próbach pokazuje błąd.
* Gotowy świat, pomysł gracza, prompt i odpowiedź modelu zapisują się w tabeli `worlds` bazy `data/dvn.sqlite`.
  Opis świata widać też w panelu badawczym, w zakładce **Tura**.
* W trybie `demo` nie ma modelu, więc zamiast nowego świata dostajesz „Zaginioną koronę” z twoim pomysłem w opisie.
* Model nadaje też światu cel oraz warunek wygranej i przegranej (patrz niżej).

## Wygrana, przegrana i limit tur

* Każdy świat ma cel oraz warunek wygranej i przegranej. W „Zaginionej koronie” wygrana to oddanie korony królowi
  albo straży, a przegrana to śmierć, loch na zawsze albo zniszczenie korony. Własny świat dostaje je od modelu.
* Po każdej turze narrator ocenia, czy gra się skończyła (pole `outcome` w JSON). Gdy tak, na scenie pojawia się
  plansza „Wygrana!” albo „Przegrana” z powodem, a pole akcji się blokuje.
* W menu możesz ustawić **Limit tur**. Gdy limit minie, a cel nie jest osiągnięty, gra kończy się przegraną.
  Narrator wie, która to tura, więc pod koniec przyspiesza akcję.
* **Podpowiedzi** (przełącznik w menu, w kodzie `difficulty: "easy"`): narrator dostaje dodatkowe zasady
  z `app/prompts/narrator_easy.md`. Rozsądne pomysły się udają, postacie chętnie pomagają, narrator ostrzega
  przed niebezpieczeństwem, a po każdej turze zwraca pole `hint` z następnym krokiem w stronę wygranej.
  Podpowiedź widać w prawym górnym rogu ekranu gry. Zasady świata i fakty niezmienne obowiązują dalej.
* Wynik każdej tury zapisuje się w kolumnie `outcome` tabeli `turns`.
* **Komiks z rozgrywki:** na planszy końca gry przycisk otwiera `comic.html?game=<id>` w nowej karcie. Najpierw okładka,
  przy własnym świecie strona „Prompt świata” (pomysł gracza z tabeli `worlds`), potem jedna tura na stronę (1040 x 680 px, na wydruku A4 poziomo): po lewej obraz sceny (a gdy go nie ma, tło lokacji),
  po prawej komenda gracza, narracja i dymki z dialogami. Za długi tekst najpierw się zmniejsza, potem narracja
  jest skracana („…”), a na końcu chowają się ostatnie dymki. Na telefonie strony są jedna pod drugą bez stałego rozmiaru.
  Dane daje `GET /api/games/{id}/comic`, bez dodatkowych zapytań do modelu. Zapis do PDF: przycisk „Drukuj”.
  Komiks każdej gry (także niedokończonej) otworzysz też z menu: **Zapisane gry**, przycisk „Odpal komiks”.
* **Lektor** (przycisk na scenie albo klawisz L) czyta nową turę głosem przeglądarki (Web Speech API, bez serwera).
  Narrator w grze podaje płeć mówiących (`gender` w `dialogue`, w odpowiedzi API pole `voices` tury), więc kobiety
  czyta kobiecy głos, a mężczyzn męski. Bez płci lektor zgaduje po końcówce imienia. Naturalne polskie głosy
  (Marek, Zofia) są w Edge. W Chrome zwykle jest tylko głos kobiecy, wtedy męski to ten sam głos z niższym tonem.
* Dotyczy to tylko gry w przeglądarce. Eksperymenty (`app.eval.run`) mają ten sam prompt i format JSON co wcześniej.

Gra zapamiętuje bieżącą rozgrywkę w przeglądarce, więc po odświeżeniu strony wracasz do niej.
Po restarcie serwera gra odtwarza się z bazy (patrz „Zapisane gry”) i można grać dalej.

## Testy

```bash
docker compose exec app pytest -v
```

Poprawny wynik wygląda tak (liczby mogą być inne, ważne, żeby nie było `failed`):
```
21 passed, 1 skipped
```
Jeden test jest pominięty, jeśli nie masz uruchomionej Ollamy (patrz niżej). To normalne.

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

## Wybór modelu narratora

Połączenie z modelami idzie przez bibliotekę **LiteLLM**, więc zmiana modelu to zmiana
jednej linijki w `.env` (`NARRATOR_MODEL`) albo pola „Model narratora” w menu (Ustawienia deweloperskie).

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

## Własne API do tekstu i obrazów

Nie musisz edytować `.env`, żeby zagrać na swoim koncie u dostawcy modeli.
Wszystko ustawisz w menu, w panelu **Ustawienia deweloperskie**. Ustawienia działają tylko dla tej jednej gry.

### Model tekstowy (narrator)

1. W polu **Model narratora** wybierz **Inny model (wpisz nazwę)** i wpisz nazwę w formacie LiteLLM:
   `<dostawca>/<model>`.
2. Rozwiń **Własne API modelu tekstowego** i wpisz:
   * **Adres API**: potrzebny tylko dla serwerów zgodnych z API OpenAI (vLLM, LM Studio, OpenRouter itp.).
     Dla OpenAI, Anthropic i Gemini zostaw puste.
   * **Klucz API**: twój klucz. Puste = klucz z `.env`.
3. Kliknij **Zacznij**. Przy nazwie modelu pojawi się zielona kropka z opisem „własne API”.

| Dostawca | Model narratora | Adres API |
|---|---|---|
| OpenAI | `openai/gpt-4o-mini` | puste |
| Anthropic | `anthropic/claude-haiku-5-5` | puste |
| Google Gemini | `gemini/gemini-3.8-flash` | puste |
| OpenRouter | `openrouter/<model>`, np. `openrouter/meta-llama/llama-3.1-8b-instruct` | puste |
| Groq, Mistral, DeepSeek… | `groq/<model>`, `mistral/<model>`, `deepseek/<model>` | puste |
| vLLM, LM Studio, inny serwer zgodny z OpenAI | `openai/<nazwa-modelu>` | np. `http://host.docker.internal:1234/v1` |

Pełna lista dostawców: [docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers).
Serwer działający na twoim komputerze (poza kontenerem) jest widoczny pod adresem `host.docker.internal`, nie `localhost`.

### Obrazy (tła i sceny)

W polu **Grafika** wybierz, kto rysuje:

| Opcja | Kiedy | Co wpisać |
|---|---|---|
| **Serwer obrazów z .env** (albo **Bez obrazów**, gdy w `.env` nie ma `IMAGE_SERVER_URL`) | ustawienie domyślne | nic |
| **Własny serwer obrazów projektu** | masz uruchomiony `bench/images/consistency/serve.py` pod innym adresem | adres, np. `http://host.docker.internal:8420`, i generator |
| **Własne API obrazów** | chcesz rysować przez zewnętrzne API, np. OpenAI | model, np. `openai/gpt-image-1` albo `openai/dall-e-3`, klucz i rozmiar obrazu |

Własne API obrazów idzie przez LiteLLM, więc działa każdy dostawca obrazów, którego LiteLLM obsługuje
(OpenAI, Azure, Vertex AI, Bedrock, serwery zgodne z API OpenAI przez pole **Adres**).
Takie API rysuje tylko z opisu sceny, bez obrazów wejściowych, więc postacie mogą wyglądać
trochę inaczej w kolejnych turach. Serwer obrazów projektu rysuje sceny na podstawie stałego tła i portretów,
dlatego jest bardziej spójny.

Gemini: model np. `gemini/gemini-3.1-flash-image` (Nano Banana 2), adres pusty, klucz pusty albo `GEMINI_API_KEY` z `.env`.
Modele obrazów Gemini nie działają w darmowym planie, potrzebny jest klucz z włączonymi płatnościami.

Uwaga na koszty: każda tura to jeden obraz sceny, a nowa lokacja i nowa postać to dodatkowe obrazy.

### Gdzie trafiają klucze

* Klucz wpisany w oknie trafia tylko do serwera gry na twoim komputerze i stamtąd do dostawcy.
  Nie zapisuje się w bazie `data/dvn.sqlite` ani w odpowiedziach serwera.
* Po zaznaczeniu **Zapamiętaj adresy i klucze w tej przeglądarce** dane zostają w pamięci przeglądarki
  (localStorage), żeby nie wpisywać ich przy każdej grze. Nie zaznaczaj tego na cudzym komputerze.
* Na stałe (dla wszystkich gier i eksperymentów) klucze ustawiasz w `.env`: `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` albo `NARRATOR_API_BASE` i `NARRATOR_API_KEY`.

## Konta: administrator i gracze

Gdy w `.env` jest `ADMIN_PASSWORD=...`, gra wymaga logowania loginem i hasłem (strona `/login`, wylogowanie `/logout`).
Puste hasło = gra bez logowania, jak wcześniej. Stare `GAME_PASSWORD` działa jako hasło administratora.

- **Administrator** loguje się loginem `ADMIN_LOGIN` (domyślnie `administrator`). Ma wszystko, co zwykła gra,
  i **Panel administratora** (`/admin`, przycisk w menu).
- W panelu zakłada konto gracza: login, hasło, scenariusz (gotowy świat albo własny opis, limit tur, podpowiedzi, pamięć),
  model tekstowy (z `.env`, inny model, własny adres i klucz API) i grafikę (serwer obrazów z `.env`, inny serwer `serve.py`,
  API obrazów przez LiteLLM albo bez obrazów).
- Po zapisaniu serwer w tle buduje świat i zamawia pierwsze tło i portret bohatera. Stan konta: „gra się przygotowuje”,
  „gra gotowa” albo „błąd” (z opisem i przyciskiem **Ponów**). Lista odświeża się sama.
- **Gracz** po zalogowaniu od razu widzi swoją grę. Nie ma menu, ustawień ani panelu badawczego, nie widzi cudzych gier.
  Po końcu gry ma swój komiks. Uprawnienia sprawdza serwer (`app/auth.py`), nie tylko strona.
- **Nowa gra** w panelu daje graczowi nową grę z tymi samymi ustawieniami. Stara zostaje w **Zapisanych grach** administratora.
  Usunięcie konta nie usuwa rozegranych gier (zostają do metryk).
- Klucze API graczy są w bazie zaszyfrowane sekretem `SECRET_KEY` z `.env` (puste = losowy w `data/secret.key`).
  Nie wracają do przeglądarki. Zmiana albo utrata sekretu wylogowuje wszystkich, a klucze trzeba wpisać od nowa.
- Hasła graczy są w bazie tylko jako skrót (scrypt). Sesja trwa 30 dni, zmiana hasła wylogowuje tę osobę.
- Kod: `app/auth.py` (logowanie i uprawnienia), `app/admin.py` (panel i przygotowanie gier), `app/accounts.py`
  (hasła i szyfrowanie), `app/static/admin.html`, tabela `users` w `data/dvn.sqlite`.

## Gra z obrazami (serwer GPU instytutu)

Pierwsze uruchomienie na nowym koncie (Conda, kod, biblioteki) krok po kroku: [serwer_obrazow.md](serwer_obrazow.md).

Obrazy powstają w trakcie gry. Gra nie czeka na nie: tekst pojawia się od razu, a obraz po chwili.
Każda lokacja ma jedno stałe tło (wzorzec miejsca), a każda tura osobny obraz sceny rysowany na jego podstawie.
Bez serwera obrazów gra działa jak zwykle.

1. W `.env` ustaw `IMAGE_SERVER_URL=http://host.docker.internal:8420` i wykonaj `docker compose up -d --force-recreate app`.
2. Na serwerze GPU, przy wolnym GPU (`nvidia-smi`), uruchom serwer obrazów w `tmux`:
   ```bash
   eval "$(conda shell.bash hook)" && conda activate ~/data/conda/dvn-images
   cd ~/data/dvn && git pull && cd bench/images/consistency
   python serve.py
   ```
3. Na laptopie, przy włączonym VPN, w osobnym oknie terminala zestaw tunel i zostaw go otwartego:
   ```bash
   ssh -N -L 8420:127.0.0.1:8420 -i ~/.ssh/id_ed25519 <login>@<adres serwera>
   ```
4. Graj na http://localhost:8000. Generator grafiki wybierzesz w menu, w **Ustawieniach deweloperskich**
   (domyślny ustawia `IMAGE_MODEL` w `.env`). Styl obrazów bierze epokę z pola `visual_style` świata.
   Na GPU mieści się jeden model naraz, więc po zmianie generatora serwer wczytuje inny model i pierwszy obraz powstaje dłużej.
   Obrazy zapisują się w `data/images/`, a czasy i prompty w tabeli `images` bazy.
5. Po graniu obowiązkowo wyłącz serwer obrazów przez `Ctrl+C` (regulamin: żadnych usług działających na stałe).
   Dla pewności sam wyłączy się po 30 minutach bez zadań.

Obrazy i pomiary na jednym GPU się nie mieszczą: nie uruchamiaj gry z obrazami w trakcie pomiaru.

### Co trafia do modelu obrazów
Model obrazów dostaje opisy tylko po angielsku i bez imion postaci (imiona rysował jako napisy na obrazie).
- Świat ma pola do obrazów: `hero_look` (wygląd bohatera), `characters` (wygląd pozostałych postaci, także zwierząt)
  i `look` przy lokacji („Interior of …” albo „Exterior of …”). Twórca świata wypełnia je sam z pomysłu gracza,
  zaczynając od płci i wieku. Narrator ich nie widzi, więc eksperymenty się nie zmieniają.
- W grze narrator dopisuje do JSON-a po angielsku: `picture` (co widać w turze), `scene.look` (nowe miejsce)
  i `new_characters` (wygląd postaci, która pojawia się pierwszy raz).
- Postać jest rozpoznawana także po innej formie imienia („Senna” i „Senne”, „Bodo” i „szkiełkarz Bodo”),
  więc ma jeden portret i jeden opis na całą grę.
- Portrety postaci z wstępu powstają razem ze światem, przed pierwszą turą.
- Stare gry i światy bez tych pól dostają, jak wcześniej, wygląd z faktów i zdania z narracji po polsku.
- W promptach do obrazów nie ma zaprzeczeń („no”, „not”, „without”). Model obrazów rysuje każdą nazwaną rzecz:
  „no vines” dawało pnącza, „clock without hands” zegar ze wskazówkami. Szablony stylu w `app/config.py` mówią
  tylko, co ma być widać, wytyczne każą modelom pisać opisy bez zaprzeczeń, a `positive()` w `app/images.py`
  wycina zaprzeczone fragmenty, które mimo to przyjdą (także ze starych światów).

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

**5. Pomiar cache promptu (KV cache)** (VPN, ok. 15 minut):
```bash
python -m app.eval.kv_cache --reps 3 --tag kv1                  # oba modele, prompty 2k, 4k, 8k, 11k tokenów
python -m app.eval.kv_cache --summary data/eval/kv_cache.csv --tag kv1   # sama tabela z zapisanych wyników
```
Skrypt składa prompty z prawdziwej gry z bazy (jak pamięć `full_cached`) i mierzy czas do pierwszego tokenu (TTFT)
w 4 scenariuszach: pierwszy raz (`cold`), powtórka (`warm`), dopisanie następnej tury (`append`)
i zmiana początku (`invalidate`). Przed dłuższym pomiarem sprawdź obciążenie serwera na dashboardzie Grafana.

Gra domyślnie odbiera odpowiedź strumieniem i zapisuje w każdej turze `ttft_ms` (koniec czytania promptu)
i `first_answer_ms` (koniec myślenia modelu). Wyłączenie: `NARRATOR_STREAM=false` w `.env`.
