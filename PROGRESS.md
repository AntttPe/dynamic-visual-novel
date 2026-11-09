# Postęp projektu (wspólna pamięć zespołu i agentów)

Ten plik to pamięć projektu. Każdy agent czyta go na początku pracy, a przed pushem dopisuje,
co zrobił. Dzięki temu kolejna osoba (albo jej agent) wie, na czym stanęliśmy, bez pytania.

## Zasady aktualizacji

1. **Na początku pracy:** przeczytaj cały plik i `CLAUDE.md`. Sprawdź „Zadania w toku”,
   żeby nie robić tego samego co ktoś inny.
2. **Gdy zaczynasz zadanie:** wpisz się w „Zadania w toku” (kto, co, od kiedy). Zrób osobny mały commit
   i push, żeby inni od razu to widzieli.
3. **Przed każdym pushem z większą zmianą:**
   - dopisz wpis NA GÓRZE sekcji „Dziennik” (nowe wpisy wyżej, starsze niżej),
   - popraw „Stan projektu”, jeśli coś zaczęło albo przestało działać,
   - przenieś skończone zadanie z „Zadań w toku” do „Dziennika”,
   - dopisz decyzję do „Decyzji”, jeśli coś ustaliliście (np. wybór modelu, zmiana metryki).
4. **Konflikt w tym pliku przy `git pull`:** zostaw OBA wpisy, nic nie usuwaj.
   Najpierw `git pull --rebase`, potem push.
5. Pisz krótko i konkretnie. Wpis w dzienniku to 2 do 6 punktów, nie esej.
6. Po polsku, bez długich myślników. Bez kluczy API, haseł i adresów serwerów uczelni (repo jest publiczne).

Co jest „większą zmianą”: nowa funkcja, zmiana sposobu uruchamiania, zmiana scenariusza albo metryki,
nowe wyniki badań, nowa zależność. Literówki i drobne poprawki nie wymagają wpisu.

Wzór wpisu w dzienniku:

```
### RRRR-MM-DD, Imię: krótki tytuł
- Co zrobione: ...
- Pliki: ...
- Wyniki / jak sprawdzić: ...
- Uwaga dla następnych: ... (co nie działa, na co uważać, co dalej)
- Commit: abc1234
```

## Stan projektu

**Działa:**
- Gra w przeglądarce (`http://localhost:8000`) w jednym kontenerze Docker (macOS, Windows/WSL2, Linux).
- Narrator przez LiteLLM: tryb `demo` bez modelu, Ollama na hoście, modele prowadzącego
  `openai/strata-big` i `openai/large-reasoning` (wymagają VPN instytutu, klucz w `.env`).
- Stan świata z faktami niezmiennymi i walidatorem, pamięć `full`, `window` i `full_cached` (pod cache serwera),
  każda tura w `data/dvn.sqlite` (z `tokens_cached`, `ttft_ms` i `first_answer_ms`, odpowiedź strumieniem).
- Cache promptu działa na obu modelach. Pomiar TTFT na promptach z gry: `python -m app.eval.kv_cache` (Dziennik 2026-11-03).
- Scenariusze badawcze (`app/eval/scenarios/`, aktualny `main_v2`), runner ze wznawianiem po zerwaniu VPN,
  metryki M1, M2 (bez gaslightingu), M4 i raport w terminalu. Opis komend: README, sekcja „Eksperymenty”.
- Metryki dodatkowe X1 do X5 i porównanie „ze stanem minus bez stanu” na parach seedów (McNemar, bootstrap,
  przedziały Wilsona): `python -m app.eval.extra_metrics --tag <tag> [--csv plik] [--names 20]`.
- Pełne badanie `long50` (3 modele × 25 gier ze stanem + 25 bez), wyniki w Dzienniku 2026-10-28.
- Gra z obrazami na żywo przez serwer GPU i tunel SSH (README, sekcja „Gra z obrazami”): tło lokacji, portret postaci
  i obraz sceny w każdej turze, generator do wyboru przy nowej grze. Czasy i prompty w tabeli `images`.

**Nie ma jeszcze:**
- Sędzia LLM (M3 dziwne komendy, gaslighting w M2).
- Wyniki Gemini (darmowy klucz: 20 zapytań dziennie, za mało na badanie).
- Wykresy i raport dla prowadzącego.

**Znane problemy:**
- VPN rozłącza się przy wygaszaczu ekranu i bez powodu (macOS i Windows). Na macOS `caffeinate -di` (README),
  na Windows wyłącz usypianie i wygaszacz. Runner i tak wznawia po powrocie VPN.
- `large-reasoning` jest wolny (mediana 34 s, p95 150 s na turę) i w 2,6% tur nie daje poprawnego JSON.
- `--no-state` ukrywa w prompcie także listę lokacji, nie tylko stan. Spadek M4 bez stanu wynika głównie z tego (zadanie P3).
- `strata-big`: kilka gier naraz psuje sobie cache (wspólny początek promptu, sesje się nadpisują). 4 gry naraz: 0 trafień,
  2 gry: trafia tylko jedna. Gry `full_cached` na `strata-big` uruchamiać po kolei.
- `strata-big` z wymuszonym JSON oddaje całą odpowiedź naraz, mimo strumienia. Jego `ttft_ms` w grze to czas
  całej tury (TTFT mierzyć skryptem `kv_cache`, bez JSON). Ważne dla Z4c. `large-reasoning` strumieniuje normalnie.
- `large-reasoning` przy domyślnym `NARRATOR_MAX_TOKENS` (1200) potrafi uciąć myślenie przed JSON. Ponowienia dają tury po 2,5 min.
- `strata-big` 2026-11-08 chwilami nie odpowiadał przez ponad 150 s (przyczyna po stronie serwera, niepotwierdzona).
- Obrazy w grze: portrety słabo oddają polskie opisy (np. Borwin bez rudych włosów) i bywają do siebie podobne,
  czasem pojawia się drobny tekst na obrazie, a akcja sceny bywa pominięta (np. brak wędki).

## Metryki sprintu (ustalone)

| Metryka | Co mierzy | Jak oceniane |
|---|---|---|
| M1 pamięć faktów | czy model pamięta fakt podany przez gracza po k turach | szukanie słowa z `accept` w odpowiedzi |
| M2 fakty niezmienne | czy da się zmienić fakt niezmienny (pytanie, próba zmiany, gaslighting) | słowa i walidator, gaslighting: sędzia LLM |
| M3 dziwne komendy | czy reakcja na absurd jest logiczna i w roli | sędzia LLM według kryterium z YAML |
| M4 spójność lokacji | czy location_id zgadza się z oczekiwanym i między wizytami | porównanie z YAML |

## Zadania w toku

Wpisz się w kolumnę „Kto”, zanim zaczniesz (osobny mały commit i push). Opisy zadań są niżej.

**Sprint 5 (od 2026-11-08), wymagania prowadzącego (DoD: więcej testów grafik, inne modele i adaptery,
testy całości narrator + grafika, screenshoty GUI):**

Kod pomiaru obrazów: `bench/images/consistency/` (README tam, strona z komendami na serwer u Antka).
Nowy model = nowa klasa w `models.py` (wzór: `Flux2Klein`, `Qwen21Turbo`) i test na modelu na niby.
Na serwerze GPU pobrane są już: FLUX.2 klein 4B, SDXL + IP-Adapter, Qwen-Image-2.1-Turbo i modele ocen.

| Kto | Zadanie | Wymaga | Od kiedy |
|---|---|---|---|
| Dudsztor | G1a. Wykrywanie postaci na obrazach Qwena. Próg 0.1 daje 9/9, zostało obejrzeć wycięte postacie (Dziennik 2026-11-09) | GPU | 2026-11-08 |
| Dudsztor | G1b. Pełny pomiar obrazów: 22 sceny, 2 seedy, 4 modele. Zrobione (Dziennik 2026-11-09, pełny pomiar) | GPU | 2026-11-09 |
| (wolne) | G1c. Nowe miary: duplikaty postaci i sędzia obrazów (łączy się z Z5) | VPN, GPU | |
| (wolne) | G2a. Nowe modele obrazów (lista niżej) | GPU | |
| Dudsztor | G2b. Adaptery tożsamości postaci. Zrobione: IP-Adapter Face (Dziennik 2026-11-09). PuLID i InstantID odłożone | GPU | 2026-11-08 |
| (wolne) | G3a. Eksport prawdziwej gry do zestawu scen dla obrazów | VPN | |
| (wolne) | G3b. Test całości: gra z narratorem, potem obrazy do każdej tury, czas i spójność | VPN, GPU, po G3a | |
| (wolne) | G4. Screenshoty GUI do raportu | nic (tryb `demo`) albo VPN | |

**Sprint 4 (od 2026-11-03), wymagania prowadzącego (DoD: KV cache, model image-to-image, optymalizacja czasu):**

Zadania oznaczone „GPU” wymagają serwera GPU instytutu (dostęp: Antek, Krzysiek). Reszta wymaga tylko
VPN instytutu i klucza do modeli w `.env`. Zadania są niezależne, chyba że w opisie jest „po”.

