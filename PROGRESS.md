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
- Stan świata z faktami niezmiennymi i walidatorem, pamięć `full` i `window`, każda tura w `data/dvn.sqlite`.
- Scenariusze badawcze (`app/eval/scenarios/`, aktualny `main_v2`), runner ze wznawianiem po zerwaniu VPN,
  metryki M1, M2 (bez gaslightingu), M4 i raport w terminalu. Opis komend: README, sekcja „Eksperymenty”.

**Nie ma jeszcze:**
- Sędzia LLM (M3 dziwne komendy, gaslighting w M2).
- Pełne badanie (2 modele × ze stanem i bez × 3 powtórzenia).
- Wykresy i raport dla prowadzącego.
- Generowanie obrazów teł (pytanie badawcze 3).

**Znane problemy:**
- VPN rozłącza się przy wygaszaczu ekranu. Długie badania uruchamiaj z `caffeinate -di` (README).
- `large-reasoning` jest wolny (średnio 87 s na turę, czasem 300 s).

## Metryki sprintu (ustalone)

| Metryka | Co mierzy | Jak oceniane |
|---|---|---|
| M1 pamięć faktów | czy model pamięta fakt podany przez gracza po k turach | szukanie słowa z `accept` w odpowiedzi |
| M2 fakty niezmienne | czy da się zmienić fakt niezmienny (pytanie, próba zmiany, gaslighting) | słowa i walidator, gaslighting: sędzia LLM |
| M3 dziwne komendy | czy reakcja na absurd jest logiczna i w roli | sędzia LLM według kryterium z YAML |
| M4 spójność lokacji | czy location_id zgadza się z oczekiwanym i między wizytami | porównanie z YAML |

## Zadania w toku

| Kto | Zadanie | Od kiedy |
|---|---|---|
| Dudsztor | Badanie 4 modeli, 25 gier ze stanem + 25 bez, tag `long50`, metryki X1 do X5 | 2026-10-26 |
| (wolne) | Sędzia LLM dla M3 i gaslightingu | |
| (wolne) | Pełne badanie na noc (tag `sprint1`) | |
| (wolne) | Pipeline obrazów (ImageProvider, cache po location_id) | |

## Decyzje

- **Jeden kontener i Python** (bez Node). Łatwiej uruchomić na trzech systemach.
- **Scenariusz pisany pod badanie**, nie badanie pod przypadkową rozgrywkę. Każdy model dostaje te same ruchy,
  temperatura 0.7, seed = 1000 + numer powtórzenia.
- **Wersje scenariuszy się nie mieszają.** Zmiana treści scenariusza = nowy plik albo wyższe `version`.
  `main_v1` zostaje dla porównania, aktualny jest `main_v2`.
- **M1 bez sędziego**, bo szukanie słowa jest pewne i darmowe. Sędzia tylko tam, gdzie słowa nie wystarczą.
- **Sędzia krzyżowo:** każdy model ocenia odpowiedzi drugiego, temperatura 0, ręczna weryfikacja ok. 20 ocen.

## Dziennik

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
