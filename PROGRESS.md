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
  każda tura w `data/dvn.sqlite` (z `tokens_cached`).
- Scenariusze badawcze (`app/eval/scenarios/`, aktualny `main_v2`), runner ze wznawianiem po zerwaniu VPN,
  metryki M1, M2 (bez gaslightingu), M4 i raport w terminalu. Opis komend: README, sekcja „Eksperymenty”.
- Metryki dodatkowe X1 do X5 i porównanie „ze stanem minus bez stanu” na parach seedów (McNemar, bootstrap,
  przedziały Wilsona): `python -m app.eval.extra_metrics --tag <tag> [--csv plik] [--names 20]`.
- Pełne badanie `long50` (3 modele × 25 gier ze stanem + 25 bez), wyniki w Dzienniku 2026-10-28.

**Nie ma jeszcze:**
- Sędzia LLM (M3 dziwne komendy, gaslighting w M2).
- Wyniki Gemini (darmowy klucz: 20 zapytań dziennie, za mało na badanie).
- Wykresy i raport dla prowadzącego.
- Generowanie obrazów teł (pytanie badawcze 3), zadanie S2.

**Znane problemy:**
- VPN rozłącza się przy wygaszaczu ekranu i bez powodu (macOS i Windows). Na macOS `caffeinate -di` (README),
  na Windows wyłącz usypianie i wygaszacz. Runner i tak wznawia po powrocie VPN.
- `large-reasoning` jest wolny (mediana 34 s, p95 150 s na turę) i w 2,6% tur nie daje poprawnego JSON.
- `--no-state` ukrywa w prompcie także listę lokacji, nie tylko stan. Spadek M4 bez stanu wynika głównie z tego (zadanie P3).

## Metryki sprintu (ustalone)

| Metryka | Co mierzy | Jak oceniane |
|---|---|---|
| M1 pamięć faktów | czy model pamięta fakt podany przez gracza po k turach | szukanie słowa z `accept` w odpowiedzi |
| M2 fakty niezmienne | czy da się zmienić fakt niezmienny (pytanie, próba zmiany, gaslighting) | słowa i walidator, gaslighting: sędzia LLM |
| M3 dziwne komendy | czy reakcja na absurd jest logiczna i w roli | sędzia LLM według kryterium z YAML |
| M4 spójność lokacji | czy location_id zgadza się z oczekiwanym i między wizytami | porównanie z YAML |

## Zadania w toku

Wpisz się w kolumnę „Kto”, zanim zaczniesz (osobny mały commit i push). Opisy zadań są niżej.

**Sprint 3 (od 2026-10-30), wymagania prowadzącego (DoD):**

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

### Otwarte problemy i pytania

- Cache na `large-reasoning` jest wyłączony albo niezgłaszany. Pytanie do prowadzącego, czy da się włączyć.
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

## Dziennik

### 2026-10-30, Antek: zadania sprintu 3 z DoD prowadzącego
- Co zrobione: nowa lista zadań (S1 do S5 z DoD, P1 do P4 z poprzednich sprintów) z opisami
  i sekcja „Otwarte problemy i pytania”.
- DoD prowadzącego: SOTA, research lokalnych modeli graficznych (proof-of-concept) i językowych
  (gemma-4-26b-A4B-it), scenariusz wygenerowany na początku vs halucynowany on-the-fly (proof-of-concept),
  metryki automatycznej oceny jakości rozgrywki.
- Uwaga dla następnych: prowadzący może udostępnić maszynę z RTX 4090, ale jest niestabilna (tylko testy).

### 2026-10-30, Antek: przyczyna problemu z cache i poprawka `full_cached`
- Diagnoza (nagłówki serwera pokazują, która maszyna odpowiada; obie mają po 1 kopii modelu):
  - `strata-big` (Qwen3.8-Flash-Next, model hybrydowy z warstwami liniowymi) zapisuje cache tylko na KOŃCU
    całego promptu. Trafienie jest wtedy, gdy nowy prompt to poprzedni prompt plus dopisane wiadomości.
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
