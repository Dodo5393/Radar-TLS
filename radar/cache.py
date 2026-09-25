"""Cache na dysku: jeden plik JSON na klucz, w .cache/<rodzaj>/."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

KATALOG = Path(__file__).resolve().parents[1] / ".cache"


def _sciezka(rodzaj: str, klucz: str) -> Path:
    return KATALOG / rodzaj / (hashlib.sha256(klucz.encode()).hexdigest()[:32] + ".json")


def wczytaj(rodzaj: str, klucz: str, max_wiek_dni: float | None = None):
    p = _sciezka(rodzaj, klucz)
    if not p.exists() or (max_wiek_dni and time.time() - p.stat().st_mtime > max_wiek_dni * 86400):
        return None
    return json.loads(p.read_text(encoding="utf-8"))["dane"]


def zapisz(rodzaj: str, klucz: str, dane) -> None:
    p = _sciezka(rodzaj, klucz)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"klucz": klucz, "dane": dane}, ensure_ascii=False), encoding="utf-8")
