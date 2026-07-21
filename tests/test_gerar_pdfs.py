"""Testes do conversor HTML→PDF (gerar_pdfs.py).

Não invocam o Chrome: a impressão é interceptada (monkeypatch em
imprimir_pdf) e os testes validam O QUE seria impresso — fatiamento,
classificação de finais e ordenação do dia completo.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import gerar_pdfs as G


# ── Helpers ──────────────────────────────────────────────────────────────────

def _html_paginas(paginas):
    """HTML no shape do app: lista de (bateria, raia) → 1 página cada.
    bateria/raia vazios viram fline em branco (aguardando balizamento)."""
    corpo = ""
    for bat, raia in paginas:
        b = (f'<div class="fline fline-filled">{bat}</div>' if bat
             else '<div class="fline"></div>')
        r = (f'<div class="fline fline-filled">{raia}</div>' if raia
             else '<div class="fline"></div>')
        corpo += (f'<div class="page"><div class="fl">Bateria / Heat</div>{b}'
                  f'<div class="fl">Raia</div>{r}'
                  f'<div class="page-footer">rodapé</div></div>')
    return ('<!DOCTYPE html><html><head><style>.x{}</style></head><body>'
            + corpo + '</body></html>')


@pytest.fixture
def captura(monkeypatch):
    """Intercepta imprimir_pdf; devolve {caminho_relativo: [páginas (bat,raia)]}."""
    out = {}

    def fake(chrome, html_path, pdf_path):
        corpo = pathlib.Path(html_path).read_text(encoding="utf-8")
        doc = G.dividir_documento(corpo)
        pgs = doc[1] if doc else []
        chave = "/".join(pathlib.Path(pdf_path).parts[-3:])
        out[chave] = [(G.bateria_da_pagina(p), G.raia_da_pagina(p)) for p in pgs]

    monkeypatch.setattr(G, "imprimir_pdf", fake)
    return out


def _converter(tmp_path, arquivos, horarios=None, finais=None, captura=None,
               saidas=None):
    """arquivos: {'Dia/Cat/01_WOD.html': [(bat, raia), ...]}"""
    raiz = tmp_path / "raiz"
    for rel, pgs in arquivos.items():
        f = raiz / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_html_paginas(pgs), encoding="utf-8")
    G.converter(raiz, tmp_path / "out", horarios or {}, chrome="/fake",
                log=lambda m: None, finais=finais or {}, saidas=saidas)
    return captura


# ── Contrato com o template real do gerador ──────────────────────────────────

def test_contrato_fatiamento_com_gerador_real(fonts_empty, evento_basico,
                                              workout_for_time,
                                              atletas_desordenados):
    """Se o template do campo_generator mudar rótulos/estrutura, este teste
    quebra ANTES de o conversor degradar em silêncio no campo."""
    from campo_generator import render_workout_combined
    html = render_workout_combined(evento_basico, workout_for_time,
                                   fonts_empty, "", "", atletas_desordenados)
    doc = G.dividir_documento(html)
    assert doc is not None, "dividir_documento não achou <body>/páginas"
    _, paginas, _ = doc
    assert len(paginas) == len(atletas_desordenados)
    for pg, atleta in zip(paginas, atletas_desordenados):
        assert G.bateria_da_pagina(pg) == atleta["bateria"]
        assert G.raia_da_pagina(pg) == atleta["raia"]


def test_fatiamento_ignora_page_footer():
    html = _html_paginas([("1", "1"), ("1", "2")])
    _, paginas, _ = G.dividir_documento(html)
    assert len(paginas) == 2   # page-footer não pode virar página


# ── Separador de finais ──────────────────────────────────────────────────────

FINAIS_RX = {"Domingo": {"bats": {"27"},
                         "cat_bat": {"Rx_Masculino": ("17:46", "27")},
                         "cat_wkts": {"Rx_Masculino": {"FINAL_WOD"}}}}


def test_finais_por_numero_de_bateria(tmp_path, captura):
    """Páginas com nº de bateria-final entram; das outras baterias, não."""
    cap = _converter(tmp_path, {
        "Domingo/Rx_Masculino/01_WOD1.html": [("11", "1"), ("27", "1"), ("27", "2")],
    }, finais=FINAIS_RX, captura=captura)
    finais = cap["out/Domingo/00_FINAIS.pdf"]
    assert [b for b, _ in finais] == ["27", "27"]


def test_finais_branco_so_do_workout_final(tmp_path, captura):
    """Regressão do bug A1 (auditoria 15/06/2026): dia pré-balizamento
    inteiro em branco NÃO pode despejar workouts comuns no 00_FINAIS —
    só as páginas do workout que a bateria-final roda."""
    cap = _converter(tmp_path, {
        "Domingo/Rx_Masculino/01_WOD1.html":     [("", "")] * 10,
        "Domingo/Rx_Masculino/03_FINAL_WOD.html": [("", "")] * 10,
    }, finais=FINAIS_RX, captura=captura)
    assert len(cap["out/Domingo/00_FINAIS.pdf"]) == 10


def test_finais_branco_sem_info_de_workout_e_permissivo(tmp_path, captura):
    """Sem cat_wkts (bateria roda tudo / config antiga), mantém o
    comportamento de incluir páginas em branco da categoria-final."""
    finais = {"Domingo": {"bats": {"27"},
                          "cat_bat": {"Rx_Masculino": ("17:46", "27")},
                          "cat_wkts": {"Rx_Masculino": set()}}}
    cap = _converter(tmp_path, {
        "Domingo/Rx_Masculino/03_FINAL_WOD.html": [("", "")] * 4,
    }, finais=finais, captura=captura)
    assert len(cap["out/Domingo/00_FINAIS.pdf"]) == 4


def test_categoria_sem_final_nao_gera_finais(tmp_path, captura):
    cap = _converter(tmp_path, {
        "Domingo/Iniciante/01_WOD1.html": [("1", "1"), ("", "")],
    }, finais=FINAIS_RX, captura=captura)
    assert "out/Domingo/00_FINAIS.pdf" not in cap


def test_multiarena_numero_repetido_nao_colide(tmp_path, captura):
    """A2 (auditoria 15/06/2026): se a bateria 5 é final da Alfa (arena A)
    e existe OUTRA bateria 5 na arena B (categoria Beta, sem final), as
    páginas da Beta não podem vazar pro 00_FINAIS."""
    finais = {"Sab": {"bats": {"5"},
                      "cat_bat": {"Alfa": ("17:00", "5")},
                      "cat_wkts": {"Alfa": {"W"}}}}
    cap = _converter(tmp_path, {
        "Sab/Alfa/01_W.html": [("5", "1"), ("5", "2")],
        "Sab/Beta/01_W.html": [("5", "1"), ("5", "2")],   # arena B, não-final
    }, finais=finais, captura=captura)
    assert len(cap["out/Sab/00_FINAIS.pdf"]) == 2         # só as da Alfa


def test_fallback_por_numero_quando_sem_mapa_de_categoria(tmp_path, captura):
    """parse_excel falhou → só os números do PASSO 1: comportamento antigo
    (por nº de bateria) precisa continuar funcionando."""
    finais = {"Sab": {"bats": {"7"}, "cat_bat": {}, "cat_wkts": {}}}
    cap = _converter(tmp_path, {
        "Sab/Alfa/01_W.html": [("6", "1"), ("7", "1")],
    }, finais=finais, captura=captura)
    assert [b for b, _ in cap["out/Sab/00_FINAIS.pdf"]] == ["7"]


def test_finais_do_excel_le_todos_os_blocos_de_arena(tmp_path):
    """Multi-arena (Pwrd By Coffee): a aba tem blocos lado a lado, cada um
    com Categoria/Bateria próprios. Finais marcadas no SEGUNDO bloco têm
    que ser detectadas (a versão inicial só lia o primeiro)."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sábado"
    ws.append(["Arena: Campo", "", "", "", "Arena: Quadra", "", ""])
    ws.append(["Eventos", "Categoria", "Bateria", "",
               "Eventos", "Categoria", "Bateria"])
    ws.append(["W1", "Alfa", 1, "", "W9", "Gama", 53])
    ws.append(["", "Alfa (Final Heat)", 39, "", "", "Gama (Final Heat)", 85])
    xlsx = tmp_path / "prog.xlsx"
    wb.save(xlsx)
    fin = G.finais_do_excel(str(xlsx))
    assert fin["Sábado"]["bats"] == {"39", "85"}   # dos DOIS blocos


