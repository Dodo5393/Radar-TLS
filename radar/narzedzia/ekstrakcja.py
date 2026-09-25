"""Ekstrakcja faktów ze stron firmy. Model wskazuje fakt z cytatem, kod sprawdza, że cytat
naprawdę jest na stronie — inaczej fakt nie dostaje dowodu, czyli liczy się jak brak.
"""
from __future__ import annotations

from pydantic import BaseModel, create_model

from radar.llm import json_wg_schematu
from radar.narzedzia.pobieranie import slowa, tekst_i_linki
from radar.typy import Dowod, Fakt, Fakty, PoleSchematu, Strona

LIMIT_ZNAKOW_NA_STRONE = 15_000
TYPY = {"liczba": float, "tak_nie": bool, "tekst": str, "lista": list[str]}

PROMPT = """\
Wyciągasz fakty o firmie z jej strony WWW (poniżej, kilka podstron).

Dla każdego pola zwróć obiekt {{wartosc, cytat, url}} albo null.
- cytat: dosłowny fragment tekstu strony (5–40 słów), skopiowany bez zmian, z którego wynika wartość.
- url: adres podstrony z cytatem (z nagłówka ===).
- null, gdy strona tego wprost nie mówi. Nie zgaduj i nie wnioskuj z ogólnej wiedzy o branży.
- tak_nie = false tylko wtedy, gdy strona wprost mówi „nie”; brak informacji to null.
- liczba: sama liczba („ponad 120 osób” → 120).

POLA:
{pola}

STRONY:
{strony}
"""


def _model_odpowiedzi(schemat: dict[str, PoleSchematu]) -> type[BaseModel]:
    pola = {}
    for nazwa, pole in schemat.items():
        fakt = create_model(f"Fakt_{nazwa}", wartosc=(TYPY[pole.typ], ...), cytat=(str, ...), url=(str, ...))
        pola[nazwa] = (fakt | None, ...)  # wymagane, ale może być null
    return create_model("FaktyZeStrony", **pola)


def _gdzie_cytat(cytat: str, teksty: dict[str, str], url: str) -> str | None:
    igla = slowa(cytat)
    if len(igla) < 3:
        return None
    for u in dict.fromkeys([url, *teksty]):  # najpierw strona wskazana przez model
        if u in teksty and igla in slowa(teksty[u]):
            return u
    return None


def wyciagnij_fakty(strony: list[Strona], schemat: dict, model: str) -> Fakty:
    schemat = {n: PoleSchematu.model_validate(p) for n, p in schemat.items()}
    teksty = {s.url: tekst_i_linki(s)[0][:LIMIT_ZNAKOW_NA_STRONE] for s in strony}
    if not teksty:
        return Fakty()
    prompt = PROMPT.format(
        pola="\n".join(f"- {n} ({p.typ}): {p.opis}" for n, p in schemat.items()),
        strony="\n\n".join(f"=== {u} ===\n{t}" for u, t in teksty.items()),
    )
    odp = json_wg_schematu(model, prompt, _model_odpowiedzi(schemat))
    pola = {}
    for nazwa in schemat:
        if (f := getattr(odp, nazwa)) is None:
            continue
        url = _gdzie_cytat(f.cytat, teksty, f.url)
        # bez potwierdzonego cytatu wartość przepada (typy.Fakt), klucz zostaje: model coś twierdził
        pola[nazwa] = Fakt(wartosc=f.wartosc, dowod=Dowod(cytat=f.cytat, url=url) if url else None)
    return Fakty(strony=list(teksty), pola=pola)
