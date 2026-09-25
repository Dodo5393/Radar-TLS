# Radar-TLS

Znajduje i kwalifikuje potencjalnych klientów na podstawie opisu kontekstu.

## Uruchomienie

    pip install -r requirements.txt
    python -m radar.profil zlecenia/<nazwa> --model anthropic:claude-opus-5   # raz, potem ręczna korekta profil.yaml
    python -m radar.agent zlecenia/<nazwa>                                    # odkrywanie -> kandydaci.csv, log.jsonl

Zmienne środowiskowe:

- `RADAR_KONTAKT` — e-mail do User-Agent (wymagane przy pobieraniu stron)
- `GOOGLE_PLACES_API_KEY` — Places API (New)
- `ANTHROPIC_API_KEY` — dla modeli `anthropic:*`

Modele `hermes:*` idą przez lokalne proxy Nous Portal, bez klucza: `hermes proxy start`.
Model na etap: `modele` w `profil.yaml`.

Testy: `python tests/test_typy.py`, `python tests/test_agent.py`.
