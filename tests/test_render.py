"""Render de súmulas: HTML único e HTML combinado por workout."""
import re

from campo_generator import (render_workout, render_workout_combined,
                             render_for_load_team_summary, render_grid)


def _page_div_class(html):
    """Extrai as classes do primeiro <div class="page ...">. Evita falso
    positivo com os nomes de classe que aparecem no bloco <style>."""
    m = re.search(r'<div class="(page[^"]*)"', html)
    return m.group(1) if m else ""


def test_render_grid_um_doc_varias_paginas(evento_basico, workout_for_time, fonts_empty):
    """Fase 2.0 (preview): N súmulas num doc só, 1 page cada, wrapper de
    documento (html/body) UMA vez — senão 156× as fontes estouraria."""
    itens = [
        ({**evento_basico, 'categoria': 'Cat A'}, workout_for_time),
        ({**evento_basico, 'categoria': 'Cat B'}, workout_for_time),
        ({**evento_basico, 'categoria': 'Cat C'}, workout_for_time),
    ]
    html = render_grid(itens, fonts_empty)
    assert html.count("<html") == 1
    assert html.count("<body>") == 1
    assert html.count('<div class="page">') == 3
    assert "CAT A" in html.upper() and "CAT C" in html.upper()


def test_render_workout_for_time_emite_doc_completo(evento_basico, workout_for_time, fonts_empty):
    html = render_workout(evento_basico, workout_for_time, fonts_empty, logo_src="", logo_evento="")
    # Estrutura básica: 1 doc, 1 page
    assert html.count("<html") == 1
    assert html.count("<body>") == 1
    assert html.count('<div class="page">') == 1
    # Conteúdo: nome do workout, evento, time cap, movimento
    assert "TWENTIES" in html
    assert "SUN2026" in html
    assert "9 min" in html
    assert "CHEST-TO-BAR PULL-UPS" in html


def test_render_workout_combined_n_paginas_na_ordem_dos_atletas(
    evento_basico, workout_for_time, fonts_empty, atletas_desordenados
):
    # Não ordena de propósito — o renderer aceita a ordem que receber.
    # Quem ordena por bateria/raia/nome é o handler em _handle_generate.
    html = render_workout_combined(
        evento_basico, workout_for_time, fonts_empty,
        logo_src="", logo_evento="", atletas=atletas_desordenados,
    )
    # 1 doc, 4 pages (uma por atleta)
    assert html.count("<html") == 1
    assert html.count("<body>") == 1
    assert html.count('<div class="page">') == len(atletas_desordenados)
    # Nomes dos atletas aparecem no HTML, na ordem que foi passada
    pos_nomes = [html.find(a["nome"]) for a in atletas_desordenados]
    assert all(p > 0 for p in pos_nomes)
    assert pos_nomes == sorted(pos_nomes)


def test_render_for_load_individual_emite_tentativas_e_barra_correta(fonts_empty):
    """Súmula For Load: barra deduzida do gênero, tentativas, anilhas."""
    ev = {"nome": "EVT", "categoria": "Rx Feminino", "data": "2026", "unidade_default": "kg"}
    wkt = {
        "numero": 1, "nome": "MAX CLEAN", "tipo": "for_load", "modalidade": "individual",
        "tentativas": 3,
        "descricao": [],
    }
    html = render_workout(ev, wkt, fonts_empty, logo_src="", logo_evento="")
    # Tem as 3 tentativas
    for t in ("T1", "T2", "T3"):
        assert t in html, f"esperava {t} na súmula"
    # Anilhas default kg
    for p in (25, 20, 15, 10, 5, 2.5, 1.25):
        assert str(p) in html
    # Barra feminina (categoria Rx Feminino) — 15kg
    assert "15 kg" in html or ">15<" in html
    # NÃO usa barra masculina
    assert "20 kg" not in html  # confere que não vazou a M
    # Melhor Carga aparece
    assert "Melhor Carga" in html or "MELHOR CARGA" in html.upper()


def test_render_for_load_categoria_masculina_usa_barra_de_20kg(fonts_empty):
    ev = {"nome": "EVT", "categoria": "Rx Masculino", "data": "2026", "unidade_default": "kg"}
    wkt = {
        "numero": 1, "nome": "MAX CLEAN", "tipo": "for_load", "modalidade": "individual",
        "tentativas": 3,
    }
    html = render_workout(ev, wkt, fonts_empty, logo_src="", logo_evento="")
    assert "20 kg" in html or ">20<" in html


def test_render_for_load_categoria_mista_individual_usa_barra_masculina(fonts_empty):
    """Categoria MISTO individual (sem time): default conservador = barra M."""
    ev = {"nome": "EVT", "categoria": "Rx Misto", "data": "2026", "unidade_default": "kg"}
    wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
           "modalidade": "individual", "tentativas": 3}
    html = render_workout(ev, wkt, fonts_empty, logo_src="", logo_evento="")
    assert "20 kg" in html, "MISTO individual deve usar barra masculina (20kg)"
    assert "15 kg" not in html, "MISTO individual não deve renderizar barra feminina"


