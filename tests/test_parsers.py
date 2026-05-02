"""Parsers heurísticos: texto livre de workout e Excel do organizador."""
import sumula_app


def test_parse_workout_text_for_time_extrai_movimentos_e_time_cap():
    texto = (
        '"TWENTIES"\n'
        "For Time:\n"
        "20 Chest-to-Bar Pull-Ups\n"
        "20 Devil's Presses\n"
        "Time cap: 9 min"
    )
    wkt = sumula_app.parse_workout_text(texto, numero=1)
    assert wkt["nome"] == "TWENTIES"
    assert wkt["tipo"] == "for_time"
    assert wkt["time_cap"] == "9 min"
    nomes = [m.get("nome") for m in wkt["movimentos"] if m.get("nome")]
    assert "CHEST-TO-BAR PULL-UPS" in nomes
    # For Time fecha com chegada
    assert any(m.get("chegada") for m in wkt["movimentos"])


def test_parse_excel_modelo_retorna_estrutura_valida(modelo_xlsx_bytes):
    result = sumula_app.parse_excel(modelo_xlsx_bytes)
    assert isinstance(result, dict)
    # Modelo é formato simples (não-grade): tem evento + workouts no topo
    assert "workouts" in result
    assert isinstance(result["workouts"], list)
    assert len(result["workouts"]) >= 1
    # Cada workout deve ter no mínimo nome e tipo
    for w in result["workouts"]:
        assert "nome" in w
        assert "tipo" in w
        assert w["tipo"] in {"for_time", "amrap", "express"}
