"""Modele danych Radaru. Nic branżowego — branża żyje w kontekst.yaml i profil.yaml."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# --- Wejście zlecenia (kontekst.yaml) ---

class Produkt(BaseModel):
    nazwa: str
    opis: str  # co sprzedajemy
    problem: str  # jaki problem to rozwiązuje u klienta


class Kontekst(BaseModel):
    kogo_szukamy: str  # opis prozą
    produkt: Produkt
    obszar: str
    pracownicy_min: int
    pracownicy_max: int
    ile_kandydatow: int = 50


# --- Profil (profil.yaml, generowany raz, korygowany ręcznie) ---

class PoleSchematu(BaseModel):
    typ: Literal["tekst", "liczba", "tak_nie", "lista"]
    opis: str  # co dokładnie wyciągnąć i jak to rozpoznać w tekście


class Regula(BaseModel):
    fakt: str  # klucz z profil.schemat
    warunek: Literal["prawda", "wypelniony", ">=", "<=", "zawiera"]
    wartosc: str | float | None = None  # dla >=, <=, zawiera
    punkty: float  # ujemne = sygnał przeciw
    uzasadnienie: str  # jaki związek z problemem, który rozwiązuje produkt


class Profil(BaseModel):
    lokalizacje: list[str]  # obszar rozbity na miejscowości do Places
    frazy_miejsca: list[str]  # krótkie frazy do Google Places
    frazy_web: list[str]  # zapytania do wyszukiwarki (w tym katalogi, izby, targi)
    pkd: list[str]
    schemat: dict[str, PoleSchematu]
    reguly: dict[str, Regula]
    modele: dict[str, str]  # etap -> model

    @model_validator(mode="after")
    def _reguly_wskazuja_istniejace_fakty(self):
        for id_, r in self.reguly.items():
            if r.fakt not in self.schemat:
                raise ValueError(f"reguła {id_!r} odwołuje się do nieznanego faktu {r.fakt!r}")
            if r.warunek in (">=", "<=", "zawiera") and r.wartosc is None:
                raise ValueError(f"reguła {id_!r}: warunek {r.warunek!r} wymaga wartości")
        return self


# --- Odkrywanie ---

class WynikWyszukiwania(BaseModel):
    tytul: str
    url: str
    opis: str = ""


class Miejsce(BaseModel):
    place_id: str
    nazwa: str
    adres: str = ""
    www: str | None = None
    telefon: str | None = None
    kategorie: list[str] = []


class Katalog(BaseModel):
    url: str  # strona katalogu oglądana przez człowieka
    metoda: Literal["json", "html_tabela", "html_lista"]
    zrodlo: str  # endpoint JSON albo URL listy
    paginacja: str | None = None  # np. "?page={n}", "offset=+50"; None = jedna strona
    mapowanie_pol: dict[str, str]  # pole Firma -> ścieżka/selektor w źródle
    opis: str


class Firma(BaseModel):
    nazwa: str
    www: str | None = None
    adres: str | None = None
    telefon: str | None = None
    nip: str | None = None
    krs: str | None = None
    zrodlo: str  # narzędzie + zapytanie, np. "szukaj_miejsca:spedycja|Gdynia"
    zrodlo_url: str | None = None  # konkretna strona/rekord, z którego pochodzi


# --- Kwalifikacja ---

class Strona(BaseModel):
    url: str
    status: int
    typ: str = ""  # Content-Type
    tresc: str  # surowe body (HTML/JSON)
    pobrano: datetime
    z_cache: bool = False


class DaneRejestrowe(BaseModel):
    nip: str | None = None
    krs: str | None = None
    regon: str | None = None
    nazwa_pelna: str | None = None
    forma_prawna: str | None = None
    pkd: list[str] = []
    data_rejestracji: str | None = None
    adres: str | None = None
    zrodlo: str | None = None


class Dowod(BaseModel):
    cytat: str
    url: str


class Fakt(BaseModel):
    wartosc: str | float | bool | list[str] | None = None
    dowod: Dowod | None = None

    @model_validator(mode="after")
    def _bez_dowodu_brak(self):
        if self.dowod is None:
            self.wartosc = None
        return self


class Fakty(BaseModel):
    firma: str
    pola: dict[str, Fakt] = Field(default_factory=dict)  # klucze z profil.schemat


class TrafienieReguly(BaseModel):
    regula: str
    punkty: float
    dowod: Dowod | None = None


class Ocena(BaseModel):
    suma: float
    trafienia: list[TrafienieReguly] = []