| Kto | Zadanie | Wymaga | Od kiedy |
|---|---|---|---|
| Antek | Z1. Architektura pomiarowa obrazów. Zrobione: krótka gra na 3 modelach (Dziennik 2026-11-05), dalej w G1 | GPU | 2026-11-03 |
| (wstępnie) | Z2. Wybór modelu image-to-image: FLUX.2 klein (szybki) albo Qwen-Image 2.1 (dokładniejszy), rozstrzygnie G1 | GPU | |
| (wstrzymane) | Z4a. Myślenie narratora: wyłączyć albo ograniczyć. Wstrzymane 2026-11-03: nie zmieniamy parametrów modeli (Decyzje) | VPN | |
| Krzysiek | Z4b. Badanie `full_cached` vs `window/8`. Zrobione: 40 gier (Dziennik 2026-11-04) | VPN | 2026-11-03 |
| (wolne) | Z4c. Strumieniowanie narracji do UI | nic (tryb `demo`) | |
| Dudsztor | Z4d. Obrazy w tle i cache po `location_id` w grze. Zrobione (Dziennik 2026-11-09) | GPU | 2026-11-08 |
| (wolne) | Z5. Czy `large-reasoning` przyjmuje obrazy, sędzia spójności obrazów | VPN | |

**Sprint 3, wymagania prowadzącego (DoD):**

| Kto | Zadanie | Od kiedy |
|---|---|---|
| (wolne) | S1. SOTA: czy ktoś zrobił coś podobnego | |
| (wolne) | S2. Research: lokalne modele graficzne, proof-of-concept | |
| (wolne) | S3. Research: lokalne modele językowe (gemma-4-26b-A4B-it i inne) | |
| (wolne) | S4. Scenariusz: wygenerowany na początku vs halucynowany on-the-fly, proof-of-concept | |
| (wolne) | S5. Metryki automatycznej oceny jakości rozgrywki | |

**Z poprzednich sprintów (nadal otwarte):**

| Kto | Zadanie | Od kiedy |
|---|---|---|
| (wolne) | P1. Sędzia LLM dla M3 i gaslightingu w M2 | |
| (wolne) | P2. Badanie `full_cached` vs `window/8` na pełnym scenariuszu | |
| (wolne) | P3. Rozdzielić `--no-state` na stan i listę lokacji | |
| (wolne) | P4. Wykresy i raport z `long50` | |

### Opisy zadań

**G1a. Wykrywanie postaci na obrazach Qwena.** W krótkiej grze v2 detektor osób OWLv2 (`score.py`) znalazł postacie
tylko na części obrazów Qwena (np. 1 z 9 w wariancie z obrazem wzorcowym), na FLUX i SDXL na wszystkich.
Obrazy Qwena są RGBA i 1280x704. Sprawdzić: konwersję kanału alfa (czy tło nie jest przezroczyste), próg detektora,
wymiary. Dane do debugowania: `data/dvn-results/short-v2` u Antka (nie ma ich w repo).
Wynik: `score.py` znajduje postacie na obrazach wszystkich modeli, test na małym obrazie, jeśli się da bez GPU.

**G1b. Pełny pomiar obrazów.** `testset.yaml` (22 sceny, powroty 20 do 1, 19 do 3, 17 do 5, 15 do 2, 14 do 4),
modele: `flux2-klein-4b`, `qwen-image-21-turbo` (ok. 18 s na scenę, ok. 2 h na seed) i `sdxl-ip` jako punkt odniesienia.
Najpierw `--seeds 1`, potem dorobić seedy tą samą komendą. Wynik: raport, wnioski w Dzienniku, wybór modelu (Z2).

**G1c. Nowe miary spójności.**
- Duplikaty: na obrazie jest więcej osób niż postaci w scenie (SDXL robi to często, FLUX czasem). Detektor już zwraca ramki,
  trzeba zliczać osoby i porównać z liczbą postaci. Uwaga: w tle mogą być przechodnie, więc liczyć tylko duże ramki.
- Sędzia obrazów: model multimodalny dostaje wzorzec postaci i wycinek ze sceny i ocenia „ta sama osoba?” (zadanie Z5,
  najpierw sprawdzić, czy `large-reasoning` przyjmuje obrazy). Ręczna weryfikacja ok. 20 ocen.
- Zgodność z kartą postaci: czy szczegóły z opisu są na obrazie (np. blizna na lewej dłoni, opaska na oku).
  W krótkiej grze FLUX rysował bliznę na twarzy, Qwen na dłoni. Kandydat do sędziego obrazów.

**G2a. Nowe modele obrazów.** Każdy: licencja, VRAM, czas, czy przyjmuje kilka obrazów wejściowych. Kandydaci:
- FLUX 3 Image Klein (`flux3-klein`, adapter już jest): do 10 obrazów wejściowych, wymaga akceptacji licencji i tokenu
  Hugging Face (token tylko na czas sesji, instrukcja w README pomiaru).
- Qwen-Image-2.1 bez Turbo (40 kroków): czy lepsza jakość jest warta czasu.
- Qwen-Image-Edit-2511 (20B, Apache 2.0): deklarowana poprawa spójności postaci, na 24 GB tylko z odciążaniem.
- FLUX.2 klein 9B (licencja niekomercyjna, ok. 29 GB): z odciążaniem do RAM.
- Inne otwarte modele edycji z wieloma obrazami wejściowymi, jeśli się pojawią. Qwen-Image 3.0 nie ma otwartych wag.

**G2b. Adaptery tożsamości postaci.** Moduły dokładane do modelu, które trzymają wygląd konkretnej osoby:
IP-Adapter Plus Face i FaceID (SDXL), PuLID (FLUX), InstantID (SDXL), ewentualnie LoRA trenowana na wzorcach postaci
(cięższe, osobne zadanie). Ten sam test i te same miary co G1, żeby porównać z obrazem wzorcowym bez adaptera.

**G3a. Eksport gry do scen.** Skrypt (np. `app/eval/export_scenes.py`): bierze rozegraną grę z bazy (`turns`: `location`,
`scene_description`, `characters_present`, narracja) i zapisuje zestaw scen w formacie `testset.yaml` (postacie,
lokacje, sceny, powroty wykryte po `location_id`). Opis wyglądu postaci: ze świata (`app/worlds/`) albo z pierwszego
opisu w narracji. Test bez modelu na zapisanej grze z FakeLLM.

**G3b. Test całości (narrator + grafika).** Gra `main_v2` na `strata-big` z `full_cached`, eksport (G3a), potem obrazy
na serwerze GPU tym samym `run.py`. Mierzyć: czas od komendy gracza do tekstu i do obrazu (suma, bo obrazy liczymy
partiami), spójność postaci i lokacji w prawdziwej grze, ile tur zmienia lokację (cache tła po `location_id`).
Na serwerze GPU nie uruchamiamy usług na stałe (regulamin), dlatego obrazy liczymy partiami po grze, a nie na żywo.

**G4. Screenshoty GUI.** Zrzuty ekranu gry w przeglądarce: start gry, kilka tur, panel z promptem i stanem świata,
wybór modelu. Najlepiej z prawdziwym modelem (`strata-big`), awaryjnie tryb `demo`. Do `docs/screenshots/`
z krótkim opisem w `docs/screenshots/README.md`. Sprawdzić przed commitem, czy na zrzutach nie ma klucza API
ani adresów serwerów uczelni (repo jest publiczne). Jeśli powstaną obrazy z G3b, dodać zrzut gry z tłem.

**Z1. Architektura pomiarowa obrazów.** Powtarzalne stanowisko do porównywania modeli pod spójność postaci
i lokacji. Założenie od innej grupy badawczej (u nas jeszcze niezmierzone): bez obrazu wejściowego modele szybko
się rozjeżdżają, więc bohatera i inne postacie trzeba podawać jako obraz. To samo sprawdzamy dla teł lokacji.
- Miejsce: `bench/images/` (torch i diffusers poza kontenerem gry). Dziś benchmark obsługuje tylko tekst na obraz
  i jest ustawiony pod RunPod, więc trzeba go dostosować do serwera instytutu (zasady niżej).
- Wejście: plik ze stałymi testami: postacie i lokacje z obrazem wzorcowym oraz sekwencja scen
  (ta sama postać w różnych miejscach, powroty do tej samej lokacji).
- Warianty: bez obrazu (punkt odniesienia), zawsze ze wzorca, łańcuch (każdy obraz z poprzedniego).
- Modele za wspólnym interfejsem, żeby nowy model wymagał tylko małego adaptera. Stałe seedy.
- Wyjście: obrazy i jeden plik z wynikami na obraz (model, wariant, seed, krok, czas, szczyt VRAM, ładowanie modelu).
  Wznawianie po przerwaniu, bo maszyna jest niestabilna.
- Metryki: podobieństwo do wzorca w zależności od kroku k (rozjeżdżanie się, jak recall@k w M1),
  postać: embeddingi twarzy lub DINOv2/CLIP, lokacja: DINOv2/CLIP, zgodność z opisem sceny: CLIPScore,
  czas i VRAM. Do sprawdzenia: czy detektor twarzy działa na grafikach, inaczej same DINOv2/CLIP.
- Wynik: jedna komenda uruchamia macierz modele × warianty × seedy i daje raport obok siebie.

**Z2. Wybór modelu image-to-image.** Pomiar na Z1 (`bench/images/consistency/`). Modele w adapterach:
`sdxl-ip` (SDXL + IP-Adapter, punkt odniesienia), `flux2-klein-4b` (FLUX.2 [klein] 4B, Apache 2.0, ok. 13 GB VRAM,
4 kroki) i `flux3-klein` (FLUX 3 Image Klein z 2026-10-15, 5,6B, do 10 obrazów wejściowych, licencja FLUX Kommunity,
gated na HF; w pełnej precyzji ponad 24 GB, więc z odciążaniem do RAM). „NoGPU” z wyszukiwania to hasło reklamowe,
nie osobny model. Wynik: decyzja, który model wpinamy do gry.