def test_render_for_load_team_dupla_trio_quarteto(fonts_empty):
    """For Load em modalidade dupla/trio/quarteto gera sub-blocos por atleta
    com soma do time no fim. Quarteto entra em layout super-compacto."""
    import re
    ev = {"nome": "EVT", "categoria": "Trio Rx Misto", "data": "2026", "unidade_default": "kg"}
    atl = {"nome": "TIME X", "box": "CF", "raia": "1", "numero": "1", "bateria": "1"}
    for modalidade, n_atletas_esperado, super_compact_esperado in [
        ("individual", 0, False),  # sem sub-blocos
        ("dupla", 2, False),
        ("trio", 3, False),
        ("quarteto", 4, True),     # super-compact pra caber em A4
    ]:
        wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
               "modalidade": modalidade, "tentativas": 3}
        html = render_workout(ev, wkt, fonts_empty, "", "", atl)
        n_blocos = len(re.findall(r'class="fl-atleta-bloco"', html))
        n_tents = len(re.findall(r'>T\d+<', html))
        assert n_blocos == n_atletas_esperado, (
            f"{modalidade}: esperava {n_atletas_esperado} sub-blocos, got {n_blocos}"
        )
        # Tentativas totais = N atletas × 3 (em team) ou 3 (em individual)
        esperado_tents = (n_atletas_esperado or 1) * 3
        assert n_tents == esperado_tents, (
            f"{modalidade}: esperava {esperado_tents} tentativas, got {n_tents}"
        )
        m = re.search(r'<div class="fl-zone[^"]*"', html)
        super_c = "fl-zone-super-compact" in m.group()
        assert super_c == super_compact_esperado, (
            f"{modalidade}: super-compact esperado {super_compact_esperado}, got {super_c}"
        )
        # Team tem 'Soma do Time' no fim
        if n_atletas_esperado > 0:
            assert "Soma do Time" in html


def test_render_for_load_team_pre_workout_modalidade(fonts_empty):
    """Sub-bloco por atleta exibe 'Atleta 1', 'Atleta 2', etc — e label
    'Melhor Carga' por atleta (não 'Melhor Atleta N' — esse termo confunde
    semântica: o campo registra o peso lifted, não escolhe qual atleta)."""
    import re
    ev = {"nome": "EVT", "categoria": "Trio", "data": "2026"}
    atl = {"nome": "T", "box": "C", "raia": "1", "numero": "1", "bateria": "1"}
    wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
           "modalidade": "trio", "tentativas": 3}
    html = render_workout(ev, wkt, fonts_empty, "", "", atl)
    for pos in (1, 2, 3):
        assert f"Atleta {pos}" in html
    # 'Melhor Carga' rotula cada sub-bloco (3 atletas)
    import re
    n_label = len(re.findall(r'class="fl-atleta-melhor-lbl">Melhor Carga<', html))
    assert n_label == 3


def test_render_for_load_compact_para_tentativas_altas(fonts_empty):
    """Pra 5+ tentativas, layout compacto é aplicado (cabe em A4).
    Pra 4 ou menos, layout expandido (2 linhas por tentativa)."""
    import re
    ev = {"nome": "EVT", "categoria": "Rx Masculino", "data": "2026", "unidade_default": "kg"}
    atl = {"nome": "X", "box": "CF", "raia": "1", "numero": "101", "bateria": "1"}
    for n, esperado_compact in [(3, False), (4, False), (5, True), (8, True)]:
        wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
               "modalidade": "individual", "tentativas": n}
        html = render_workout(ev, wkt, fonts_empty, "", "", atl)
        m = re.search(r'<div class="fl-zone( fl-zone-compact)?"', html)
        assert m, f"div fl-zone não encontrado pra {n} tentativas"
        is_compact = bool(m.group(1))
        assert is_compact == esperado_compact, (
            f"{n} tentativas: esperado compact={esperado_compact}, got={is_compact}"
        )


def test_render_modalidades_aplica_label_correto(fonts_empty):
    """Modalidade muda o label de 'Nome do X' no pré-workout."""
    ev = {"nome": "EVT", "categoria": "Rx", "data": "2026"}
    atl = {"nome": "X", "box": "CF", "raia": "1", "numero": "1", "bateria": "1"}
    wkt_base = {"numero": 1, "nome": "WKT", "tipo": "for_time", "time_cap": "5 min",
                "movimentos": [{"nome": "PULL-UPS", "reps": 10}, {"chegada": True}]}
    for modalidade, label_esperado in [
        ("individual", "Nome do Atleta"),
        ("dupla", "Nome da Dupla"),
        ("trio", "Nome do Trio"),
        ("quarteto", "Nome do Quarteto"),
        ("time", "Nome do Time"),
    ]:
        wkt = {**wkt_base, "modalidade": modalidade}
        html = render_workout(ev, wkt, fonts_empty, "", "", atl)
        assert label_esperado in html, f"modalidade {modalidade!r}: esperava {label_esperado!r}"


