"""Parsers heurísticos: texto livre de workout e Excel do organizador."""
from parsers import (
    parse_workout_text, parse_excel,
    _quebrar_categoria_composta, _bateria_casa_categoria,
    _propagar_codigos_da_montagem,
)


def test_parse_workout_text_for_time_extrai_movimentos_e_time_cap():
    texto = (
        '"TWENTIES"\n'
        "For Time:\n"
        "20 Chest-to-Bar Pull-Ups\n"
        "20 Devil's Presses\n"
        "Time cap: 9 min"
    )
    wkt = parse_workout_text(texto, numero=1)
    assert wkt["nome"] == "TWENTIES"
    assert wkt["tipo"] == "for_time"
    assert wkt["time_cap"] == "9 min"
    nomes = [m.get("nome") for m in wkt["movimentos"] if m.get("nome")]
    assert "CHEST-TO-BAR PULL-UPS" in nomes
    # For Time fecha com chegada
    assert any(m.get("chegada") for m in wkt["movimentos"])


def test_parse_excel_modelo_retorna_estrutura_valida(modelo_xlsx_bytes):
    result = parse_excel(modelo_xlsx_bytes)
    assert isinstance(result, dict)
    # Parser unificado sempre retorna shape evento_multidia (formato antigo é adaptado)
    assert result["tipo"] == "evento_multidia"
    assert "dias" in result
    assert isinstance(result["dias"], list)
    assert len(result["dias"]) >= 1
    # Pelo menos 1 categoria com pelo menos 1 workout
    primeiro_dia = result["dias"][0]
    assert "categorias" in primeiro_dia
    assert len(primeiro_dia["categorias"]) >= 1
    primeiro_workout = primeiro_dia["categorias"][0]["workouts"][0]
    assert "nome" in primeiro_workout
    assert "tipo" in primeiro_workout
    assert primeiro_workout["tipo"] in {"for_time", "amrap", "express"}


# ── Layout grades-por-tipo (Sun Challenge 2026) ───────────────────────────────
def test_quebrar_categoria_composta_separa_e_normaliza():
    partes = _quebrar_categoria_composta(
        "Iniciante Feminino (Heat 3) & Iniciante Masculino (Heat 1)"
    )
    assert partes == ["iniciante feminino", "iniciante masculino"]


def test_bateria_casa_categoria_evita_falso_positivo_dupla_vs_individual():
    # 'rx masculino' não deve casar com 'dupla rx masculino' (categorias distintas)
    assert _bateria_casa_categoria("Rx Masculino (Single Heat)", "rx masculino") is True
    assert _bateria_casa_categoria("Dupla Rx Masculino (Heat 1)", "rx masculino") is False
    assert _bateria_casa_categoria("Dupla Rx Masculino (Heat 1)", "dupla rx masculino") is True


def test_propagar_codigos_da_montagem_preenche_cronograma_vazio():
    # Cronograma sem códigos + montagem com códigos → cronograma fica preenchido
    cronograma = [
        {"numero": "1", "codigo_evento": "", "categoria": "X"},
        {"numero": "2", "codigo_evento": "", "categoria": "Y"},
    ]
    montagem = {
        ("#1", "X", "1"): [{"raia": "1", "nome": "Foo"}],
        ("#2 & #3", "Y", "2"): [{"raia": "1", "nome": "Bar"}],
    }
    _propagar_codigos_da_montagem(cronograma, montagem)
    assert cronograma[0]["codigo_evento"] == "#1"
    assert cronograma[1]["codigo_evento"] == "#2 & #3"


def test_propagar_codigos_nao_sobrescreve_quando_cronograma_ja_tem():
    # Se o cronograma já tem ao menos 1 código, nada é alterado
    cronograma = [
        {"numero": "1", "codigo_evento": "#1", "categoria": "X"},
        {"numero": "2", "codigo_evento": "",   "categoria": "Y"},
    ]
    montagem = {("#9", "Y", "2"): [{"raia": "1", "nome": "Bar"}]}
    _propagar_codigos_da_montagem(cronograma, montagem)
    # Bateria 2 fica sem código (propagador só ativa quando cronograma inteiro está vazio)
    assert cronograma[1]["codigo_evento"] == ""