**Z3. Pomiar KV cache przez TTFT.** Najpierw przeczytaj „Wnioski z noty prowadzącego o modelach” niżej.
- Dodać do `app/llm/litellm_client.py` tryb strumieniowania i zapis TTFT (czas do pierwszego tokenu) w `turns`,
  tak jak `tokens_cached` (kolumna z migracją w `app/storage/db.py`). Bez tego cache na `large-reasoning` jest
  niewidoczny, bo vLLM nie zgłasza `cached_tokens`.
- Skrypt pomiarowy (np. `app/eval/kv_cache.py`): 4 scenariusze z noty (zimny, powtórka, dopisanie, zmiana początku)
  na prawdziwych promptach z gry (`turns.prompt` w bazie), oba modele, po kilka powtórzeń, zapis do CSV.
- Wynik: tabela TTFT jak w nocie, ale dla naszych promptów, z godziną pomiaru. Testy bez modelu (FakeLLM).

**Z4a. Myślenie narratora.** Oba modele myślą przed odpowiedzią (`strata-big`: budżet do 2048 tokenów).
Z naszych danych (szacunek z liczby znaków na token): ok. 40% tokenów wyjściowych `strata-big` i ponad połowa
u `large-reasoning` to ukryte myślenie, czyli 10 do 20 s na turę.
- Sprawdzić, które parametry serwer przyjmuje: `reasoning_effort` („low”, „none”) i dla Qwen
  `extra_body={"chat_template_kwargs": {"enable_thinking": false}}`. Zmierzyć tokeny wyjściowe i czas.
- Jeśli działa: opcja w konfiguracji gry (`.env` i runner, np. `--thinking off`), domyślnie bez zmian.
- Badanie: `main_v2`, myślenie włączone vs wyłączone, ok. 5 gier na wariant. Mierzyć czas tury, JSON, M1, M2, M4.
  Pytanie: ile czasu zyskujemy i czy spada jakość.

**Z4b. Badanie `full_cached`.** Jak P2, ale na obu modelach (`large-reasoning` ma cache od początku, `strata-big`
od 2026-11-03). Seedy z `long50`, ok. 5 gier na wariant na start. Mierzyć czas tury, TTFT (po Z3), `tokens_cached`,
M1, M2, M4. Nie więcej niż kilka gier naraz: `strata-big` ma 32 sloty cache wspólne dla wszystkich studentów.

**Z4c. Strumieniowanie do UI.** Narracja pojawia się w przeglądarce w trakcie generowania, a nie po całej turze.
Problem: odpowiedź to JSON, więc trzeba wyciągać pole `narration` w locie. FastAPI (np. Server-Sent Events)
i obecny UI w `app/static/` (czysty JS, bez frameworków). Działa w trybie `demo`, więc nie wymaga VPN.
Miara: czas do pierwszego widocznego słowa.

**Z4d. Obrazy w grze.** Po Z2. Generowanie tła w tle (gra nie czeka na obraz), cache po `location_id`,
stały styl i seed. Gra działa dalej bez obrazów, gdy serwer GPU jest niedostępny.

**Z5. Obrazy w `large-reasoning`.** Prowadzący pisze, że `large-reasoning` powinien przyjmować obrazy
(tabela w nocie podaje tylko tekst). Sprawdzić wysłanie obrazu w formacie OpenAI (`image_url` z base64).
Jeśli działa: prototyp sędziego spójności, który dostaje obraz wzorcowy postaci lub lokacji i nowy obraz
i ocenia, czy to ta sama postać lub miejsce (skala i krótkie uzasadnienie). To dodatkowa miara do Z1 obok DINOv2/CLIP.

**S1. SOTA.** Przegląd prac i projektów, w których LLM prowadzi interaktywną fabułę: gry tekstowe
z narratorem AI, badania nad spójnością narracji i pamięcią długich rozmów, generowanie obrazów spójnych
w czasie. Wynik: krótka lista (nazwa, link, co robią, czym się różnimy) w `docs/sota.md`.
Pytanie do odpowiedzi: co u nas jest nowe (np. pomiar spójności faktów i lokacji na stałych scenariuszach).

**S2. Lokalne modele graficzne (proof-of-concept).** Cel: tło lokacji generowane lokalnie z `scene.description`,
z cache po `location_id` (ta sama lokacja = to samo tło). Tropy:
- „NoGPU Flux3 Klein”: znalezione przez Antka, podobno bardzo szybkie. Do sprawdzenia: co to dokładnie jest,
  licencja, czy działa bez GPU (Mac, CPU), czas jednego obrazu.
- Maszyna z RTX 4090 od prowadzącego: dostępna do testów, ale niestabilna. Nie opierać na niej gry,
  tylko pomiary. Gotowy benchmark: `bench/images/` (SD 1.5, SDXL Turbo, SDXL, FLUX.1 schnell).
- Mac M (Apple Silicon) jako opcja lokalna dla zespołu.

Wynik: tabela model × sprzęt (czas obrazu, VRAM, jakość na 5 scenach z `bench/images/prompts.json`)
i decyzja, który model wpinamy do gry.

**S3. Lokalne modele językowe.** Sprawdzić `gemma-4-26b-A4B-it` (MoE, ok. 4B aktywnych parametrów,
powinna być szybka) i inne lokalne modele na tym samym scenariuszu `main_v2`. Mamy już wynik
`llama3.1:8b` w `long50` (słaba pamięć faktów: M1 31%). Uruchamianie przez Ollamę na hoście
(`ollama_chat/<model>`) albo na maszynie z GPU. Wynik: M1, M2, M4, JSON, czas tury obok modeli prowadzącego.

**S4. Scenariusz: z góry czy na żywo.** Dwa tryby fabuły do porównania:
- wygenerowany na początku: model najpierw tworzy plan historii (wątek główny, kluczowe wydarzenia,
  zakończenie), potem prowadzi grę, trzymając się planu,
- halucynowany on-the-fly: jak teraz, model wymyśla wszystko na bieżąco.

Proof-of-concept: tryb „plan na początku” w silniku (plan zapisany jak stan świata, w prompcie)
i krótki test na `main_v2`. Pytanie badawcze: czy plan poprawia utrzymanie wątku głównego.

**S5. Metryki jakości rozgrywki (automatyczne).** Obecne metryki mierzą spójność (fakty, lokacje).
Brakuje oceny, czy gra jest dobra: postęp w wątku głównym (np. odległość od celu z planu z S4),
różnorodność i powtarzalność tekstu (X4 już jest), zmyślone byty (X3), sensowność reakcji (sędzia LLM, P1),
spójność obrazów (CLIP/DINOv2, po S2). Wynik: propozycja 3 do 5 metryk z opisem, jak je liczyć
automatycznie, w tym pliku w sekcji „Metryki”.

**P1. Sędzia LLM.** Model ocenia odpowiedź narratora według kryterium z YAML (M3) i to, czy narrator
przytaknął gaslightingowi (M2). Ocena krzyżowa (model nie ocenia sam siebie), temperatura 0,
ręczna weryfikacja ok. 20 ocen i zgodność z człowiekiem.

**P2. Badanie `full_cached`.** Działa na `strata-big` od 2026-10-30 (Dziennik, test `cache_fix`: tura ok. 17 s
zamiast 41 s, 1 gra). Zostało pełne badanie na seedach z `long50`: czas tury, `tokens_cached`, M1, M2, M4.
`large-reasoning` nie ma cache po stronie serwera.

**P3. `--no-state`.** Teraz ukrywa stan świata i listę lokacji naraz, więc spadek M4 bez stanu
mierzy głównie brak listy lokacji. Dwie osobne flagi i powtórka porównania.

**P4. Wykresy.** M1 w zależności od k dla każdego modelu, porównanie ze stanem/bez stanu, czasy tur.
Dane `long50` są tylko u Dudsztora (`data/dvn.sqlite`), trzeba je wymienić albo wyeksportować do CSV.

### Wnioski z noty prowadzącego o modelach (2026-11-03)

Nota jest na wiki przedmiotu (link u Antka). Najważniejsze dla nas:
- `large-reasoning`: Qwen3.8-27B FP8 na vLLM, 5 kart RTX 4080. Generuje 17 do 20 tokenów/s, czyta prompt
  1000 do 1800 tokenów/s. Cache prefiksu działa automatycznie, ale vLLM NIE zgłasza `cached_tokens`:
  sprawdzamy go po TTFT. Cache obejmuje tylko pełne bloki po 784 tokeny, reszta jest liczona od nowa.
- `strata-big`: Qwen3.8-Flash-Next, MoE 180B (ok. 22B aktywnych), osobny silnik (wagi w RAM, jedna RTX 4080).
  Generuje 22 do 28 tokenów/s. Cache włączony 2026-11-03: 32 sesje w RAM wspólne dla wszystkich studentów,
  przy dużym ruchu najstarsze są usuwane. Myśli przed odpowiedzią (budżet 2048 tokenów, `reasoning_effort` „medium”).
- TTFT z noty: z cache ok. 0,1 s (`strata-big`) i 0,15 do 1 s (`large-reasoning`), bez cache 2 do 15 s
  zależnie od długości promptu.