def test_render_for_load_libras(fonts_empty):
    ev = {"nome": "EVT", "categoria": "Rx Masculino", "data": "2026", "unidade_default": "lb"}
    wkt = {
        "numero": 1, "nome": "MAX CLEAN", "tipo": "for_load", "modalidade": "individual",
        "tentativas": 3,
    }
    html = render_workout(ev, wkt, fonts_empty, logo_src="", logo_evento="")
    # Barra M default em lb = 45
    assert "45 lb" in html
    # Anilha default lb inclui 55
    assert ">55<" in html or "55" in html


def test_render_for_load_team_summary_lista_atletas_e_soma(fonts_empty):
    """Resumo de time For Load: lista cada atleta com campo de melhor carga + soma."""
    ev = {"nome": "EVT", "categoria": "Dupla Misto", "data": "2026", "unidade_default": "kg"}
    wkt = {"numero": 1, "nome": "MAX CLEAN", "tipo": "for_load",
           "modalidade": "dupla", "tentativas": 3, "unidade": "kg"}
    atletas = [
        {"nome": "João Silva", "box": "CF ALFA", "numero": "401", "raia": "1", "bateria": "1"},
        {"nome": "Maria Souza", "box": "CF DELTA", "numero": "402", "raia": "1", "bateria": "1"},
    ]
    html = render_for_load_team_summary(ev, wkt, fonts_empty, "", "", atletas)
    # Tem todos os atletas pelo nome
    for a in atletas:
        assert a["nome"].upper() in html
    # Tem o campo "Soma do Time"
    assert "Soma do Time" in html or "SOMA DO TIME" in html.upper()
    # Header tem "Resumo do Time"
    assert "RESUMO DO TIME" in html.upper()


def test_render_for_time_relay_renderiza_blocos_atleta_com_cum_continuo(fonts_empty):
    """For Time com `rounds_per_atleta` + modalidade team renderiza UMA tabela
    de movimentos, mas com separador 'Atleta N' entre blocos. Reps cumulativos
    seguem entre atletas — workout contínuo, score do time, UM tempo total."""
    import re
    ev = {"nome": "EVT", "categoria": "Trio Rx", "data": "2026"}
    wkt = {
        "numero": 1, "nome": "SPIN", "tipo": "for_time", "modalidade": "trio",
        "time_cap": "12 min", "rounds_per_atleta": 1,
        "movimentos": [
            {"nome": "ROPE CLIMBS", "reps": 3},
            {"nome": "30/24 CAL ROW", "reps": 30},
            {"chegada": True},
        ],
    }
    html = render_workout(ev, wkt, fonts_empty, "", "")
    # Nota do formato no topo
    assert "Formato Relay" in html
    assert "1 Round por Atleta" in html
    # 3 separadores 'Atleta N' com linha de nome
    n_atletas = len(re.findall(r'class="atleta-sep-row"', html))
    assert n_atletas == 3
    # Movimentos repetem por atleta (mas em UMA tabela só, reps cum acumulam)
    assert html.count("ROPE CLIMBS") == 3
    assert html.count("CAL ROW") == 3
    # Chegada aparece uma vez no fim
    assert html.count("chegada-inline") >= 1


def test_render_for_time_paralelo_marca_movimentos(fonts_empty):
    """Movimentos com `paralelo: True` ganham classe mov-row-paralelo."""
    ev = {"nome": "EVT", "categoria": "Trio Rx", "data": "2026"}
    wkt = {
        "numero": 1, "nome": "SIMPLE", "tipo": "for_time", "modalidade": "trio",
        "time_cap": "12 min",
        "movimentos": [
            {"nome": "900M SKI ERG", "reps": 900, "paralelo": True},
            {"nome": "DOUBLE-UNDERS", "reps": 150, "paralelo": True},
            {"nome": "PULL-UPS", "reps": 21},  # sem paralelo
            {"chegada": True},
        ],
    }
    html = render_workout(ev, wkt, fonts_empty, "", "")
    # Classe presente nos paralelos
    assert 'class="mov-row mov-row-paralelo"' in html
    # Mark visual presente
    assert "mr-paralelo-mark" in html


