"""Render de súmulas: HTML único e HTML combinado por workout."""
from campo_generator import render_workout, render_workout_combined


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