- Złota zasada: stały początek, zmienne dane na końcu, historii nie zmieniać, tylko dopisywać.
  Każda zmiana na początku (data, ID sesji) unieważnia cache całego promptu. Nasz `full_cached` jest zgodny z tą zasadą,
  a `window/8` nie (okno się przesuwa i zmienia początek historii).
- Obciążenie serwera i kolejki widać na dashboardzie Grafana (adres w nocie). Sprawdzać przed długimi pomiarami.
- Ceny w nocie są odwrotne niż te, które zwraca serwer (`/model/info`). Na budżet nie ma to wpływu.

### Zasady serwera GPU instytutu

Dostęp mają Antek i Krzysiek przez wspólne konto `antpie` (klucze SSH, VPN instytutu). Adres u nich, nie wpisywać do repo.
- Na początku uzupełnić `PROJECT.md` w katalogu głównym serwera.
- Tylko środowiska Conda, `pip` wewnątrz nich. Bez `sudo apt-get` i bez instalowania innych VPN-ów.
- Przed startem `top`, `nvidia-smi`, `df -h`. Nie przerywać cudzych procesów.
- Modele, dane i wyniki w `~/data`, bo katalog domowy to mały dysk systemowy.
- Bez usług działających w trybie ciągłym (np. ollama), po testach wyłączyć, bo blokują GPU.
  Po pracy z Dockerem usunąć swoje kontenery i obrazy.
- Konto i dane są usuwane na końcu semestru, kopii nie ma: kod do repo, wyniki kopiować poza serwer.
  Po zakończeniu projektu usunąć swoje dane i środowiska.

### Otwarte problemy i pytania

- Cache na `large-reasoning` działa (zmierzone w Z3), ale nie jest zgłaszany w `cached_tokens` (vLLM). Widać go tylko po TTFT.
- W `full_cached` każda stara wiadomość gracza niesie kopię stanu świata z tamtej tury, więc prompt rośnie szybko
  (ok. 20k tokenów w turze 28 zamiast 5 do 7k przy `window/8`). Do sprawdzenia: stan tylko w ostatniej wiadomości.
  Uwaga (Antek): to złamie cache na `strata-big`. On trafia tylko wtedy, gdy nowy prompt to cały poprzedni prompt
  plus dopisane wiadomości (Dziennik 2026-10-30). Jeśli stan zniknie ze starej wiadomości, prompt przestaje być
  dopisaniem. `large-reasoning` (vLLM, najdłuższy wspólny początek) by na tym nie stracił. Mierzyć osobno dla obu modeli.
- Maszyna RTX 4090 prowadzącego jest niestabilna: tylko do testów, nie do gry ani długich badań.
- VPN zrywa się przy wygaszaczu ekranu i bez powodu. Długie badania z `caffeinate -di` (macOS).
- Dane badań są lokalne u każdego (`data/` nie jest w repo). Trzeba ustalić wspólny eksport (CSV) do raportu.
- Gemini: darmowy klucz ma 20 zapytań dziennie, za mało na badanie. Bez płatnego klucza odpada.
- X3 (zmyślone nazwy) ma precyzję ok. 55%, a M2 „próba zmiany” daje 100% wszędzie. Obie metryki
  wymagają poprawy albo sędziego.

## Decyzje

- **Jeden kontener i Python** (bez Node). Łatwiej uruchomić na trzech systemach.
- **Scenariusz pisany pod badanie**, nie badanie pod przypadkową rozgrywkę. Każdy model dostaje te same ruchy,
  temperatura 0.7, seed = 1000 + numer powtórzenia.
- **Wersje scenariuszy się nie mieszają.** Zmiana treści scenariusza = nowy plik albo wyższe `version`.
  `main_v1` zostaje dla porównania, aktualny jest `main_v2`.
- **M1 bez sędziego**, bo szukanie słowa jest pewne i darmowe. Sędzia tylko tam, gdzie słowa nie wystarczą.
- **Sędzia krzyżowo:** każdy model ocenia odpowiedzi drugiego, temperatura 0, ręczna weryfikacja ok. 20 ocen.
- **Badanie porównawcze: 50 gier na model, 25 ze stanem + 25 bez stanu** na tych samych seedach (1001 do 1025),
  porównanie parami. Pamięć domyślna `window/8`, temperatura 0.7. Warianty na przemian, żeby przy limicie
  zostały pełne pary.
- **Metryki X1 do X5** (`extra_metrics.py`) obok M1, M2, M4. X2 (podobieństwo opisów lokacji) jest leksykalne
  (Jaccard, trigramy) do czasu decyzji o embeddingach CLIP/tekstowych. X3 to heurystyka (precyzja ok. 55%).
- **Model przy limicie:** gdy skończy się limit tokenów lub zapytań, przechodzimy dalej i raportujemy tyle gier,
  ile się wykonało.
- **Parametrów modeli nie zmieniamy** (myślenie, `reasoning_effort`): optymalizujemy czas po naszej stronie (cache, prompt).
- **Gry `full_cached` na `strata-big` po kolei, nie równolegle**, bo równoległe gry nadpisują sobie cache.

- **Próg detektora postaci to 0.1** (było 0.15). Najlepszy wynik Qwena to ok. 0,14, a FLUX i SDXL ok. 0,27.
- **Adaptery na `insightface` odkładamy** (cięższe, ograniczenia licencji). IP-Adapter Face pomaga SDXL w powrotach postaci,
  ale SDXL z nim nadal wyraźnie ustępuje FLUX.2 klein (pełny pomiar G1b).

## Dziennik

### 2026-11-09, Dudsztor: pełny pomiar obrazów G1b (4 modele, 22 sceny, 2 seedy)
- Co zrobione: 1048 obrazów (`testset.yaml`, seedy 1001 i 2001, próg detektora 0.1). Poprawka braku pamięci Qwena przy 4 obrazach wejściowych.
- Pliki: `bench/images/consistency/models.py`, `tests/test_image_bench.py`. Wyniki: `~/data/dvn-results/full-v1` na serwerze GPU i u Dudsztora w `data/dvn-results/`.
- Wyniki (DINO, wyżej = bardziej podobne). Postać do wzorca: średnia z obu seedów. Powrót: 5 par scen, 15 lub 16 porównań na komórkę.

  | Model | Wariant | Postać do wzorca | Powrót postaci | Postać znaleziona | CLIPScore | s na scenę |
  |---|---|---|---|---|---|---|
  | flux2-klein-4b | text | 0,734 | 0,864 | 100% | 32,0 | 1,4 |
  | flux2-klein-4b | anchor | 0,768 | 0,903 | 100% | 32,4 | 5,7 |
  | flux2-klein-4b | chain | 0,728 | 0,822 | 99% | 31,7 | 5,7 |
  | flux2-klein-4b | layers | 0,893 | 0,876 | 100% | 29,5 | 6,0 |
  | qwen-image-21-turbo | text | 0,672 | 0,831 | 97% | 28,5 | 14,0 |
  | qwen-image-21-turbo | anchor | 0,841 | 0,900 | 92% | 30,7 | 17,5 |
  | qwen-image-21-turbo | chain | 0,782 | 0,873 | 100% | 28,9 | 17,1 |
  | qwen-image-21-turbo | layers | 0,835 | 0,894 | 96% | 26,3 | 30,1 |
  | sdxl-ip | text | 0,583 | 0,594 | 96% | 33,2 | 3,8 |
  | sdxl-ip | anchor | 0,689 | 0,725 | 94% | 32,2 | 3,9 |
  | sdxl-ip | chain | 0,559 | 0,583 | 97% | 30,2 | 3,9 |
  | sdxl-ip | layers | 0,742 | 0,772 | 100% | 28,7 | 8,6 |
  | sdxl-ip-face | anchor | 0,696 | 0,791 | 94% | 30,9 | 3,9 |
  | sdxl-ip-face | chain | 0,669 | 0,773 | 94% | 30,9 | 3,9 |
  | sdxl-ip-face | layers | 0,711 | 0,722 | 99% | 29,5 | 8,6 |

- Wnioski (różnice parami, bootstrap po scenach, 95% CI):
  - **Rekomendacja do gry: FLUX.2 klein 4B.** Qwen `anchor` trzyma postać lepiej niż FLUX `anchor` (+0,074, CI +0,037 do +0,109), ale kosztuje 3 razy więcej czasu,
    gubi więcej postaci (92% wobec 100%) i mocno zależy od seeda (0,887 i 0,786). W powrotach oba są równe (0,900 i 0,903).
  - FLUX `layers` ma najwyższe podobieństwo do wzorca (+0,125 wobec FLUX `anchor`, CI +0,085 do +0,165), ale częściowo z konstrukcji (wklejona postać)
    i gorzej zgadza się z opisem sceny (CLIPScore 29,5 wobec 32,4). Gra używa dziś sposobu `anchor`, `layers` nie jest w niej zrobione.
  - **Adapter Face: poprawka wniosku z krótkiego testu.** Pomaga SDXL w powrotach (`anchor` +0,084, CI +0,016 do +0,158; `chain` +0,168, CI +0,087 do +0,253)
    i w podobieństwie do wzorca w `chain` (+0,110). W `anchor` do wzorca bez różnicy (-0,002), w `layers` w granicach szumu. Mimo to SDXL Face `anchor` jest gorszy od FLUX `anchor` (-0,071).
  - Dwa seedy potrafią różnić się o ok. 0,1 (np. Qwen `anchor`, SDXL `layers`), więc różnice rzędu kilku setnych traktować ostrożnie.
