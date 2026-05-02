import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def modelo_xlsx_bytes():
    return (ROOT / "modelo_importacao.xlsx").read_bytes()


@pytest.fixture
def fonts_empty():
    return {"black": "", "bold": "", "reg": "", "light": ""}


@pytest.fixture
def evento_basico():
    return {"nome": "SUN2026", "categoria": "RX MASCULINO", "data": "2026"}


@pytest.fixture
def workout_for_time():
    return {
        "numero": 1,
        "nome": "TWENTIES",
        "tipo": "for_time",
        "modalidade": "individual",
        "time_cap": "9 min",
        "movimentos": [
            {"nome": "CHEST-TO-BAR PULL-UPS", "reps": 20},
            {"nome": "THRUSTERS", "reps": 20, "label": "@ 43kg"},
            {"chegada": True},
        ],
    }


@pytest.fixture
def atletas_desordenados():
    return [
        {"nome": "Carlos", "box": "CF Alfa",  "raia": "10", "bateria": "B", "numero": "003"},
        {"nome": "Ana",    "box": "CF Beta",  "raia": "2",  "bateria": "A", "numero": "001"},
        {"nome": "Bruno",  "box": "CF Gama",  "raia": "1",  "bateria": "B", "numero": "002"},
        {"nome": "Diana",  "box": "CF Delta", "raia": "3",  "bateria": "A", "numero": "004"},
    ]