def test_render_amrap_emom_mostra_header_correto(fonts_empty):
    """AMRAP com emom_janela + emom_rounds mostra 'EMOM X × Y rounds'."""
    ev = {"nome": "EVT", "categoria": "Trio Rx", "data": "2026"}
    wkt = {
        "numero": 1, "nome": "RECAP", "tipo": "amrap", "modalidade": "trio",
        "emom_janela": "2:30", "emom_rounds": 5,
        "movimentos": [
            {"nome": "SWIM", "reps": 50},
            {"nome": "THRUSTERS", "reps": 10},
        ],
    }
    html = render_workout(ev, wkt, fonts_empty, "", "")
    assert "EMOM 2:30" in html
    assert "5 rounds" in html
    # EMOM não emite linha R+ (apenas N rounds fixos)
    assert "amrap-row rplus-row" not in html
    assert ">R+<" not in html


def test_render_amrap_tiebreak_por_round_adiciona_coluna(fonts_empty):
    """AMRAP com tiebreak_por_round adiciona coluna de tiebreak no scorecard."""
    import re
    ev = {"nome": "EVT", "categoria": "Trio Rx", "data": "2026"}
    wkt = {
        "numero": 1, "nome": "RECAP", "tipo": "amrap", "modalidade": "trio",
        "emom_janela": "2:30", "emom_rounds": 5, "tiebreak_por_round": True,
        "movimentos": [{"nome": "SWIM", "reps": 50}],
    }
    html = render_workout(ev, wkt, fonts_empty, "", "")
    n_tb = len(re.findall(r'class="ar-tb-cell"', html))
    assert n_tb == 5, f"esperava 5 células tiebreak (1/round), got {n_tb}"
    assert "Tie-break" in html


def test_render_for_load_trio_misto_atleta_1_usa_barra_feminina(fonts_empty):
    """Trio Rx Misto: atleta 1 = F (15kg), atletas 2 e 3 = M (20kg)."""
    import re
    ev = {"nome": "EVT", "categoria": "Trio Rx Misto", "data": "2026", "unidade_default": "kg"}
    atl = {"nome": "TRIO X", "box": "CF", "raia": "1", "numero": "401", "bateria": "1"}
    wkt = {"numero": 1, "nome": "MAX CLEAN", "tipo": "for_load",
           "modalidade": "trio", "tentativas": 3}
    html = render_workout(ev, wkt, fonts_empty, "", "", atl)
    # 3 sub-blocos
    n_blocos = len(re.findall(r'class="fl-atleta-bloco"', html))
    assert n_blocos == 3
    # Header da zone indica misto
    assert "Misto · Barras conforme atleta" in html
    # Atleta 1 = F (com label 'Barra 15 kg' no header do bloco)
    blocos = html.split('class="fl-atleta-bloco"')
    # blocos[0] é antes do 1º bloco; blocos[1..3] são os 3 sub-blocos
    assert "(F)" in blocos[1] and "15 kg" in blocos[1]
    assert "(M)" in blocos[2] and "20 kg" in blocos[2]
    assert "(M)" in blocos[3] and "20 kg" in blocos[3]


def test_render_for_load_dupla_misto_atleta_1_F_atleta_2_M(fonts_empty):
    ev = {"nome": "EVT", "categoria": "Dupla Misto", "data": "2026", "unidade_default": "kg"}
    atl = {"nome": "DUPLA", "box": "CF", "raia": "1", "numero": "1", "bateria": "1"}
    wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
           "modalidade": "dupla", "tentativas": 3}
    html = render_workout(ev, wkt, fonts_empty, "", "", atl)
    blocos = html.split('class="fl-atleta-bloco"')
    assert "(F)" in blocos[1] and "15 kg" in blocos[1]
    assert "(M)" in blocos[2] and "20 kg" in blocos[2]


def test_render_for_load_quarteto_misto_2F_2M(fonts_empty):
    ev = {"nome": "EVT", "categoria": "Quarteto Misto", "data": "2026", "unidade_default": "kg"}
    atl = {"nome": "QUARTETO", "box": "CF", "raia": "1", "numero": "1", "bateria": "1"}
    wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
           "modalidade": "quarteto", "tentativas": 3}
    html = render_workout(ev, wkt, fonts_empty, "", "", atl)
    blocos = html.split('class="fl-atleta-bloco"')
    # 4 atletas: 1=F, 2=F, 3=M, 4=M
    assert "(F)" in blocos[1] and "(F)" in blocos[2]
    assert "(M)" in blocos[3] and "(M)" in blocos[4]


def test_render_for_load_trio_rx_nao_misto_nao_aplica_genero_por_atleta(fonts_empty):
    """Trio Rx Masculino: todos os sub-blocos com mesma barra M, sem marca de gênero."""
    ev = {"nome": "EVT", "categoria": "Trio Rx Masculino", "data": "2026", "unidade_default": "kg"}
    atl = {"nome": "TRIO", "box": "CF", "raia": "1", "numero": "1", "bateria": "1"}
    wkt = {"numero": 1, "nome": "MAX", "tipo": "for_load",
           "modalidade": "trio", "tentativas": 3}
    html = render_workout(ev, wkt, fonts_empty, "", "", atl)
    assert "Misto · Barras conforme atleta" not in html
    assert "Barra Masculina 20 kg" in html
    # Sem marca de gênero por atleta (a classe é definida no CSS mas não usada)
    assert 'class="fl-atleta-genero"' not in html