- Uwaga dla następnych: Qwen w 2 z 44 scen `anchor` (4 obrazy wejściowe) dostaje je mniejsze (`output_resolution` 886 zamiast 1024) i znalazł tam tylko 3 z 6 postaci
  (mała próba, FLUX 6 z 6). `ref_max_side = 768` u Qwena nie oszczędza pamięci, bo pipeline skaluje obrazy z powrotem do ok. 1 Mpx, przez co mogą być rozmyte. Zostawione dla zgodności wyników.
  Powrót to mała próba. Porównań jest kilkanaście, więc pojedynczy wynik „pewny” też może być przypadkiem. Zostaje obejrzenie wycinków `crops/` (domknięcie G1a).
- Commit: ten wpis

### 2026-11-09, Dudsztor: obrazy na żywo w grze, wybór generatora, test IP-Adapter Face
- Co zrobione: połączenie interfejsu z generowaniem obrazów działa w prawdziwej grze (Z4d). Tło jest stałe dla lokacji, portret
  rysowany raz dla postaci, a scena tury dostaje tło i do 3 portretów jako obrazy wejściowe. Postacie, które zostały w innym miejscu,
  nie trafiają na scenę. Wypowiedzi są usuwane z promptu, bo powodowały napisy (9 z 9 obrazów z mową, 0 z 12 bez).
- Interfejs: tekst tury pod obrazem, opcjonalne „Dane techniczne”, pamięć `full_cached` i generator grafiki do wyboru przy nowej grze.
- Pliki: `app/images.py`, `app/main.py`, `app/static/`, `app/storage/db.py`, `bench/images/consistency/serve.py`, `models.py`, `run.py`, `score.py`.
- Wyniki w grze (FLUX.2 klein 4B): tła ok. 2 s, portrety 1,4 do 2,9 s, sceny z portretami 6 do 12 s.
- Test adapterów (`testset_short`, 1 seed, 6 scen, próg 0.1, wszędzie 9/9 wykrytych postaci). Kolumny: podobieństwo DINO do wzorca,
  to samo w scenach z jedną postacią, powrót postaci, sekundy na obraz:

  | Model | Wariant | DINO | Jedna postać | Powrót | s |
  |---|---|---|---|---|---|
  | flux2-klein-4b | anchor | 0,696 | 0,693 | 0,893 | 5,1 |
  | flux2-klein-4b | chain | 0,575 | 0,518 | 0,986 | 5,2 |
  | flux2-klein-4b | layers | 0,819 | 0,910 | 0,979 | 5,2 |
  | flux2-klein-4b | text | 0,615 | 0,505 | 0,895 | 1,4 |
  | qwen-image-21-turbo | anchor | 0,846 | 0,866 | 0,863 | 20,4 |
  | qwen-image-21-turbo | chain | 0,832 | 0,762 | 0,982 | 17,9 |
  | qwen-image-21-turbo | layers | 0,782 | 0,820 | 0,835 | 26,7 |
  | qwen-image-21-turbo | text | 0,661 | 0,533 | 0,941 | 14,7 |
  | sdxl-ip | anchor | 0,652 | 0,672 | 0,806 | 3,9 |
  | sdxl-ip | chain | 0,677 | 0,663 | 0,757 | 3,9 |
  | sdxl-ip | layers | 0,655 | 0,658 | 0,692 | 7,4 |
  | sdxl-ip | text | 0,570 | 0,613 | 0,641 | 3,7 |
  | sdxl-ip-face | anchor | 0,692 | 0,700 | 0,767 | 3,9 |
  | sdxl-ip-face | chain | 0,669 | 0,720 | 0,794 | 3,9 |
  | sdxl-ip-face | layers | 0,637 | 0,690 | 0,643 | 7,4 |
  | sdxl-ip-face | text | 0,570 | 0,613 | 0,641 | 3,7 |

- Wnioski: adapter Face podnosi podobieństwo SDXL do wzorca o 0,03 do 0,06 (do poziomu FLUX anchor), ale w anchor i layers pogarsza
  powroty postaci. Wynik mieszany, przy 1 seedzie w granicach szumu, więc na razie nie dodajemy adapterów na `insightface`.
  Qwen anchor najlepiej trzyma postacie, ale kosztuje ok. 20 s na scenę. FLUX layers to najlepszy kompromis, choć częściowo
  z konstrukcji (wklejona postać). Powrót ok. 0,98 w chain to głównie kopiowanie obrazu.
- Jak sprawdzić: `pytest -v` (123 testy bez modelu). Raport testu adapterów: `~/data/dvn-results/short-adapters` na serwerze GPU.
- Uwaga dla następnych: przełączanie generatora działa w testach na modelu na niby i w interfejsie, ale nie było jeszcze sprawdzone
  na prawdziwym GPU. Serwer ma ręcznie skopiowane `serve.py`, `models.py` i `run.py`: przed `git pull` przywróć te dwa ostatnie
  przez `git checkout --` i usuń `serve.py`. Dalej: G1b (`--threshold 0.1`), obejrzenie wyciętych postaci Qwena (domknięcie G1a).
- Commit: ten wpis

### 2026-11-08, Antek: zadania sprintu 5 z DoD prowadzącego
- DoD: więcej testów grafik, inne modele i adaptery, testy całości (narrator + grafika), screenshoty GUI.
- Zadania G1a do G4 z opisami. Z1 i Z4b oznaczone jako zrobione, Z2 wstępnie: FLUX.2 klein albo Qwen-Image 2.1.

### 2026-11-05, Antek: krótka gra v2 na 3 modelach (Z1)
- Co zrobione: `testset_short` v2 (poprawione warstwy), 1 seed, `~/data/dvn-results/short-v2`. Lokalnie u Antka.
- Czas sceny (mediana) i VRAM: FLUX.2 klein 1,4 s tekst / 4,9 s z obrazami / 4,6 s warstwy, 17 GB.
  Qwen-Image-2.1-Turbo 14,7 / 18,4 / 24 s, 22 GB (z odciążaniem do RAM, obrazy wejściowe zmniejszone do 768 px,
  bo pełne dały brak pamięci). SDXL 3,7 / 3,9 / 6,5 s, 12,7 GB. Do Qwena trzeba było doinstalować torchvision.
- Powrót runda 6 kontra 1, postacie, wariant z obrazem wzorcowym: FLUX 0,87 / 0,92, SDXL 0,81 / 0,80.
  Warstwy po poprawce: FLUX 0,98 / 0,98 (wcześniej dwie postacie na jednym sprite).
- Wzrokowo: Qwen najdokładniejszy i najwierniejszy opisowi (blizna na lewej dłoni, którą FLUX rysował na twarzy),
  FLUX dobry i najszybszy, SDXL często podwaja osoby i gubi wygląd Borwina.
- Problem: detektor osób (OWLv2) nie znalazł postaci na większości obrazów Qwena (np. anchor 1 z 9), więc liczby
  dla Qwena na wycinkach są niewiarygodne. Do sprawdzenia: obrazy Qwena są RGBA i 1280x704.

### 2026-11-05, Antek: Qwen-Image-2.1-Turbo i poprawka wariantu warstw
- Co zrobione: adapter `qwen-image-21-turbo` (Qwen-Image-2.1-Turbo, 7B, 8 kroków, do 10 obrazów wejściowych,
  Qwen Research License, odciążanie do RAM). Qwen-Image 3.0 nie ma otwartych wag (tylko API Alibaby), więc lokalnie
  testujemy 2.1. Prompt postaci w `layers` zawiera teraz tylko tę jedną postać i jej pozę, bez akcji z innymi osobami.
  Wersje: `testset_short` v2, `testset` v3. `run.py` nie miesza wyników różnych zestawów w jednym katalogu.
- Uwaga dla następnych: nowy przebieg krótkiej gry do `~/data/dvn-results/short-v2` (wszystkie 3 modele).
  Adapter Qwen nie był jeszcze uruchamiany na GPU. Czy model wymaga akceptacji licencji na HF, nie wiadomo.

### 2026-11-05, Antek: pierwszy test obrazów na serwerze GPU (Z1, krótka gra)
- Co zrobione: `testset_short.yaml` (6 scen, runda 6 wraca do rundy 1), 1 seed, 4 warianty, 2 modele bez tokenu HF:
  FLUX.2 klein 4B i SDXL + IP-Adapter, RTX 4090. Wyniki tylko lokalnie u Antka (`data/dvn-results/short`, 116 MB).
- Serwer: brak `git` i `tmux` (są w środowisku Conda z conda-forge), kanały Anacondy wymagają akceptacji ToS
  (używamy tylko conda-forge), GPU bywa zajęte przez innych (systemowa Ollama, trening innego studenta).
- Czas i pamięć:

  | model | sam tekst | z obrazami wejściowymi | VRAM | wczytanie |
  |---|---|---|---|---|
  | flux2-klein-4b | 1,5 s | 4,1 s (2 obrazy), 5,7 s (3 obrazy) | 17 GB | 127 s z pobraniem 16 GB |
  | sdxl-ip | 3,7 s | 3,9 s | 12,8 GB | 114 s z pobraniem |

- Spójność (DINOv2 na wycinkach postaci, 1 gra, wyniki orientacyjne). Powrót runda 6 kontra runda 1, postacie:
  FLUX anchor 0,86 (Aren) i 0,92 (Borwin), SDXL anchor 0,80 i 0,82, SDXL sam tekst 0,55 (Aren).
  Aren kontra pierwsze pojawienie się, średnio: FLUX text 0,71, anchor 0,78, SDXL text 0,40, anchor 0,73.
