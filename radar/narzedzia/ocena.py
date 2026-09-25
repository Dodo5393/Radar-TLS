"""Punktacja: jawne reguły z profilu na faktach z dowodami. Bez modelu.

Fakt bez dowodu ma wartość None (patrz typy.Fakt) i nie spełnia żadnej reguły —
także "falsz": brak informacji to nie "nie".
"""
from __future__ import annotations

from radar.typy import Fakty, Ocena, Regula, TrafienieReguly


def _liczba(x) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _spelnia(r: Regula, wartosc) -> bool:
    if wartosc is None:
        return False
    match r.warunek:
        case "prawda":
            return wartosc is True
        case "falsz":
            return wartosc is False
        case "wypelniony":
            return wartosc not in ("", [])
        case ">=" | "<=":
            a, b = _liczba(wartosc), _liczba(r.wartosc)
            return a is not None and b is not None and (a >= b if r.warunek == ">=" else a <= b)
        case "zawiera":
            igla = str(r.wartosc).lower()
            elementy = wartosc if isinstance(wartosc, list) else [wartosc]
            return any(igla in str(e).lower() for e in elementy)
    return False


def ocen(fakty: Fakty, reguly: dict) -> Ocena:
    trafienia = []
    for id_, r in reguly.items():
        r = Regula.model_validate(r)
        fakt = fakty.pola.get(r.fakt)
        if fakt and _spelnia(r, fakt.wartosc):
            trafienia.append(TrafienieReguly(regula=id_, punkty=r.punkty, dowod=fakt.dowod))
    return Ocena(suma=sum(t.punkty for t in trafienia), trafienia=trafienia)