def test_parse_excel_aplica_equipamento_aos_for_load(fonts_empty):
    """parse_excel injeta anilhas + unidade nos workouts For Load do evento."""
    import openpyxl, io
    from parsers import parse_excel
    wb = openpyxl.Workbook()
    # Workouts (com pelo menos um For Load)
    ws_w = wb.create_sheet("Workouts")
    ws_w.append(["Categoria", "WKT 1"])
    ws_w.append(["Rx Masculino", "MAX CLEAN\nFor Load"])
    # Equipamento
    ws_e = wb.create_sheet("Equipamento")
    ws_e.append(["Anilha", "Peso", "Qtd"])
    ws_e.append(["A", "45lb", 8])
    ws_e.append(["B", "35lb", 4])
    ws_e.append(["C", "25lb", 4])
    # Remove a Sheet default
    if "Sheet" in wb.sheetnames: del wb["Sheet"]
    buf = io.BytesIO()
    wb.save(buf)
    result = parse_excel(buf.getvalue())
    # Equipamento detectado em top-level
    if result.get("tipo") != "erro":
        assert result.get("unidade_default") == "lb"
        assert result.get("equipamento", {}).get("anilhas") == [45, 35, 25]


def test_render_escapa_html_de_input_do_usuario(fonts_empty):
    """Garante que dados externos (nome, box, etc) são escapados — sem XSS."""
    ev = {"nome": "<script>alert(1)</script>", "categoria": "A & B", "data": "2026"}
    wkt = {
        "numero": 1, "nome": '"Hack"', "tipo": "for_time", "modalidade": "individual",
        "time_cap": "9 min",
        "movimentos": [{"nome": "<img src=x>", "reps": 20}, {"chegada": True}],
    }
    atleta = {"nome": 'João <b>X</b>', "box": 'CF "Aspas"',
              "raia": "1", "numero": "001", "bateria": "1"}
    html = render_workout(ev, wkt, fonts_empty, logo_src="", logo_evento="", atleta=atleta)
    # Strings cruas NÃO podem aparecer
    assert "<script>alert" not in html
    assert "<img src=x>" not in html
    assert "<b>X</b>" not in html
    # Versão escapada SIM — template usa |upper no nome do evento
    assert "&lt;SCRIPT&gt;" in html
    assert "A &amp; B" in html


def test_render_buyin_mais_rounds_bloco_stack_bad(evento_basico, fonts_empty):
    """Stack Bad (Pwrd): buy-in '1000m Ski Erg' UMA vez + bloco 'then, 2 rounds
    of' repetido 2×. Regressão: antes vinha só 1 round depois do Ski."""
    from parsers import parse_workout_text
    texto = ('"Stack Bad"\n\nFor time:\n1000m Ski Erg\nthen, 2 rounds of:\n'
             '30 Handstand Push-Ups\n400m Run\n30 Line-Facing Burpees\n\n'
             'Time cap: 16 minutes')
    wkt = parse_workout_text(texto, "STACK BAD")
    html = render_workout(evento_basico, wkt, fonts_empty, logo_src="", logo_evento="")
    assert "Round 1" in html and "Round 2" in html and "Round 3" not in html
    assert html.upper().count("SKI ERG") == 1, "buy-in não pode multiplicar"
    assert html.upper().count("HANDSTAND PUSH-UP") == 2, "bloco deve rodar 2 rounds"
    assert "Buy-in +" in html


def test_render_muitos_rounds_ativa_compactacao_a4(evento_basico, fonts_empty):
    """Dupla com 5 rounds (Rocket): 25 linhas efetivas → classe is-denso-x pra
    caber no A4 sem cortar o 5º round. Regressão do overflow reportado."""
    from parsers import parse_workout_text
    texto = ('"Rocket"\n\n5 rounds for time of:\n12 Deadlifts\n9 Hang Power Cleans\n'
             '6 Shoulder-to-Overhead\n3 Bar Muscle-Ups\n\nTime cap: 12 minutes')
    wkt = parse_workout_text(texto, "ROCKET")
    wkt["modalidade"] = "dupla"
    html = render_workout(evento_basico, wkt, fonts_empty, logo_src="", logo_evento="")
    assert wkt.get("rounds_fixos") == 5
    assert "Round 5" in html, "todos os 5 rounds devem renderizar"
    assert "is-denso-x" in _page_div_class(html), "compactação agressiva não ativou"


def test_render_for_time_curto_nao_ativa_compactacao(evento_basico, workout_for_time, fonts_empty):
    """For time pequeno NÃO deve ganhar a classe de compactação (mantém rows
    generosas pra escrita)."""
    html = render_workout(evento_basico, workout_for_time, fonts_empty, logo_src="", logo_evento="")
    assert "is-denso" not in _page_div_class(html)