- Wnioski z obrazów (ocena wzrokowa, zgodna z liczbami):
  - FLUX.2 klein wyraźnie lepszy: Aren i Borwin rozpoznawalni w każdej scenie (szalik, opaska, broda).
    SDXL gubi wygląd, Borwin w ogóle nie ma rudych włosów ani opaski, bo SDXL czyta tylko 77 tokenów promptu.
  - Wzorzec lokacji „no people” jako obraz wejściowy daje puste miejsca (rynek bez ludzi w wariancie anchor),
    w wariancie sam tekst FLUX rysuje tłum.
  - Błędy do poprawy: FLUX w anchor potrafi podwoić postać (scena 5: dwóch Arenów), `chain` kopiuje poprzedni obraz
    (runda 6 prawie identyczna z rundą 1: 0,99), błąd wzorca się utrwala (blizna na twarzy zamiast na lewej dłoni
    we wszystkich scenach). `layers` w tym przebiegu nieważny: prompt postaci zawierał akcję z drugą osobą
    („talking to Borwin”), więc model rysował dwie postacie na jednym sprite.
- Uwaga dla następnych: przed pełnym pomiarem poprawić prompt postaci w `layers` (bez innych postaci w akcji)
  i rozważyć wzorce lokacji z ludźmi w tle. Miary DINO na wycinkach są czułe na pozę, potrzebny sędzia obrazów (Z5).

### 2026-11-04, Antek: test spójności obrazów w wersji 2 (Z1, kod bez pomiaru)
- Co zrobione: 22 sceny z zaplanowanymi powrotami (20 -> 1, 19 -> 3, 17 -> 5, 15 -> 2, 14 -> 4), osobny seed
  na scenę (wcześniej jeden seed na wszystkie sceny zawyżał spójność wariantu bez obrazu), czwarty wariant
  `layers` (tło z cache + postać ze swojego wzorca, wycięta przez rembg i nałożona, jak w visual novel),
  oceny na wycinkach postaci (detektor osób OWLv2) zamiast całych obrazów: podobieństwo do pierwszego
  pojawienia się postaci (k do 22), do wzorca, powroty kontra pierwsza wizyta, czy postać w ogóle jest.
  Raport: ranking wariantów po powrotach, tabela w zależności od k, runda 1 i 20 obok siebie.
- Pliki: `bench/images/consistency/` (`compose.py` nowy), `tests/test_image_bench.py`.
- Pełny pomiar: ok. 980 obrazów na 3 seedach, szacunek 2 do 3 h (najdłużej FLUX 3). Na start `--seeds 2`.
- Uwaga dla następnych: adaptery FLUX, OWLv2 i rembg nie były jeszcze uruchamiane na GPU, najpierw krótki test.

### 2026-11-03, Antek: stanowisko pomiaru spójności obrazów (Z1, kod bez pomiaru)
- Co zrobione: `bench/images/consistency/`: zestaw testowy (3 postacie, 3 lokacje, 10 scen), runner z wariantami
  `text`, `anchor`, `chain` i wznawianiem, adaptery `sdxl-ip`, `flux2-klein-4b`, `flux3-klein`, oceny DINOv2 i CLIP
  (`score.py`), raport HTML (`report.py`), instrukcja na serwer GPU zgodna z jego zasadami (README w tym katalogu).
- Testy logiki bez GPU: `tests/test_image_bench.py` (model na niby).
- Uwaga dla następnych: adaptery FLUX nie były jeszcze uruchomione na GPU. Nazwy parametrów, repozytorium wersji
  destylowanej FLUX 3 i API `ModularPipeline` sprawdzić na krótkim teście (README, krok 8).

### 2026-11-03, Krzysiek: pomiar KV cache (Z3) i wstępne badanie `full_cached` (Z4b)
- Co zrobione: odpowiedź narratora strumieniem (`NARRATOR_STREAM`, domyślnie włączone), w `turns` nowe kolumny
  `ttft_ms` (koniec czytania promptu) i `first_answer_ms` (koniec myślenia), migracja starych baz. Skrypt
  `app/eval/kv_cache.py`: 4 scenariusze z noty prowadzącego na promptach z prawdziwej gry, wznawianie, CSV.
  Baza czeka na zapis do 30 s (było 5 s: 8 równoległych gier dawało `database is locked`).
- Pliki: `app/llm/`, `app/core/engine.py`, `schemas.py`, `app/storage/db.py`, `app/config.py`, `app/eval/kv_cache.py`,
  `tests/test_kv_cache.py`, `tests/test_llm.py`, README (sekcja „Eksperymenty”, punkt 5).
- **Z3, TTFT w ms** (mediana z 3 powtórzeń, tag `kv1`, prompty z gry strata-big w układzie `full_cached`, bez wymuszonego JSON):

  | model | prompt | bez cache | powtórka | przyspieszenie | dopisana tura | zmieniony początek |
  |---|---|---|---|---|---|---|
  | strata-big | 2k | 2 270 | 120 | 19x | 745 | 2 246 |
  | strata-big | 4k | 2 359 | 120 | 20x | 882 | 2 392 |
  | strata-big | 8k | 3 410 | 105 | 32x | 868 | 3 410 |
  | strata-big | 11k | 5 033 | 118 | 43x | 838 | 5 033 |
  | large-reasoning | 2k | 2 276 | 841 | 2,7x | 1 129 | 2 243 |
  | large-reasoning | 4k | 5 520 | 922 | 6,0x | 1 182 | 5 503 |
  | large-reasoning | 8k | 7 440 | 1 092 | 6,8x | 1 250 | 7 431 |
  | large-reasoning | 11k | 8 764 | 975 | 9,0x | 1 272 | 8 772 |

  Cache działa na obu modelach (wniosek z 2026-10-29 „large-reasoning nie ma cache” jest nieaktualny). Dopisanie tury
  (`full_cached`) trzyma TTFT ok. 0,8 s / 1,2 s niezależnie od długości. Zmiana początku = brak cache. Serwer czyta prompt
  dużo szybciej niż 2026-10-29 (11k tokenów: 5 s, wtedy 6k: 29 s), więc cache oszczędza 4 do 7,5 s na turze, nie więcej.
- **Z4b wstępnie** (tag `z4b`, `main_v2` 28 tur, seedy 1001 i 1002, po 2 gry na wariant, 4 gry modelu naraz):

  | model | pamięć | czas tury med / p95 | czas gry | prompt w turze 28 | TTFT med | myślenie med | JSON 1. raz | M1 | M2 | M4 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | strata-big | full_cached | 27 / 82 s | 17 min | 19k | (całość) | ? | 100% | 9/10 | 6/6 | 16/16 |
  | strata-big | window/8 | 23 / 87 s | 15 min | 5k | (całość) | ? | 100% | 8/10 | 6/6 | 16/16 |
  | large-reasoning | full_cached | 35 / 98 s | 22 min | 20k | 1,2 s | 16,9 s | 89% | 10/10 | 6/6 | 16/16 |
  | large-reasoning | window/8 | 46 / 121 s | 25 min | 7k | 2,2 s | 18,4 s | 61% | 5/10 | 6/6 | 16/16 |

  - strata-big w tym badaniu NIE trafiał w cache (0 tokenów z cache we wszystkich turach), więc to porównanie
    „długi prompt bez cache vs krótki”. Test wyjaśniający (`z4b-solo`, `z4b-pair`, po 8 tur): 1 gra sama trafia
    w cache prawie co turę, przy 2 grach naraz trafia tylko jedna. Równoległe gry nadpisują sobie sesje cache.
  - large-reasoning: cache działa w grze (TTFT 1,2 s przy promptach do 20k). Myślenie to ok. połowa tury (17 s),
    czytanie promptu 3 do 6%. Pełna historia daje lepsze M1 (10/10 vs 5/10, fakty sprzed > 8 tur są w prompcie).
  - 2 gry na wariant: czasy i M1 to pierwszy sygnał, nie wynik. Czas tury mocno zależy od obciążenia serwera.
- Uwaga dla następnych: gry `full_cached` na strata-big tylko po kolei. Dłuższe badanie Z4b: strata-big sekwencyjnie
  (ok. 5 do 10 min na grę, gdy cache trafia), large-reasoning może iść równolegle. Pytanie o myślenie (Z4a) odpada:
  zespół nie zmienia parametrów modeli.
- Jak sprawdzić: `python -m app.eval.kv_cache --summary data/eval/kv_cache.csv --tag kv1`, `python -m app.eval.report --tag z4b`.
- Commit: a558571

### 2026-11-03, Antek: nota prowadzącego o modelach i nowe zadania
- Prowadzący włączył KV cache na `strata-big` i przysłał notę o modelach i cache. Streszczenie: sekcja
  „Wnioski z noty prowadzącego o modelach”.
- Wyjaśnia nasze pomiary: `strata-big` ma sesje cache w 32 slotach wspólnych dla wszystkich (przy ruchu wypadają),
  `large-reasoning` ma cache, ale go nie zgłasza.
- Nowe odkrycie z naszych danych: dużą część tokenów wyjściowych zajmuje ukryte myślenie (Z4a).
- Zadania sprintu 4 rozbite na Z1 do Z5 z opisami, co przygotować.

### 2026-11-03, Antek: zadania sprintu 4 i zasady serwera GPU
- Co zrobione: zadania Z1 do Z4 z opisami, zasady serwera GPU (bez adresu). Prowadzący dodał klucze Antka i Krzyśka.
- Poprawka: „model hybrydowy” jako przyczyna działania cache na `strata-big` to był domysł, wpis z 2026-10-30 poprawiony.
- Uwaga dla następnych: najpierw Z1. Połączenia z serwerem GPU jeszcze nie sprawdzaliśmy.

