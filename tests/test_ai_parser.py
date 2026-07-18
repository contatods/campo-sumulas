"""Fase 2: IA como reparador de parsing. Testa o conversor puro (JSON→workout)
e o wiring do fallback (cache, aceitação só-se-válido, nunca pior que regex).
Sem chamar API — mocka a resposta da IA."""
import pytest

import ai_parser
import parsers
from parsers import (parse_workout_text_robusto, registrar_reparador,
                     validar_workout_schema)


@pytest.fixture(autouse=True)
def _reset_reparador():
    """Garante isolamento: nenhum teste vaza o reparador global pros demais."""
    yield
    registrar_reparador(None)
    ai_parser.limpar_cache()


# ── Conversor puro: JSON da IA → dict interno ────────────────────────────────
def test_converter_multijanela():
    js = {
        "nome": "PWRD Loop", "tipo": "amrap", "time_cap": "8 min",
        "score_regra": "soma das Max",
        "janelas": [
            {"titulo": "AMRAP 4 minutes", "rest_depois": "Rest 1 minute",
             "movimentos": [
                 {"nome": "Toes Raises", "reps": 30, "pontua": False},
                 {"nome": "Wall-Ball + DB Front Squat", "max": True}]},
            {"titulo": "AMRAP 4 minutes",
             "movimentos": [
                 {"nome": "Toes Raises", "reps": 30, "pontua": False},
                 {"nome": "Wall-Ball + DB Front Squat", "max": True}]},
        ],
    }
    w = ai_parser._ia_json_para_workout(js, 3)
    assert w["tipo"] == "amrap" and len(w["janelas"]) == 2
    maxes = [m for j in w["janelas"] for m in j["movimentos"] if m.get("max")]
    assert len(maxes) == 2 and all(m["pontua"] for m in maxes)
    presc = [m for j in w["janelas"] for m in j["movimentos"] if not m.get("max")]
    assert all(m["pontua"] is False for m in presc)
    assert validar_workout_schema(w) == []


def test_converter_janela_unica_com_goal():
    js = {"nome": "Rocket", "tipo": "for_time_goal", "time_cap": "10 min",
          "goal_reps": 75, "goal_movimento": "Snatches",
          "movimentos": [{"nome": "Pull-Ups", "reps": 21},
                         {"nome": "Snatches", "reps": None, "goal": True}]}
    w = ai_parser._ia_json_para_workout(js, 1)
    assert w["tipo"] == "for_time_goal" and w["goal_reps"] == 75
    assert any(m.get("goal") for m in w["movimentos"])


def test_converter_rejeita_lixo():
    assert ai_parser._ia_json_para_workout({}, 1) is None
    assert ai_parser._ia_json_para_workout({"tipo": "banana"}, 1) is None
    assert ai_parser._ia_json_para_workout({"tipo": "amrap", "nome": ""}, 1) is None
    assert ai_parser._ia_json_para_workout("nao é dict", 1) is None


def test_extrair_json_tolera_cerca():
    obj = ai_parser._extrair_json_obj('claro:\n```json\n{"tipo":"amrap","nome":"X"}\n```')
    assert obj["tipo"] == "amrap"
    assert ai_parser._extrair_json_obj("sem json aqui") is None


# ── Wiring do fallback no parser ─────────────────────────────────────────────
def _texto_quebrado():
    # 2 janelas AMRAP + linha Max — mas forço um cenário onde a regex falharia.
    # Usamos um texto que a regex parseia mas SEM capturar o essencial pra
    # disparar o reparador (via schema). Simplificamos com monkeypatch abaixo.
    return '"X"\n\nFor time:\n21 Thrusters\nMax Snatches (75lb)\nTime cap: 5 min'


def test_robusto_sem_reparador_e_igual_a_regex():
    registrar_reparador(None)
    from parsers import parse_workout_text
    txt = '"T"\n\nFor time:\n21 Thrusters\n21 Pull-Ups\nTime cap: 8 min'
    assert parse_workout_text_robusto(txt, 1) == parse_workout_text(txt, 1)


