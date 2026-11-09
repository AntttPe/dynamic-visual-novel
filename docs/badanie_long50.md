# Badanie long50: porównanie narratorów LLM

Notatka opisuje, jak badamy narratorów w Dynamic Visual Novel, co mierzymy i co wyszło w badaniu `long50`
(26 do 28 października 2026). Surowe dane są lokalnie w `data/dvn.sqlite` u osoby, która prowadziła badanie.

## 1. Pytanie badawcze

Sprawdzamy, jak dobrze model językowy prowadzi grę jako narrator:

- czy **pamięta fakty** podane przez gracza wiele tur wcześniej,
- czy **trzyma się stałych cech świata** (np. miecz bohatera jest srebrny),
- czy **konsekwentnie nazywa miejsca** (ta sama lokacja ma ten sam identyfikator),
- czy **zmyśla** nowe postacie i miejsca, **powtarza się** i ile to **kosztuje**.

Główne pytanie tego badania: **ile daje podawanie modelowi stanu świata w prompcie?**

## 2. Jak działa badanie

### Scenariusz

Każdy model dostaje dokładnie te same 28 ruchów gracza ze scenariusza `main_v2`
(`app/eval/scenarios/main_v2.yaml`). Skrypt nie reaguje na odpowiedzi modelu, więc różnice w wynikach to różnice
między modelami, a nie między rozgrywkami. Scenariusz ma trzy części:

| tury | co się dzieje |
|---|---|
| 1 do 14 | gracz podaje fakty (imię konia, hasło, miejsce zakopania liny), pierwsze pytania kontrolne, łagodne dziwne komendy |
| 15 do 23 | powroty do lokacji, pytania o fakty niezmienne, próba zmiany faktu, pytania kontrolne po 9 do 19 turach |
| 24 do 28 | testy niszczące: gaslighting, wyjście z roli, autodestrukcja |

### Dwa warianty

| wariant | co model widzi w prompcie |
|---|---|
| **ze stanem** | instrukcje, opis świata, **stan świata (fakty)**, **listę znanych lokacji**, ostatnie 8 tur, akcję gracza |
| **bez stanu** (`--no-state`) | to samo, ale bez stanu świata i bez listy lokacji |

W obu wariantach model może zapisywać zmiany w stanie (`state_updates`), a silnik zapisuje stan po każdej turze
do bazy. W wariancie bez stanu ten zapis po prostu nie wraca do promptu. Dzięki temu da się sprawdzić, czy model
zapisuje fakty, niezależnie od wariantu.

### Ustawienia (stałe dla wszystkich gier)

| ustawienie | wartość |
|---|---|
| gier na model | 50 (25 ze stanem + 25 bez stanu) |
| seedy | 1001 do 1025, te same w obu wariantach (porównanie parami) |
| temperatura | 0.7 |
| pamięć rozmowy | okno ostatnich 8 tur (`window/8`) |
| ponowienia przy złym JSON | 2 |
| limit czasu na odpowiedź | 180 s |

### Modele

| model | gdzie działa | wynik |
|---|---|---|
| `openai/strata-big` | serwer instytutu (VPN) | 50/50 gier |
| `openai/large-reasoning` | serwer instytutu (VPN) | 50/50 gier |
| `ollama/llama3.1:8b` | Ollama na komputerze | 50/50 gier |
| `gemini/gemini-3.6-flash` | API Google | 0 gier, darmowy klucz ma limit 20 zapytań dziennie |

## 3. Co mierzymy

### Metryki podstawowe (`app/eval/metrics.py`)

| metryka | co mierzy | jak liczona |
|---|---|---|
| **M1** pamięć faktów | czy model pamięta fakt podany przez gracza k tur wcześniej (k = 2, 5, 9, 18, 19) | w odpowiedzi musi paść słowo kluczowe, np. „Kasztan” |
| **M2** fakty niezmienne | czy model zna i chroni stałe cechy świata | pytanie: słowo kluczowe w odpowiedzi; próba zmiany: walidator stanu |
| **M3** dziwne komendy | czy reakcja na absurd jest logiczna i w roli | sędzia LLM, **jeszcze nie ma** |
| **M4** spójność lokacji | czy `location_id` zgadza się z oczekiwanym i jest ten sam przy powrotach | porównanie z YAML |

### Metryki dodatkowe (`app/eval/extra_metrics.py`)