### 2026-10-30, Antek: zadania sprintu 3 z DoD prowadzącego
- Co zrobione: nowa lista zadań (S1 do S5 z DoD, P1 do P4 z poprzednich sprintów) z opisami
  i sekcja „Otwarte problemy i pytania”.
- DoD prowadzącego: SOTA, research lokalnych modeli graficznych (proof-of-concept) i językowych
  (gemma-4-26b-A4B-it), scenariusz wygenerowany na początku vs halucynowany on-the-fly (proof-of-concept),
  metryki automatycznej oceny jakości rozgrywki.
- Uwaga dla następnych: prowadzący może udostępnić maszynę z RTX 4090, ale jest niestabilna (tylko testy).

### 2026-10-30, Antek: przyczyna problemu z cache i poprawka `full_cached`
- Diagnoza (nagłówki serwera pokazują, która maszyna odpowiada; obie mają po 1 kopii modelu):
  - `strata-big` (Qwen3.8-Flash-Next) w pomiarach zachowuje się tak, jakby zapisywał cache tylko na KOŃCU
    całego promptu (przyczyna nieznana, konfigurację sprawdza prowadzący). Trafienie jest wtedy, gdy nowy prompt to poprzedni prompt plus dopisane wiadomości.
    Sam wspólny początek z innym końcem daje 0 (test: 3 końcówki po 5,2k wspólnych tokenów, 0 trafień;
    dopisanie do poprzedniego promptu: 5201 z 5232 z cache, 28 s → 0,5 s).
  - `large-reasoning`: cache wyłączony albo niezgłaszany (brak `cached_tokens`, identyczny czas przy powtórce).
- Dlaczego test `cache15` dał 0: w `full_cached` historia zapisywała samą akcję gracza, a wysłana wiadomość
  zawierała też stan świata, więc kolejny prompt nie był dopisaniem do poprzedniego.
- Poprawka: przy `full_cached` pamięć zapisuje wiadomość gracza dokładnie tak, jak była wysłana
  (razem ze stanem z tamtej tury). Prompt rośnie szybciej, ale prawie cały idzie z cache. Test silnika sprawdza,
  że kolejny prompt zaczyna się całym poprzednim.
- Test `cache_fix` (strata-big, 8 tur, sama jedna gra): z cache od 2. tury 85 do 99% promptu,
  mediana tury 2 do 8: 17 s (w `long50` przy `window/8`: 41 s). Dwie tury po 35 i 42 s mimo cache
  (prawdopodobnie obciążenie serwera). 1 gra, do potwierdzenia pełnym badaniem.
- Przy okazji: nagłówek `x-litellm-key-spend` podaje wydatki klucza: 1,59 $ ze 100 $ (2026-10-30).

### 2026-10-29, Antek: test `full_cached` w prawdziwej grze (cache nie działa między turami)
- Co zrobione: strategia pamięci `full_cached` (`--history full_cached`): stały prompt systemowy, pełna historia
  tylko dopisywana, lokacja, stan i akcja gracza na końcu. Nowa kolumna `turns.tokens_cached` (ile tokenów serwer
  wziął z cache, stare bazy dostają ją same) i test stałości prefiksu.
- Pliki: `app/core/context.py`, `memory.py`, `engine.py`, `schemas.py`, `app/llm/`, `app/storage/db.py`,
  `app/eval/run.py`, `app/main.py`, `tests/test_core.py`.
- Test `cache15`: strata-big, `main_v2`, 14 tur, seed 1001, obie gry równolegle:

  | wariant | tokeny z cache | mediana tury | gra 14 tur | tokeny wej. | M1 |
  |---|---|---|---|---|---|
  | window/8 | 0 | 79 s | 23 min | 41k | 1/2 |
  | full_cached | **0 w 14 turach** | 79 s | 22 min | 50k | 2/2 |

- Wyjaśnienie: serwer bierze z cache tylko prompt powtórzony W CAŁOŚCI (wtedy pełna tura 9 do 13 s zamiast 40 s).
  Prompt tury 13 wysłany zaraz po prompcie tury 12 (wspólne 23 z 24 wiadomości) dał 0 tokenów z cache,
  z wymuszonym JSON i bez. Wcześniejszy szacunek „tura o 30% krótsza” był błędny (pomiar na powtórzonym prompcie).
- Uwaga dla następnych: bez zmiany po stronie serwera `full_cached` nie przyspiesza, a zużywa więcej tokenów.
  Pytanie do prowadzącego: czy vLLM ma `--enable-prefix-caching` i czy za `strata-big` stoi kilka kopii modelu.
  Czasy tury w teście są ok. 2 razy dłuższe niż w `long50`, bo obie gry szły równolegle.

### 2026-10-29, Antek: okno kontekstu i cache promptu na serwerze prowadzącego
- Co zrobione: sprawdzone limity modeli (`/v1/model/info`) i pomiar cache promptu, bez zmian w kodzie.
- Limity: `strata-big` (Qwen3.8-Flash-Next) 164k tokenów wejścia, `large-reasoning` (Qwen3.8-27B-FP8) 131k,
  oba maks. 8k na odpowiedź. Nasza tura to ok. 4k tokenów, cała gra z pełną historią ok. 20 do 30k.
- Pomiar (czas „przeczytania” promptu, odpowiedź 1 token, po 3 powtórzenia):

  | model | prompt | bez cache | z cache |
  |---|---|---|---|
  | strata-big | 6k | 29 s | 0,3 s (cached_tokens 5943) |
  | strata-big | 30k | 109 s | 0,3 s |
  | large-reasoning | 6k | 6,2 s | 6,2 s (serwer nie zgłasza cache) |

  `strata-big` czyta prompt wolno (ok. 200 tokenów/s), a pisze ok. 40 tokenów/s.
- Wniosek: przy `strata-big` ok. 18 z 41 s tury to czytanie promptu, które cache może prawie usunąć.
  Szacunek: tura ok. 30% krócej. NIEPOTWIERDZONE na prawdziwej grze (cache może wypaść przy obciążeniu serwera).
  Przy `large-reasoning` zysku nie ma, a pełna historia wydłuży czytanie promptu.
- Uwaga dla następnych: zadanie `full_cached` w „Zadaniach w toku”. Ryzyko: pełna historia BEZ trafienia
  w cache na `strata-big` to ok. 100 s na turę pod koniec gry.

### 2026-10-28, Dudsztor: badanie long50 (3 modele × 50 gier) i metryki X1 do X5
- Co zrobione: `app/eval/extra_metrics.py` (X1 do X5, testy pary ze stanem/bez stanu) z testami,
  pełne badanie `main_v2` tag `long50`: strata-big, large-reasoning, llama3.1:8b po 25 + 25 gier (4200 tur).
  Gemini zatrzymany po 2 turach: darmowy klucz ma limit 20 zapytań dziennie.
- Pliki: `app/eval/extra_metrics.py`, `tests/test_extra_metrics.py`, README. Dane tylko lokalnie u Dudsztora
  (`data/dvn.sqlite`, `data/eval/long50*.csv`).
- Ustawienia: pamięć `window/8`, temp 0.7, seedy 1001 do 1025. W wariancie bez stanu stan jest nadal liczony
  i zapisywany (`state_after`), tylko nie trafia do promptu (razem z listą lokacji).

**Tabela 1. Metryki podstawowe** (gry ukończone/25; % z przedziałem Wilsona 95%; czas tury bez 1. tury)

| model | wariant | gry | M1 | M2 (bez gasl.) | M4 | JSON 1. raz | ponow./turę | czas med / p95 | 1. tura med | tury z błędem |
|---|---|---|---|---|---|---|---|---|---|---|
| strata-big | ze stanem | 25 | 80% (100/125; 72 do 86) | 100% (75/75) | 100% (200/200) | 100% | 0,00 | 41 / 79 s | 42 s | 0 |
| strata-big | bez stanu | 25 | 53% (66/125; 44 do 61) | 52% (39/75) | 24% (47/200) | 100% | 0,00 | 44 / 66 s | 40 s | 0 |
| large-reasoning | ze stanem | 25 | 75% (89/118; 67 do 82) | 100% (75/75) | 100% (200/200) | 69% | 0,38 | 35 / 154 s | 59 s | 11 |
| large-reasoning | bez stanu | 25 | 60% (70/116; 51 do 69) | 36% (25/70) | 38% (76/198) | 71% | 0,37 | 33 / 152 s | 42 s | 26 |
| llama3.1:8b | ze stanem | 25 | 31% (39/125; 24 do 40) | 89% (67/75) | 95% (190/200) | 100% | 0,00 | 11 / 19 s | 9 s | 0 |
| llama3.1:8b | bez stanu | 25 | 30% (37/125; 22 do 38) | 33% (25/75) | 44% (88/200) | 100% | 0,00 | 11 / 18 s | 9 s | 0 |
| gemini-3.6-flash | oba | 0 | limit klucza | | | | | | | |

M3 i gaslighting w M2: brak sędziego (nie liczone). M1 w oknie pamięci (k ≤ 8) i poza nim (k > 8):
strata 96% / 69% ze stanem, 90% / 28% bez; large-reasoning 98% / 59% i 96% / 33%; llama 60% / 12% i 70% / 3%.