def test_render_rounds_sem_chegada_nao_adiciona_linha(evento_basico, fonts_empty):
    """rounds_fixos NÃO deve forçar a linha de chegada quando o Excel diz que
    não há chegada — o render seguia o parser errado e sempre anexava uma."""
    from parsers import parse_workout_text
    def n_chegada(nota_extra):
        w = parse_workout_text('"Rocket"\n\n5 rounds for time of:\n12 Deadlifts\n'
                               '9 Snatches\n' + nota_extra + '\nTime cap: 12 min', 1)
        w["modalidade"] = "dupla"
        html = render_workout(evento_basico, w, fonts_empty, logo_src="", logo_evento="")
        # descontar as 6 regras CSS `.chegada-inline`; sobra = linhas reais.
        return html.count("chegada-inline") - 6
    assert n_chegada("\nA chegada não conta como repetição") == 0
    assert n_chegada("") == 1   # default mantém 1 linha de chegada


def test_render_amrap_multijanela_pwrd_loop(evento_basico, fonts_empty):
    """Render do PWRD Loop: 2 rounds, linhas MAX presentes (o que pontua),
    prescritos marcados 'não pontua', rest entre janelas, score = soma; o score
    box AMRAP padrão NÃO aparece (tem o de soma)."""
    from parsers import parse_workout_text
    from tests.test_parsers import PWRD_LOOP
    w = parse_workout_text(PWRD_LOOP, 1)
    w["modalidade"] = "trio"
    html = render_workout(evento_basico, w, fonts_empty, logo_src="", logo_evento="")
    assert "Round 1" in html and "Round 2" in html
    assert html.upper().count("WALL-BALL SHOTS") >= 2, "linhas MAX (pontuáveis) sumiram"
    assert html.count('jan-row jan-row-max') == 2
    assert "não pontua" in html and "conta" in html
    assert "RESET EQUIPMENT" in html.upper()          # rest-bar entre janelas
    assert 'class="jan-scorebox"' in html             # score = soma das janelas
    assert '<div class="score-box' not in html        # não duplica o score AMRAP


# ── Multi-score: um campo de anotação por pontuação declarada ───────────────
def _multi_score_wkt(workout_for_time):
    return {
        **workout_for_time,
        "nome": "FIRE BURNING 1, 2 & 3",
        "movimentos": [
            {"nome": "SYNC. THRUSTERS", "carga": "60/40 KG",
             "max": True, "pontua": True, "executantes": "A/B"},
            {"nome": "CAL ROW", "reps": 100, "executantes": "C/D"},
            {"chegada": True},
        ],
        "scores": [
            {"label": "A", "nome": "Fire Burning 1", "tipo": "reps",
             "descricao": "reps de thruster do Bloco 1", "pontos": 100},
            {"label": "B", "nome": "Fire Burning 2", "tipo": "reps",
             "descricao": "reps de thruster do Bloco 3", "pontos": 100},
            {"label": "C", "nome": "Fire Burning 3", "tipo": "tempo",
             "descricao": "tempo total de conclusão", "pontos": 200},
        ],
    }


def test_render_multi_score_um_campo_por_pontuacao(evento_basico, workout_for_time, fonts_empty):
    """Workout que vale 3 pontuações rende 3 campos de anotação — um por score,
    com rótulo, nome e peso. Com o score_box genérico (Tempo/Reps) o juiz não
    teria onde escrever a 2ª e a 3ª pontuação."""
    wkt = _multi_score_wkt(workout_for_time)
    html = render_workout(evento_basico, wkt, fonts_empty, "")
    campos = re.findall(r'<div class="sb-field sb-field-score">(.*?)<div class="sb-field-line">',
                        html, re.S)
    assert len(campos) == 3, f'esperava 3 campos, veio {len(campos)}'
    for esperado in ('Fire Burning 1', 'Fire Burning 2', 'Fire Burning 3'):
        assert esperado in html
    assert '>A<' in html and '>B<' in html and '>C<' in html   # badges dos rótulos
    assert '200 pts' in html and '100 pts' in html
    # unidade por tipo: tempo escreve m:s, reps escreve total
    assert 'm:s' in campos[2]
    assert 'total de reps' in campos[0]
    assert '3 pontuações independentes' in html


def test_render_score_unico_mantem_score_box_do_tipo(evento_basico, workout_for_time, fonts_empty):
    """Sem `scores`, nada muda: segue o score_box do tipo (For Time)."""
    html = render_workout(evento_basico, workout_for_time, fonts_empty, "")
    assert 'sb-field-score' not in html.split('</style>')[-1]
    assert 'sb-field-tempo' in html and 'sb-field-reps' in html


