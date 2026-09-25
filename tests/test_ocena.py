"""python tests/test_ocena.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.narzedzia.ocena import ocen
from radar.profil import wczytaj_profil
from radar.typy import Dowod, Fakt, Fakty


def f(wartosc, dowod=True):
    return Fakt(wartosc=wartosc, dowod=Dowod(cytat="c", url="https://x.pl") if dowod else None)


def r(fakt, warunek, punkty, wartosc=None):
    return {"fakt": fakt, "warunek": warunek, "wartosc": wartosc, "punkty": punkty, "uzasadnienie": "u"}


REGULY = {
    "tak": r("a", "prawda", 10), "nie": r("a", "falsz", -5),
    "jest": r("b", "wypelniony", 3), "duzo": r("c", ">=", 7, 100), "malo": r("c", "<=", -9, 10),
    "tekst": r("d", "zawiera", 2, "CMR"), "lista": r("e", "zawiera", 4, "symfonia"),
    "bez_dowodu": r("g", "prawda", 50), "brak_faktu": r("h", "wypelniony", 50),
}
fakty = Fakty(firma="X", pola={
    "a": f(True), "b": f("faktury@x.pl"), "c": f(120), "d": f("fakturę wraz z cmr prosimy"),
    "e": f(["Comarch", "Symfonia ERP"]), "g": f(True, dowod=False),
})
o = ocen(fakty, REGULY)
assert {t.regula for t in o.trafienia} == {"tak", "jest", "duzo", "tekst", "lista"}, o.trafienia
assert o.suma == 10 + 3 + 7 + 2 + 4
assert all(t.dowod for t in o.trafienia)

# "falsz" tylko przy jawnym "nie"; bool nie jest liczbą; pusta wartość nie jest "wypelniony"
o = ocen(Fakty(firma="Y", pola={"a": f(False), "b": f(""), "c": f(True)}), REGULY)
assert [t.regula for t in o.trafienia] == ["nie"] and o.suma == -5

# reguły z prawdziwego profilu
profil = wczytaj_profil(Path(__file__).resolve().parents[1] / "zlecenia/spedycja-trojmiasto")
o = ocen(Fakty(firma="Z", pola={"instrukcja_dokumentow_dla_przewoznikow": f(True),
                                "liczba_pracownikow": f(12)}), profil.reguly)
assert o.suma == 25 - 100, o

print("ok")
