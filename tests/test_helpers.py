"""Funções puras: ordenação, numeração, parsers de duração e estimativa de rounds."""
import sumula_app


def test_atleta_sort_key_ordena_por_bateria_raia_numerica_nome(atletas_desordenados):
    ordered = sorted(atletas_desordenados, key=sumula_app._atleta_sort_key)
    assert [a["nome"] for a in ordered] == ["Ana", "Diana", "Bruno", "Carlos"]
    # Ana(A,2) → Diana(A,3) → Bruno(B,1) → Carlos(B,10) — raia 10 vem depois de 2 (numérica)


def test_assign_workout_numbers_express_ocupa_dois_slots():
    workouts = [
        {"nome": "A", "tipo": "for_time"},
        {"nome": "B", "tipo": "express"},
        {"nome": "C", "tipo": "amrap"},
    ]
    sumula_app.assign_workout_numbers(workouts)
    assert workouts[0]["numero"] == 1
    assert workouts[1]["numero"] == 2
    assert workouts[1]["numero_f2"] == 3
    assert workouts[2]["numero"] == 4
    # workouts não-express não devem ter numero_f2
    assert "numero_f2" not in workouts[0]
    assert "numero_f2" not in workouts[2]


def test_extrair_minutos_aceita_formatos_comuns():
    f = sumula_app._extrair_minutos
    assert f("AMRAP 5 MIN") == 5
    assert f("00:00 → 05:00 · AMRAP 5 MIN") == 5
    assert f("AMRAP 12 minutos") == 12
    assert f("") is None
    assert f("sem minutos aqui") is None


def test_estimar_rounds_algoritmico_retorna_inteiro_razoavel():
    movs = [
        {"nome": "PULL-UPS", "reps": 10},
        {"nome": "THRUSTERS", "reps": 10},
    ]
    n = sumula_app._estimar_rounds_algoritmico(movs, "AMRAP 5 MIN")
    assert isinstance(n, int)
    assert n >= 2  # mínimo de 2 linhas no scorecard