def test_robusto_usa_reparo_quando_regex_falha_no_schema(monkeypatch):
    """Se a regex falha no schema e o reparador devolve um workout VÁLIDO,
    o robusto adota o reparo."""
    chamado = {"n": 0}

    def fake_reparador(raw, numero, wkt_regex, problemas):
        chamado["n"] += 1
        # reparo VÁLIDO: representa a pontuação (goal) que a regex tinha dropado
        return {"numero": numero, "nome": "REPARADO", "tipo": "for_time_goal",
                "modalidade": "individual", "time_cap": "5 min", "goal_reps": 75,
                "goal_movimento": "SNATCHES",
                "movimentos": [{"nome": "THRUSTERS", "reps": 21},
                               {"nome": "SNATCHES", "goal": True}], "descricao": []}

    registrar_reparador(fake_reparador)
    # texto que a regex lê deixando problema de schema (Max dropado → pontuacao_perdida)
    txt = '"X"\n\nFor time:\n21 Thrusters\nMax Snatches (75lb)'
    w_regex = parsers.parse_workout_text(txt, 1)
    assert validar_workout_schema(w_regex, txt), "pré-condição: regex deve falhar no schema"
    w = parse_workout_text_robusto(txt, 1)
    assert chamado["n"] == 1
    assert w["nome"] == "REPARADO"
    registrar_reparador(None)


def test_robusto_ignora_reparo_invalido(monkeypatch):
    """Se o reparador devolve algo que TAMBÉM falha no schema, mantém a regex."""
    def reparador_ruim(raw, numero, wkt_regex, problemas):
        return {"numero": numero, "nome": "WKT 1", "tipo": "amrap",  # nome inválido
                "modalidade": "individual", "movimentos": [], "descricao": []}

    registrar_reparador(reparador_ruim)
    txt = '"X"\n\nFor time:\n21 Thrusters\nMax Snatches (75lb)'
    w = parse_workout_text_robusto(txt, 1)
    assert w["nome"] != "WKT 1"   # não adotou o reparo inválido
    registrar_reparador(None)


def test_robusto_reparador_que_explode_nao_derruba(monkeypatch):
    def reparador_bomba(raw, numero, wkt_regex, problemas):
        raise RuntimeError("boom")

    registrar_reparador(reparador_bomba)
    txt = '"X"\n\nFor time:\n21 Thrusters\nMax Snatches (75lb)'
    w = parse_workout_text_robusto(txt, 1)   # não deve levantar
    assert w["tipo"] in ("for_time", "for_time_goal", "amrap")
    registrar_reparador(None)


def test_cache_por_hash(monkeypatch):
    """Mesmo texto → só 1 chamada de API (cache por hash)."""
    ai_parser.limpar_cache()
    chamadas = {"n": 0}

    def fake_api(raw):
        chamadas["n"] += 1
        return {"nome": "C", "tipo": "amrap",
                "movimentos": [{"nome": "ROW", "reps": 10}]}

    monkeypatch.setattr(ai_parser, "_chamar_reparo_ia", fake_api)
    r1 = ai_parser.reparar_workout_ia("mesmo texto", 1)
    r2 = ai_parser.reparar_workout_ia("mesmo texto", 2)
    assert chamadas["n"] == 1, "deveria cachear por hash"
    assert r1 and r2 and r2["numero"] == 2   # conversão respeita o numero novo
    ai_parser.limpar_cache()


def test_integracao_reparador_real_com_api_mockada(monkeypatch):
    """Cadeia completa: regex falha no schema → reparar_workout_ia (real) →
    _chamar_reparo_ia mockado devolve JSON → conversor → parser adota o reparo."""
    ai_parser.limpar_cache()
    # texto que a regex lê perdendo a pontuação (Max dropado)
    txt = '"Simple"\n\nFor time:\n21 Pull-Ups\nMax Snatches (75lb)\nTime cap: 6 min'
    assert validar_workout_schema(parsers.parse_workout_text(txt, 1), txt)  # regex falha

    def fake_api(raw):
        return {"nome": "Simple", "tipo": "for_time_goal", "time_cap": "6 min",
                "goal_reps": 75, "goal_movimento": "Snatches",
                "movimentos": [{"nome": "Pull-Ups", "reps": 21},
                               {"nome": "Snatches", "goal": True}]}

    monkeypatch.setattr(ai_parser, "_chamar_reparo_ia", fake_api)
    registrar_reparador(ai_parser.reparar_workout_ia)
    try:
        w = parse_workout_text_robusto(txt, 1)
        assert w["nome"] == "SIMPLE" and w["tipo"] == "for_time_goal"
        assert w["goal_reps"] == 75
        assert validar_workout_schema(w, txt) == []
    finally:
        registrar_reparador(None)
        ai_parser.limpar_cache()