| metryka | co mierzy | jak liczona |
|---|---|---|
| **X1** zapis faktu | czy model zapisał podany fakt w stanie świata | słowo kluczowe w faktach dopisanych w turze podania (lub następnej) |
| X1 rozbicie M1 | czy pamięć wynika z zapisu | tabela 2×2: zapisał/nie zapisał × pamięta/zapomniał |
| **X2** opis lokacji | czy ta sama lokacja jest opisywana podobnie przy kolejnych wizytach | podobieństwo słów (Jaccard) i trigramów znakowych; ta sama lokacja vs różne |
| **X3** zmyślone byty | ile nowych nazw własnych spoza świata i akcji gracza | słowa z wielkiej litery w środku zdania, nieznane wcześniej w grze |
| X3 mówiący | czy postać mówiąca jest na scenie | `speaker` spoza `characters_present` |
| **X4** powtarzalność | czy model kopiuje frazy | trigramy wspólne z poprzednią turą, distinct-2 (różne bigramy / wszystkie) |
| **X5** koszt | jak rośnie prompt i ile kosztuje gra | nachylenie tokenów wejściowych na turę, tokeny i czas na grę, liczba faktów w stanie |

### Statystyka

| rodzaj wyniku | metoda |
|---|---|
| odsetki (M1, M2, M4, X1) | przedział ufności 95% Wilsona |
| porównanie tak/nie ze stanem vs bez | test McNemara (dokładny, z rozkładu dwumianowego), pary z tym samym seedem |
| porównanie liczb (X3, X4, tokeny) | bootstrap par (10 000 losowań, stały seed) i test znaków |
| stabilność modelu | odchylenie standardowe między grami |

## 4. Co bierzemy pod uwagę (żeby wyniki były uczciwe)

- **Te same ruchy i seedy** w obu wariantach. Różnica między wariantami to efekt stanu świata, nie losowości.
- **Okno pamięci 8 tur.** Pytania z k ≤ 8 model może odczytać z historii rozmowy, więc pamięć oceniamy osobno
  dla k ≤ 8 i k > 8.
- **Nieudany JSON** to tura z błędem. Sprawdzenia w takiej turze są „nieocenione”, nie „oblane”.
- **Zerwany VPN i 503** nie psują gry. Runner ponawia zapytania (ok. 14 min), a ta sama komenda wznawia grę
  od ostatniej zapisanej tury. W `long50` VPN zerwał się 3 razy, bez utraty danych.
- **Warianty na przemian** (gra 1 ze stanem, gra 1 bez, gra 2 ze stanem...). Gdyby skończył się limit tokenów,
  zostałyby pełne pary.
- **Heurystyki sprawdzamy ręcznie.** X3 oceniliśmy na 20 losowych trafieniach (precyzja ok. 55%).
- **Nie zgadujemy metryk sędziego.** M3 i gaslighting czekają na sędziego LLM.

## 5. Jak testujemy

| krok | komenda (w kontenerze) | po co |
|---|---|---|
| walidacja scenariusza | `python -m app.eval.check main_v2` | czy fakty, pytania i lokacje w YAML są spójne |
| testy kodu | `pytest -v` | 61 testów, działają bez modelu (tryb demo, model na niby, sztuczne dane metryk) |
| test dymny | `python -m app.eval.run --model <m> --reps 1 --max-turns 3 --tag long50-smoke` | czy model odpowiada, ile trwa tura i ile kosztuje |
| badanie | `python -m app.eval.run --model <m> --reps 25 --tag long50 [--no-state]` | pełne gry, wyniki w `data/dvn.sqlite` |
| metryki podstawowe | `python -m app.eval.report --tag long50 [--csv plik]` | M1, M2, M4, dane techniczne |
| metryki dodatkowe | `python -m app.eval.extra_metrics --tag long50 [--csv plik] [--names 20]` | X1 do X5, porównanie parami, próbka X3 do ręcznej oceny |

Metryki liczą się z zapisanych tur, więc zmiana sposobu liczenia nie wymaga ponownego uruchamiania modeli.

## 6. Wyniki

### Tabela 1. Metryki podstawowe

Odsetki z przedziałem Wilsona 95%. Czas tury bez 1. tury gry.

| model | wariant | M1 pamięć | M2 fakty niezm. | M4 lokacje | JSON 1. raz | czas tury med / p95 | tury z błędem |
|---|---|---|---|---|---|---|---|
| strata-big | ze stanem | **80%** (72 do 86) | **100%** | **100%** | 100% | 41 / 79 s | 0 |
| strata-big | bez stanu | 53% (44 do 61) | 52% | 24% | 100% | 44 / 66 s | 0 |
| large-reasoning | ze stanem | 75% (67 do 82) | **100%** | **100%** | 69% | 35 / 154 s | 11 |
| large-reasoning | bez stanu | 60% (51 do 69) | 36% | 38% | 71% | 33 / 152 s | 26 |
| llama3.1:8b | ze stanem | 31% (24 do 40) | 89% | 95% | 100% | 11 / 19 s | 0 |
| llama3.1:8b | bez stanu | 30% (22 do 38) | 33% | 44% | 100% | 11 / 18 s | 0 |

M3 i gaslighting w M2: brak sędziego.

### Tabela 2. Pamięć w oknie i poza oknem (M1)

