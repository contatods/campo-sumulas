"""Parsers heurísticos: texto livre de workout e Excel do organizador."""
import io
import openpyxl
from parsers import (
    parse_workout_text, parse_excel,
    _quebrar_categoria_composta, _bateria_casa_categoria,
    _propagar_codigos_da_montagem, _filtrar_alocacoes_por_faixa,
    _parse_inscritos,
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


# ── Layout grades-por-modalidade + dias por aba ───────────────────────────────
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


def test_filtrar_alocacoes_por_faixa_mantem_so_numeros_da_categoria():
    # Bateria mista: 3 atletas Scaled Feminino (902-905) + 2 Scaled Masculino (1041-1043)
    alocs = [
        {"raia": "1", "numero": "902",  "nome": "Brianna"},
        {"raia": "2", "numero": "903",  "nome": "Monica"},
        {"raia": "3", "numero": "904",  "nome": "Karla"},
        {"raia": "4", "numero": "1041", "nome": "Dhener"},
        {"raia": "5", "numero": "1042", "nome": "Hiago"},
    ]
    # Filtrando pra Scaled Feminino (901-999): mantém só as 3 primeiras
    fem = _filtrar_alocacoes_por_faixa(alocs, (901, 999))
    assert [a["nome"] for a in fem] == ["Brianna", "Monica", "Karla"]
    # Filtrando pra Scaled Masculino (1001-1099): mantém só as 2 últimas
    masc = _filtrar_alocacoes_por_faixa(alocs, (1001, 1099))
    assert [a["nome"] for a in masc] == ["Dhener", "Hiago"]


def _wb_com_inscritos(linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inscritos"
    for linha in linhas:
        ws.append(linha)
    return wb


def test_parse_inscritos_le_faixas_de_numero():
    wb = _wb_com_inscritos([
        ["Categorias cadastradas"],
        ["Nome", "Max", "Pago", "Nº. Inicial", "Nº. Final", "Individual"],
        ["RX Feminino",  10, 8,  501, 599, "Sim"],
        ["RX Masculino", 10, 10, 601, 699, "Sim"],
    ])
    faixas = _parse_inscritos(wb)
    assert faixas.get("rx feminino")  == (501, 599)
    assert faixas.get("rx masculino") == (601, 699)


def test_parse_inscritos_suporta_multiplos_blocos():
    # Individuais + Duplas no mesmo arquivo, separados por linha vazia
    wb = _wb_com_inscritos([
        ["Categorias cadastradas"],
        ["Nome", "Max", "Pago", "Nº. Inicial", "Nº. Final", "Individual"],
        ["RX Masculino", 10, 10, 601, 699, "Sim"],
        [],
        ["Categorias cadastradas"],
        ["Nome", "Max", "Pago", "Nº. Inicial", "Nº. Final", "Individual"],
        ["Dupla RX Misto", 20, 15, 101, 199, "Não"],
    ])
    faixas = _parse_inscritos(wb)
    assert faixas.get("rx masculino")    == (601, 699)
    assert faixas.get("dupla rx misto") == (101, 199)


def test_parse_inscritos_retorna_vazio_sem_aba():
    wb = openpyxl.Workbook()
    wb.active.title = "OutraAba"
    assert _parse_inscritos(wb) == {}


def test_filtrar_alocacoes_remove_numero_invalido_ou_vazio():
    alocs = [
        {"raia": "1", "numero": "902", "nome": "Foo"},
        {"raia": "2", "numero": "",    "nome": "Sem número"},
        {"raia": "3", "numero": "abc", "nome": "Não numérico"},
        {"raia": "4", "numero": None,  "nome": "None"},
    ]
    out = _filtrar_alocacoes_por_faixa(alocs, (900, 999))
    assert len(out) == 1
    assert out[0]["nome"] == "Foo"
