"""Funções puras: ordenação, numeração, parsers de duração e estimativa de rounds."""
from parsers import _atleta_sort_key, assign_workout_numbers, assign_workout_numbers_global
from ai_rounds import _extrair_minutos, _estimar_rounds_algoritmico
from sumula_app import _resolve_logo


def test_resolve_logo_aceita_data_url():
    val = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"
    assert _resolve_logo(val) == val


def test_resolve_logo_rejeita_caminho_de_arquivo():
    """Path traversal: POST com `logo_empresa: '/etc/passwd'` vazava o
    arquivo em base64 no HTML antes do v1.50.1. App público no Render.
    """
    assert _resolve_logo("/etc/passwd") == ""
    assert _resolve_logo(".env") == ""
    assert _resolve_logo("../../secret.txt") == ""
    assert _resolve_logo("logo.png") == ""


def test_resolve_logo_vazio_ou_none():
    assert _resolve_logo("") == ""
    assert _resolve_logo(None) == ""
    assert _resolve_logo(0) == ""


def test_atleta_sort_key_ordena_por_bateria_raia_numerica_nome(atletas_desordenados):
    ordered = sorted(atletas_desordenados, key=_atleta_sort_key)
    assert [a["nome"] for a in ordered] == ["Ana", "Diana", "Bruno", "Carlos"]
    # Ana(A,2) → Diana(A,3) → Bruno(B,1) → Carlos(B,10) — raia 10 vem depois de 2 (numérica)


def test_assign_workout_numbers_express_ocupa_dois_slots():
    workouts = [
        {"nome": "A", "tipo": "for_time"},
        {"nome": "B", "tipo": "express"},
        {"nome": "C", "tipo": "amrap"},
    ]
    assign_workout_numbers(workouts)
    assert workouts[0]["numero"] == 1
    assert workouts[1]["numero"] == 2
    assert workouts[1]["numero_f2"] == 3
    assert workouts[2]["numero"] == 4
    # workouts não-express não devem ter numero_f2
    assert "numero_f2" not in workouts[0]
    assert "numero_f2" not in workouts[2]


def test_assign_workout_numbers_global_continua_por_categoria_atraves_dias():
    """Elite Masc: 3 wkts na Sexta → 4,5 no Sábado → 6 no Domingo (contínuo).
    Rx Masc (categoria diferente) reinicia em 1."""
    dias = [
        {"label": "Sexta", "categorias": [
            {"nome": "Elite Masc", "workouts": [
                {"nome": "W1", "tipo": "for_time"},
                {"nome": "W2", "tipo": "amrap"},
                {"nome": "W3", "tipo": "for_load"},
            ]},
            {"nome": "Rx Masc", "workouts": [
                {"nome": "X1", "tipo": "for_time"},
            ]},
        ]},
        {"label": "Sábado", "categorias": [
            {"nome": "Elite Masc", "workouts": [
                {"nome": "W4", "tipo": "for_time"},
                {"nome": "W5", "tipo": "express"},
            ]},
        ]},
        {"label": "Domingo", "categorias": [
            {"nome": "Elite Masc", "workouts": [
                {"nome": "W7", "tipo": "for_time"},
            ]},
        ]},
    ]
    assign_workout_numbers_global(dias)
    # Sexta Elite
    assert [w["numero"] for w in dias[0]["categorias"][0]["workouts"]] == [1, 2, 3]
    # Sexta Rx — categoria distinta, reinicia
    assert dias[0]["categorias"][1]["workouts"][0]["numero"] == 1
    # Sábado Elite — continua após Sexta (3) → 4 e 5 (W5 é express → ocupa 5+6)
    assert dias[1]["categorias"][0]["workouts"][0]["numero"] == 4
    assert dias[1]["categorias"][0]["workouts"][1]["numero"] == 5
    assert dias[1]["categorias"][0]["workouts"][1]["numero_f2"] == 6
    # Domingo Elite — após Express ocupar 5+6, próximo é 7
    assert dias[2]["categorias"][0]["workouts"][0]["numero"] == 7


def test_extrair_minutos_aceita_formatos_comuns():
    assert _extrair_minutos("AMRAP 5 MIN") == 5
    assert _extrair_minutos("00:00 → 05:00 · AMRAP 5 MIN") == 5
    assert _extrair_minutos("AMRAP 12 minutos") == 12
    assert _extrair_minutos("") is None
    assert _extrair_minutos("sem minutos aqui") is None


def test_estimar_rounds_algoritmico_retorna_inteiro_razoavel():
    movs = [
        {"nome": "PULL-UPS", "reps": 10},
        {"nome": "THRUSTERS", "reps": 10},
    ]
    n = _estimar_rounds_algoritmico(movs, "AMRAP 5 MIN")
    assert isinstance(n, int)
    assert n >= 2  # mínimo de 2 linhas no scorecard
