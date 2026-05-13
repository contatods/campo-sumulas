"""Testes end-to-end: import + geração de ZIP + validação + render Express.

Estes testes cobrem caminhos que tocam parser + handler + render juntos.
Usam fixture xlsx in-memory pra evitar dependência de arquivos binários.
"""
import io
import json
import zipfile

import openpyxl

from parsers import parse_excel
from ai_rounds import validar_evento
from campo_generator import render_workout


# ── #1: import end-to-end do layout grades-e-dias ─────────────────────────────
def test_parse_excel_grades_e_dias_end_to_end(xlsx_grades_e_dias_bytes):
    result = parse_excel(xlsx_grades_e_dias_bytes)
    assert result["tipo"] == "evento_multidia"
    assert len(result["dias"]) == 1
    dia = result["dias"][0]
    assert dia["label"] == "Sábado"

    # 2 categorias detectadas: Rx Masculino e Scaled Masculino
    nomes_cats = {c["nome"] for c in dia["categorias"]}
    assert nomes_cats == {"Rx Masculino", "Scaled Masculino"}

    # Rx Masculino: 2 baterias (#1 Heat 1, #1 Heat 2 via mista, #2 Final)
    rx = next(c for c in dia["categorias"] if c["nome"] == "Rx Masculino")
    assert len(rx["workouts"]) == 2
    nums_rx = sorted(
        a["numero"]
        for b in rx["baterias"]
        for a in b["alocacoes"]
    )
    # 4 atletas Rx (601, 602, 603, 604)
    assert nums_rx == ["601", "602", "603", "604"]

    # Bateria mista: filtragem por faixa funciona — Scaled NÃO leva atletas RX
    scaled = next(c for c in dia["categorias"] if c["nome"] == "Scaled Masculino")
    nums_scaled = sorted(
        a["numero"]
        for b in scaled["baterias"]
        for a in b["alocacoes"]
    )
    assert nums_scaled == ["901", "902"]   # só os 2 da faixa Scaled

    # Roster
    assert len(result["roster"]) == 6
    nums_roster = {a["numero"] for a in result["roster"]}
    assert nums_roster == {"601", "602", "603", "604", "901", "902"}


# ── #2: geração de ZIP via _handle_generate ───────────────────────────────────
def test_handle_generate_produz_zip_com_html_por_workout(xlsx_grades_e_dias_bytes,
                                                          fonts_empty):
    """Replica internamente o que _handle_generate faz, sem subir HTTP server."""
    from campo_generator import render_workout_combined, sanitize
    from parsers import assign_workout_numbers
    from ai_rounds import enriquecer_workouts

    result = parse_excel(xlsx_grades_e_dias_bytes)
    dia = result["dias"][0]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cat in dia["categorias"]:
            workouts = cat["workouts"]
            assign_workout_numbers(workouts)
            enriquecer_workouts(workouts)
            for wkt_pos, wkt in enumerate(workouts, start=1):
                # Junta atletas de baterias que rodam esse workout
                atletas = []
                for b in cat["baterias"]:
                    if (b.get("workouts_que_rodam") or []) and wkt_pos not in b["workouts_que_rodam"]:
                        continue
                    for a in b.get("alocacoes", []):
                        atletas.append({
                            "nome": a["nome"], "box": a["box"], "raia": a["raia"],
                            "bateria": b["numero"], "numero": a["numero"],
                        })
                if not atletas:
                    continue
                html = render_workout_combined(
                    {"nome": "TESTE", "categoria": cat["nome"], "data": "Sábado"},
                    wkt, fonts_empty, "", "", atletas,
                )
                caminho = f"Sábado/{sanitize(cat['nome'])}/{wkt_pos:02d}_{sanitize(wkt['nome'])}.html"
                zf.writestr(caminho, html.encode("utf-8"))

    zip_bytes = buf.getvalue()
    assert len(zip_bytes) > 0
    # Confere conteúdo do zip
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        nomes = zf.namelist()
        # Pelo menos 1 arquivo por categoria × workout que tem atletas
        assert any("Rx_Masculino" in n and "TWENTIES" in n for n in nomes)
        # Lê 1 e confere que tem nome de atleta
        rx_wkt1 = [n for n in nomes if "Rx_Masculino" in n and n.endswith(".html")][0]
        html = zf.read(rx_wkt1).decode("utf-8")
        assert "ATLETA RX 1" in html


# ── #3: render Express com 2 fórmulas ─────────────────────────────────────────
def test_render_workout_express_emite_amrap_e_for_time(workout_express, evento_basico,
                                                        fonts_empty):
    html = render_workout(evento_basico, workout_express, fonts_empty,
                          logo_src="", logo_evento="")
    # Header tem ambos os números
    assert ">1<" in html and ">2<" in html
    # Tem badge Express + ambas as fórmulas
    assert "Express" in html
    assert "Fórmula 1" in html or "F&#243;rmula 1" in html or "AMRAP" in html
    assert "Fórmula 2" in html or "F&#243;rmula 2" in html or "For Time" in html
    # Movimentos da F1 e F2 aparecem
    assert "HANDSTAND PUSH-UPS" in html
    assert "DEADLIFTS" in html
    assert "DOUBLE UNDERS" in html


# ── #4: validar_evento detecta problemas reais ────────────────────────────────
def test_validar_evento_detecta_workout_sem_movimentos_e_competidor_duplicado():
    config = {
        "dias": [{
            "label": "Sexta",
            "categorias": [{
                "nome": "Rx Masculino",
                "workouts": [
                    {"nome": "VAZIO", "tipo": "for_time", "movimentos": []},
                    {"nome": "OK", "tipo": "for_time", "time_cap": "9 min",
                     "movimentos": [{"nome": "PULL-UPS", "reps": 10}, {"chegada": True}]},
                ],
                "baterias": [
                    {"numero": "1", "codigo_evento": "#1", "horario_aquecimento": "07:00",
                     "horario_fila": "07:20", "workouts_que_rodam": [2],
                     "alocacoes": [
                         {"raia": "1", "numero": "601", "nome": "Foo", "box": "X"},
                     ]},
                    {"numero": "2", "codigo_evento": "#1", "horario_aquecimento": "07:30",
                     "horario_fila": "07:50", "workouts_que_rodam": [2],
                     "alocacoes": [
                         # Mesmo número do atleta acima — duplicado
                         {"raia": "2", "numero": "601", "nome": "Foo", "box": "X"},
                     ]},
                ],
            }],
        }],
    }
    avisos = validar_evento(config)
    # Procura aviso por workout vazio
    assert any("VAZIO" in a["msg"] and "sem movimentos" in a["msg"].lower()
               for a in avisos), f"esperava aviso de workout vazio, got: {avisos}"
    # Procura aviso por competidor duplicado
    assert any("601" in a["msg"] and "2 lugares" in a["msg"] for a in avisos)


# ── #5: validar_evento detecta time cap ausente em For Time ───────────────────
def test_validar_evento_detecta_for_time_sem_time_cap():
    config = {
        "dias": [{
            "label": "Sábado",
            "categorias": [{
                "nome": "Rx",
                "workouts": [
                    {"nome": "SEM TC", "tipo": "for_time", "time_cap": "",
                     "movimentos": [{"nome": "PULL-UPS", "reps": 10}, {"chegada": True}]},
                ],
                "baterias": [],
            }],
        }],
    }
    avisos = validar_evento(config)
    assert any("SEM TC" in a["msg"] and "time cap" in a["msg"].lower()
               for a in avisos)