**Tabela 2. Metryki dodatkowe** (średnia ± odchylenie między grami; W = zapis faktu w stanie, R = pamięta)

| model | wariant | X1 W | X1 W+R / W+nieR / nieW+R / nieW+nieR | X2 ta sama / różne / różnica | X3 nowe nazwy/grę, % tur | X3 mówiący spoza obecnych | X4 trigramy t/t-1, distinct-2 | X5 tok./turę | tokeny wej./wyj. na grę (med.) | czas gry (med.) | fakty na końcu | odrzucone/grę |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| strata-big | ze stanem | 69% (52/75) | 79 / 5 / 21 / 20 | 0,24 / 0,03 / 0,21 ± 0,07 | 1,28 ± 1,24; 4% | 6% (28/509) | 0,003; 0,904 | 99 ± 8 | 102k / 15k | 19 min | 11,5 ± 1,7 | 0 |
| strata-big | bez stanu | 71% (53/75) | 47 / 50 / 19 / 9 | 0,50 / 0,04 / 0,46 ± 0,27 | 1,92 ± 1,75; 6% | 5% (27/551) | 0,003; 0,896 | 116 ± 17 | 105k / 17k | 20 min | 33,4 ± 9,5 | 0 |
| large-reasoning | ze stanem | 37% (28/75) | 44 / 0 / 45 / 29 | 0,17 / 0,03 / 0,14 ± 0,08 | 0,08 ± 0,28; 0,3% | 1% (3/334) | 0,005; 0,888 | 77 ± 33 | 94k / 24k | 22 min | 9,0 ± 1,0 | 0 |
| large-reasoning | bez stanu | 36% (27/75) | 25 / 22 / 45 / 24 | 0,68 / 0,03 / 0,65 ± 0,31 | 0,16 ± 0,47; 0,4% | 0% (0/320) | 0,004; 0,894 | 71 ± 41 | 89k / 24k | 23 min | 11,1 ± 2,5 | 0 |
| llama3.1:8b | ze stanem | 36% (27/75) | 18 / 31 / 21 / 55 | 0,29 / 0,05 / 0,24 ± 0,12 | 0,68 ± 1,18; 2% | 4% (1/25) | 0,028; 0,821 | 48 ± 16 | 65k / 5k | 5 min | 10,0 ± 0,9 | 0,04 |
| llama3.1:8b | bez stanu | 33% (25/75) | 19 / 30 / 18 / 58 | 0,82 / 0,04 / 0,78 ± 0,20 | 0,60 ± 0,96; 2% | 11% (4/37) | 0,019; 0,857 | 46 ± 8 | 61k / 5k | 5 min | 13,8 ± 2,2 | 0,04 |

X1 zapis szukany w turze podania faktu i w następnej (zapis z opóźnieniem: 0 przypadków). X2 to Jaccard słów,
przybliżenie leksykalne. Najczęstsze 4-gramy we wszystkich modelach: „patrzy na ciebie z”, „spojrzał na ciebie z”
(llama 93 tury na 700), u strata-big „zielony kruk zielony kruk”, u large-reasoning „w powietrzu unosi się zapach”.

**Tabela 3. Wpływ stanu świata** (ze stanem minus bez stanu, 25 par z tym samym seedem; McNemar dokładny
dla tak/nie, bootstrap 10 000 losowań dla liczb)

| model | M1 | M2 | M4 | X1 W | X3 nazwy/grę | X4 distinct-2 | tokeny wej./grę |
|---|---|---|---|---|---|---|---|
| strata-big | +27 pp (p < 0,001) | +48 pp (p < 0,001) | +76 pp (p < 0,001) | -1 pp (p = 1,0) | -0,64 (p = 0,22) | +0,008 (p = 0,03) | -2841 (p = 0,05) |
| large-reasoning | +17 pp (p < 0,001) | +64 pp (p < 0,001) | +62 pp (p < 0,001) | +1 pp (p = 1,0) | -0,08 (p = 0,63) | -0,006 (p = 0,21) | +6356 (p = 0,01) |
| llama3.1:8b | +2 pp (p = 0,86) | +56 pp (p < 0,001) | +51 pp (p < 0,001) | +3 pp (p = 0,87) | +0,08 (p = 0,85) | -0,037 (p = 0,01) | +5068 (p < 0,001) |

- Wnioski:
  - Zapis w stanie tłumaczy M1 poza oknem pamięci (k > 8), ale tylko gdy stan jest w prompcie. Ze stanem:
    zapisany fakt strata-big pamięta w 49 z 52 przypadków, niezapisany w 3 z 23; large-reasoning 28/28 vs 12/40.
    Bez stanu zapis nie pomaga (strata 8/53). Potwierdza to wcześniejszy wniosek zespołu.
  - To, czy model zapisuje fakt, nie zależy od tego, czy widzi stan (X1 W prawie równe w obu wariantach,
    p ≈ 1). strata-big zapisuje 70% faktów, large-reasoning i llama ok. 35%.
  - Stan świata to najsilniejszy czynnik w badaniu: M2 rośnie o 48 do 64 pp (bez stanu modele nie znają
    faktów niezmiennych, np. srebrnego miecza), M4 o 51 do 76 pp (głównie przez brak listy lokacji).
    llama nie korzysta ze stanu przy M1 (+2 pp, p = 0,86).
  - Najwięcej nowych nazw własnych zmyśla strata-big (1,3 do 1,9 na grę: Kapitan Kael, ulica Rzeźnicka,
    konie „Gbur”, „Siwy”), large-reasoning prawie wcale (0,1). llama najczęściej się powtarza (najniższe distinct-2).
  - Stan wydłuża prompt umiarkowanie (+5 do 6k tokenów na grę, ok. 6%). U strata-big bez stanu gra jest nawet
    dłuższa, bo model pisze dłuższe odpowiedzi i dopisuje do stanu duplikaty (33 fakty na końcu zamiast 11).
- Problemy:
  - VPN zerwał się 3 razy (ok. 7 h w nocy, ok. 4 h i ok. 40 min w dzień). Runner wznowił gry bez utraty danych.
  - Gemini: limit darmowego klucza (429 RESOURCE_EXHAUSTED, 20 zapytań dziennie). Do badania potrzebny płatny klucz.
  - large-reasoning: 37 tur bez poprawnego JSON (nieocenione próbki M1 i M2), p95 czasu tury ok. 150 s.
  - `--no-state` ukrywa też listę lokacji, więc M4 bez stanu mierzy głównie brak listy id. M2 „próba zmiany”
    opiera się tylko na walidatorze stanu, więc daje 100% wszędzie i niewiele mówi.
  - X3 heurystyka: ręczny przegląd 20 losowych trafień, 11 to prawdziwe nowe byty (precyzja 55%), reszta to
    zaimki („Tobą”), wykrzykniki („Jezus Maria”), „Europie”. X2 bez stanu liczone na mniejszej liczbie par
    (model rzadko powtarza id lokacji), a gdy powtarza, często kopiuje opis z historii, więc podobieństwo jest wyższe.
- Jak sprawdzić: `python -m app.eval.report --tag long50`, `python -m app.eval.extra_metrics --tag long50 --names 20`.
- Commity: f7f12d6, 95da569, 1889574

### 2026-10-23, Antek: wspólny plik postępu
- Co zrobione: ten plik (`PROGRESS.md`) i `AGENTS.md` dla agentów innych niż Claude Code.
- Uwaga dla następnych: czytaj ten plik na starcie, aktualizuj przed pushem.

### 2026-10-21, Antek: pierwsze testy obu modeli przez API
- Co zrobione: scenariusz `main_v2` (poprawione 3 niejasne akcje z `main_v1`: t19, t21, t23),
  dłuższe czekanie runnera przy zerwanym VPN (ok. 14 min), poprawka kontrolki klucza API w UI.
- Wyniki (po 1 rozgrywce, tag `smoke2`):

  | | strata-big | large-reasoning |
  |---|---|---|
  | M1 pamięć | 5/5 | 3/5 (oblane k = 18 i 19) |
  | M2 bez gaslightingu | 3/3 | 3/3 |
  | M4 lokacje | 8/8 | 8/8 |
  | JSON za 1. razem | 100% | 93% |
  | czas tury | 40 s | 87 s |

- Wniosek: model pamięta to, co zapisze w stanie świata. `strata-big` zapisał imię konia i hasło,
  `large-reasoning` nie i po 8 turach zmyślał („Jaki koń? Nie masz konia”). Gaslighting oba odparły (ocena ręczna).
- Jak sprawdzić: `docker compose exec app python -m app.eval.report --tag smoke2 --details`
  (dane są tylko w lokalnej bazie Antka, `data/` nie jest w repo).
- Commity: 1f91475, 52410be

### 2026-10-21, Antek: runner, metryki i scenariusze
- Co zrobione: format scenariuszy YAML z walidatorem (`app/eval/scenario.py`, `check.py`),
  scenariusz `main_v1`, runner ze wznawianiem (`run.py`), metryki M1/M2/M4 (`metrics.py`), raport (`report.py`).
- Test `main_v1` na `large-reasoning` (tag `smoke`): M1 3/5, M2 3/3, M4 8/8. Wyszły niejasne akcje w scenariuszu.
- Commity: e06b6f3, fe56bf5, aaef452

### Wcześniej: szkielet projektu
- Kontener Docker, FastAPI z UI, silnik tury, stan świata, LiteLLM, zapis do SQLite, połączenie z serwerem prowadzącego.
