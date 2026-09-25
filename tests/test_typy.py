"""python tests/test_typy.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from radar.typy import Dowod, Fakt, Profil

# Fakt bez dowodu = brak
assert Fakt(wartosc=120).wartosc is None
assert Fakt(wartosc=120, dowod=Dowod(cytat="120 pracowników", url="https://x.pl")).wartosc == 120

# Reguła musi wskazywać istniejący fakt i mieć wartość dla progów
baza = dict(lokalizacje=[], frazy_miejsca=[], frazy_web=[], pkd=[], modele={},
            schemat={"pracownicy": {"typ": "liczba", "opis": "x"}})
Profil(**baza, reguly={"duza": {"fakt": "pracownicy", "warunek": ">=", "wartosc": 20, "punkty": 10, "uzasadnienie": "x"}})
for zla in ({"fakt": "brak", "warunek": "prawda", "punkty": 1, "uzasadnienie": "x"},
            {"fakt": "pracownicy", "warunek": ">=", "punkty": 1, "uzasadnienie": "x"},
            {"fakt": "pracownicy", "warunek": "prawda", "punkty": 1, "uzasadnienie": "x"},
            {"fakt": "pracownicy", "warunek": "wypelniony", "wartosc": 5, "punkty": 1, "uzasadnienie": "x"}):
    try:
        Profil(**baza, reguly={"r": zla})
    except ValidationError:
        pass
    else:
        raise AssertionError(zla)

print("ok")