# ── Ordenação do dia completo ────────────────────────────────────────────────

def test_mestre_ordena_horario_bateria_raia(tmp_path, captura):
    """Bateria mista (2 categorias no mesmo heat) sai intercalada por raia,
    e os heats seguem o horário — não a ordem alfabética de categoria."""
    horarios = {
        ("Sab", "Zeta", "1"):  "09:00",   # Zeta compete ANTES apesar do nome
        ("Sab", "Alfa", "2"):  "10:00",
        ("Sab", "Zeta", "2"):  "10:00",   # bateria 2 é mista (Alfa + Zeta)
    }
    cap = _converter(tmp_path, {
        "Sab/Alfa/01_W.html": [("2", "2")],
        "Sab/Zeta/01_W.html": [("1", "1"), ("2", "1"), ("2", "3")],
    }, horarios=horarios, captura=captura)
    mestre = cap["out/Sab/00_DIA_COMPLETO.pdf"]
    assert mestre == [("1", "1"), ("2", "1"), ("2", "2"), ("2", "3")]


def test_saidas_so_finais_gera_apenas_finais(tmp_path, captura):
    """Seleção de produtos: {'finais'} não gera baterias nem dia completo —
    é o caminho rápido de regerar finais pós-balizamento."""
    cap = _converter(tmp_path, {
        "Domingo/Rx_Masculino/03_FINAL_WOD.html": [("11", "1"), ("27", "1")],
    }, finais=FINAIS_RX, captura=captura, saidas={"finais"})
    assert list(cap.keys()) == ["out/Domingo/00_FINAIS.pdf"]


def test_saidas_sem_dia_completo(tmp_path, captura):
    cap = _converter(tmp_path, {
        "Sab/Alfa/01_W.html": [("1", "1")],
    }, captura=captura, saidas={"baterias"})
    assert "out/Sab/00_DIA_COMPLETO.pdf" not in cap
    assert "Alfa/01_W/Bateria_01.pdf" in "".join(cap.keys())


def test_saidas_invalidas_caem_no_padrao_tudo(tmp_path, captura):
    cap = _converter(tmp_path, {
        "Sab/Alfa/01_W.html": [("1", "1")],
    }, captura=captura, saidas={"banana"})
    assert "out/Sab/00_DIA_COMPLETO.pdf" in cap          # gerou tudo


def test_sem_horario_agrupa_por_categoria(tmp_path, captura):
    cap = _converter(tmp_path, {
        "Sab/Beta/01_W.html": [("5", "1")],
        "Sab/Alfa/01_W.html": [("9", "1")],
    }, captura=captura)
    mestre = cap["out/Sab/00_DIA_COMPLETO.pdf"]
    assert mestre == [("9", "1"), ("5", "1")]   # Alfa antes de Beta, sem horário