| model | ze stanem, k ≤ 8 | ze stanem, k > 8 | bez stanu, k ≤ 8 | bez stanu, k > 8 |
|---|---|---|---|---|
| strata-big | 96% | **69%** | 90% | 28% |
| large-reasoning | 98% | **59%** | 96% | 33% |
| llama3.1:8b | 60% | 12% | 70% | 3% |

W oknie pamięci wszystkie duże modele pamiętają prawie wszystko. Różnicę robi to, co dzieje się poza oknem.

### Tabela 3. Czy pamięć wynika z zapisu w stanie (X1, pytania k > 8)

| model | zapisał i widzi stan | nie zapisał | zapisał, ale nie widzi stanu | zapisuje fakty (X1) |
|---|---|---|---|---|
| strata-big | **94%** (49/52) | 13% (3/23) | 15% (8/53) | 70% |
| large-reasoning | **100%** (28/28) | 30% (12/40) | 22% (6/27) | 36% |
| llama3.1:8b | 19% (5/27) | 9% (4/48) | 4% (1/25) | 35% |

### Tabela 4. Wpływ stanu świata (ze stanem minus bez stanu, 25 par)

| model | M1 | M2 | M4 | X1 zapis | tokeny wej. na grę |
|---|---|---|---|---|---|
| strata-big | **+27 pp** | **+48 pp** | **+76 pp** | -1 pp (n.i.) | -2,8 tys. |
| large-reasoning | **+17 pp** | **+64 pp** | **+62 pp** | +1 pp (n.i.) | +6,4 tys. |
| llama3.1:8b | +2 pp (n.i.) | **+56 pp** | **+51 pp** | +3 pp (n.i.) | +5,1 tys. |

Pogrubione: p < 0,001 (McNemar). n.i.: różnica nieistotna.

### Tabela 5. Metryki dodatkowe (wariant ze stanem, średnia ± odchylenie między grami)

| | strata-big | large-reasoning | llama3.1:8b |
|---|---|---|---|
| X2 podobieństwo: ta sama / różne lokacje | 0,24 / 0,03 | 0,17 / 0,03 | 0,29 / 0,05 |
| X3 zmyślone nazwy na grę | 1,28 ± 1,24 | **0,08 ± 0,28** | 0,68 ± 1,18 |
| X3 mówiący spoza sceny | 6% | **1%** | 4% |
| X4 distinct-2 (więcej = mniej powtórzeń) | **0,90** | 0,89 | 0,82 |
| X5 wzrost promptu na turę | 99 tok. | 77 tok. | 48 tok. |
| tokeny wej. / wyj. na grę (mediana) | 102k / 15k | 94k / 24k | 65k / 5k |
| czas gry (mediana) | 19 min | 22 min | 5 min |
| fakty w stanie na końcu gry | 11,5 | 9,0 | 10,0 |

## 7. Wnioski

1. **Model pamięta to, co zapisze w stanie i widzi w prompcie.** Poza oknem pamięci strata-big pamięta zapisany fakt
   w 94% przypadków, a niezapisany w 13%. Sam zapis bez stanu w prompcie nie pomaga.
2. **Skłonność do zapisywania to cecha modelu,** a nie wariantu. strata-big zapisuje ok. 70% faktów, pozostałe ok. 35%.
3. **Stan świata to najsilniejszy czynnik** dla faktów niezmiennych i lokacji (+48 do +76 pp). Kosztuje mało,
   prompt rośnie o ok. 6%.
4. **strata-big** to najlepszy narrator (pamięć, zawsze poprawny JSON), ale najczęściej zmyśla postacie i miejsca.
   **large-reasoning** prawie nie zmyśla, ale jest wolny i czasem psuje JSON. **llama** jest szybka, lecz słabo
   pamięta, nie korzysta ze stanu przy pamięci faktów i najczęściej się powtarza.

## 8. Ograniczenia i dalsze kroki

| ograniczenie | skutek | co dalej |
|---|---|---|
| `--no-state` ukrywa też listę lokacji | spadek M4 bez stanu to głównie brak listy, nie pamięci | osobna flaga dla listy lokacji |
| brak sędziego LLM | M3 i gaslighting niepoliczone | sędzia krzyżowy, temperatura 0 |
| M2 „próba zmiany” sprawdza tylko walidator | 100% wszędzie, nic nie rozróżnia | ocena narracji przez sędziego |
| X3 to heurystyka | precyzja ok. 55% (zaimki, wykrzykniki) | lepsza lista wyjątków lub NER |
| X2 liczone na słowach | przybliżenie | embeddingi CLIP/tekstowe |
| Gemini bez wyników | brak modelu z API | płatny klucz, ta sama komenda wznowi grę |
| pamięć tylko `window/8` | nie wiemy, jak działa pełna historia lub streszczenie | kolejne strategie pamięci |
