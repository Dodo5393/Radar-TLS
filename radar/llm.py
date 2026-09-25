"""Wywołania modeli. Model zapisujemy jako "dostawca:model", np.

    anthropic:claude-opus-5
    hermes:upstage/solar-pro4:free     # lokalne proxy Hermesa (`hermes proxy start`), bez klucza API

Dostawcy inni niż anthropic mówią API zgodnym z OpenAI (chat/completions).
"""
from __future__ import annotations

import json
import os
import time
from typing import TypeVar

import anthropic
import httpx
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# nazwa -> (base_url, zmienna z kluczem API lub None)
DOSTAWCY_OPENAI = {
    "hermes": ("http://127.0.0.1:8645/v1", None),  # proxy dokleja poświadczenia Nous Portal
}


def _rozbij(model: str) -> tuple[str, str]:
    dostawca, _, nazwa = model.partition(":")
    if not nazwa or (dostawca != "anthropic" and dostawca not in DOSTAWCY_OPENAI):
        raise ValueError(f"Nieznany model {model!r}; oczekiwano 'dostawca:model', dostawcy: "
                         f"anthropic, {', '.join(DOSTAWCY_OPENAI)}")
    return dostawca, nazwa


def json_wg_schematu(model: str, prompt: str, schemat: type[T]) -> T:
    """Jedno zapytanie, odpowiedź zwalidowana schematem Pydantic."""
    dostawca, nazwa = _rozbij(model)
    if dostawca == "anthropic":
        odp = anthropic.Anthropic().messages.parse(
            model=nazwa,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=[{"role": "user", "content": prompt}],
            output_format=schemat,
        )
        if odp.stop_reason != "end_turn" or odp.parsed_output is None:
            raise RuntimeError(f"{model}: odpowiedź przerwana, stop_reason={odp.stop_reason}")
        return odp.parsed_output

    url, klucz_env = DOSTAWCY_OPENAI[dostawca]
    klucz = os.environ[klucz_env] if klucz_env else "brak"
    for proba in range(4):  # darmowe modele często zwracają 429
        odp = httpx.post(
            f"{url}/chat/completions",
            headers={"Authorization": f"Bearer {klucz}"},
            json={
                "model": nazwa,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schemat.__name__, "schema": schemat.model_json_schema()},
                },
            },
            timeout=600,
        )
        if odp.status_code != 429 or proba == 3:
            break
        time.sleep(float(odp.headers.get("retry-after", 30)))
    odp.raise_for_status()
    wybor = odp.json()["choices"][0]
    if wybor["finish_reason"] != "stop":
        raise RuntimeError(f"{model}: odpowiedź przerwana, finish_reason={wybor['finish_reason']}")
    tresc = wybor["message"]["content"].strip()
    # część modeli owija JSON w ```json ... ``` mimo response_format
    tresc = tresc.removeprefix("```json").removeprefix("```").removesuffix("```")
    return schemat.model_validate(json.loads(tresc))