def test_render_badge_max_e_chip_de_executantes(evento_basico, workout_for_time, fonts_empty):
    """A linha 'Max' precisa do badge MAX (é o que pontua) e do chip de quem
    executa — sem eles o juiz vê uma caixa vazia sem saber o que anotar."""
    wkt = _multi_score_wkt(workout_for_time)
    html = render_workout(evento_basico, wkt, fonts_empty, "")
    corpo = html.split('</style>')[-1]
    assert '<span class="mr-max-badge">MAX</span>' in corpo
    assert '<span class="mr-exec">A/B</span>' in corpo
    assert '<span class="mr-exec">C/D</span>' in corpo
    # o badge não pode duplicar o nome ('MAX MAX SYNC. THRUSTERS')
    assert 'MAX SYNC. THRUSTERS' not in re.sub(r'<[^>]+>', '', corpo)


# ── Scorecard AMRAP: enche a página em vez de limitar rounds ────────────────
def test_constantes_de_altura_batem_com_o_css():
    """`linhas_amrap_que_cabem` soma alturas que espelham o CSS. Se o layout
    mudar e as constantes não, a conta erra em silêncio e a súmula perde (ou
    estoura) linhas. Este teste reparseia o CSS e trava o acoplamento."""
    import re
    from campo_generator import (CSS, PAGE_ALTURA_MM, AMRAP_ROW_MM,
                                 _AMRAP_BLOCOS_FIXOS_MM)

    # Comentários do CSS contêm chaves literais ('page-footer{margin-top:auto}')
    # que truncariam a captura do bloco — tira antes de parsear.
    css = re.sub(r'/\*.*?\*/', '', CSS, flags=re.S)

    def altura(seletor, prop='height'):
        m = re.search(r'(?:^|\})\s*' + re.escape(seletor) + r'\s*\{([^}]*)\}', css, re.M)
        assert m, f'seletor {seletor} sumiu do CSS'
        mh = re.search(r'(?:min-)?' + prop + r'\s*:\s*([\d.]+)mm', m.group(1))
        assert mh, f'{seletor} não declara {prop} em mm'
        return float(mh.group(1))

    assert altura('.page') == PAGE_ALTURA_MM
    assert altura('.amrap-row') == AMRAP_ROW_MM
    assert altura('.hdr') == _AMRAP_BLOCOS_FIXOS_MM['hdr']
    # score_box = .score-section + .score-box + margem 1.5
    assert (altura('.score-section') + altura('.score-box') + 1.5
            == _AMRAP_BLOCOS_FIXOS_MM['score_box'])
    # obs_box = .obs-box{min-height} + margin-bottom 1
    assert altura('.obs-box') + 1.0 == _AMRAP_BLOCOS_FIXOS_MM['obs_box']
    # amrap_chrome = .amrap-hdr + .amrap-subhdr + bordas
    assert (altura('.amrap-hdr') + altura('.amrap-subhdr') + 4.0
            == _AMRAP_BLOCOS_FIXOS_MM['amrap_chrome'])


def test_linhas_amrap_cabem_na_pagina():
    """O total calculado + os blocos fixos não pode passar da altura da página
    — senão o CSS (`overflow:hidden`) corta a última linha sem avisar."""
    from campo_generator import (linhas_amrap_que_cabem, PAGE_ALTURA_MM,
                                 AMRAP_ROW_MM, _AMRAP_BLOCOS_FIXOS_MM)
    fixo = sum(_AMRAP_BLOCOS_FIXOS_MM.values())
    for wkt in ({}, {'descricao': ['a', 'b', 'c']}, {'descricao': ['x'] * 8}):
        n = linhas_amrap_que_cabem(wkt)
        desc = len(wkt.get('descricao') or [])
        usado = fixo + n * AMRAP_ROW_MM + (3.0 + desc * 4.0 if desc else 0)
        assert usado <= PAGE_ALTURA_MM, f'{wkt}: {usado}mm > {PAGE_ALTURA_MM}mm'


def test_amrap_enche_a_pagina_em_vez_de_travar_em_4_rounds(evento_basico, fonts_empty):
    """AMRAP com estimativa baixa ainda ganha linhas até encher a página. Um
    time que supera a estimativa precisa de onde anotar — limitar a súmula em
    3-4 rounds é o risco, não o desperdício de linha em branco."""
    import re
    wkt = {
        "numero": 7, "nome": "FAST RELAY", "tipo": "amrap",
        "modalidade": "quarteto", "time_cap": "16 min", "n_rounds": 3,
        "movimentos": [
            {"nome": "DOUBLE UNDERS", "reps": 30},
            {"nome": "WALL-BALL SHOTS", "reps": 30, "carga": "9/6 KG",
             "progressivo": True, "reps_delta": 10,
             "reps_por_round": [30, 40, 50, 60, 70]},
        ],
    }
    html = render_workout(evento_basico, wkt, fonts_empty, "")
    linhas = re.findall(r'<div class="amrap-row([^"]*)">', html)
    assert len(linhas) >= 12, f'só {len(linhas)} linhas — estimativa travou a tabela'
    # nenhuma linha esmaecida: quando a tabela enche a página, todas valem igual
    assert not [x for x in linhas if 'rplus' in x]


def test_progressao_extrapola_alem_da_lista_pre_computada(evento_basico, fonts_empty):
    """`reps_por_round` é gerada no parse com 5 rounds. Nas linhas seguintes as
    reps têm que continuar progredindo (80, 90, 100…), não voltar pra base."""
    import re
    wkt = {
        "numero": 7, "nome": "FR", "tipo": "amrap", "modalidade": "quarteto",
        "time_cap": "16 min", "n_rounds": 3,
        "movimentos": [{"nome": "WALL-BALL SHOTS", "reps": 30,
                        "progressivo": True, "reps_delta": 10,
                        "reps_por_round": [30, 40, 50, 60, 70]}],
    }
    html = render_workout(evento_basico, wkt, fonts_empty, "")
    refs = re.findall(r'<span class="ar-ref-lbl">ref</span>([^<]*)</span>', html)
    assert refs[:7] == ['30', '40', '50', '60', '70', '80', '90'], refs[:7]
    assert '30' not in refs[5:], 'voltou pra rep base depois da lista pré-computada'


# ── Render do formato de eliminação ─────────────────────────────────────────
def _elim_wkt():
    return {
        "numero": 13, "nome": "THE LAST OF US", "tipo": "eliminacao",
        "modalidade": "quarteto", "time_cap": "15 min",
        "rounds_fixos": 5, "janela_round": "3", "eliminados_por_round": 2,
        "movimentos": [
            {"nome": "20M HANDSTAND WALK", "reps": 20},
            {"nome": "SYNC. DUAL-DUMBBELL DEVIL PRESS", "carga": "22,5/15 KG", "reps": 15},
            {"nome": "RUN TO FINISH", "posicao": True},
        ],
    }


def test_janelas_de_round():
    """O juiz precisa do relógio de cada round: num formato de eliminação,
    quem não fecha a janela está fora, então a hora do corte é arbitragem."""
    from campo_generator import janelas_de_round
    assert janelas_de_round('3', 5) == ['0:00–3:00', '3:00–6:00', '6:00–9:00',
                                        '9:00–12:00', '12:00–15:00']
    assert janelas_de_round('2:30', 2) == ['0:00–2:30', '2:30–5:00']
    assert janelas_de_round('', 5) == [] and janelas_de_round('x', 3) == []
    assert janelas_de_round('3', 0) == []


def test_render_eliminacao_grade_de_rounds(evento_basico, fonts_empty):
    """Uma linha por round com janela, campo de posição e marcação de
    eliminado — a prescrição aparece UMA vez, não repetida 5×."""
    html = render_workout(evento_basico, _elim_wkt(), fonts_empty, "")
    corpo = html.split('</style>')[-1]
    linhas = re.findall(r'<div class="elim-row">', corpo)
    assert len(linhas) == 5, f'esperava 5 rounds, veio {len(linhas)}'
    for janela in ('0:00–3:00', '3:00–6:00', '12:00–15:00'):
        assert janela in corpo, f'janela {janela} ausente'
    assert corpo.count('er-box') == 5          # um checkbox de eliminado por round
    # prescrição aparece uma vez só
    assert corpo.count('20M HANDSTAND WALK') == 1


def test_render_eliminacao_banner_e_score(evento_basico, fonts_empty):
    """Banner traz a regra do formato; o score box pede posição de chegada e
    round de saída — não tempo, que não é o score deste workout."""
    html = render_workout(evento_basico, _elim_wkt(), fonts_empty, "")
    corpo = html.split('</style>')[-1]
    assert '5 rounds' in corpo and '2 eliminados por round' in corpo
    campos = re.findall(r'<span class="sb-field-lbl">(.*?)<', corpo)
    assert any('Posição Final' in c for c in campos), campos
    assert any('Round de Saída' in c for c in campos), campos
    assert not any('Tempo' in c for c in campos), 'tempo não é o score aqui'
    assert 'POSIÇÃO' in corpo                  # badge no movimento de chegada
    assert 'Eliminação' in corpo               # rótulo do tipo no cabeçalho


def test_render_nao_repete_distancia_no_nome(evento_basico, workout_for_time, fonts_empty):
    """'900M SKI ERG' já traz a medida — o render não pode imprimir
    '(900) 900M SKI ERG'. Movimento de reps normal segue com o '(N)'."""
    wkt = {**workout_for_time, "movimentos": [
        {"nome": "900M SKI ERG", "reps": 900},
        {"nome": "THRUSTERS", "reps": 20},
    ]}
    corpo = render_workout(evento_basico, wkt, fonts_empty, "").split('</style>')[-1]
    assert '(900)' not in corpo
    assert '(20)' in corpo
