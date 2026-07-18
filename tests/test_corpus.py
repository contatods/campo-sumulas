"""Corpus de regressão: workouts REAIS de eventos passados (Monstar, exemplo).

Fase 1 do plano de robustez de leitura do Excel. A ideia: em vez de testar o
parser só com frases que EU invento (sintéticas), testar em cima da REALIDADE —
todos os workouts reais coletados das planilhas de eventos. Assim:
  - o parser não regride num formato que já funcionava;
  - novos formatos que ele lê errado aparecem AQUI (medível), não só quando o
    usuário testa em produção.

Alimenta o parser do mesmo jeito que a importação real: extrai a linha
'Arena:' antes de parsear (senão o Arena viraria o nome do workout).

Pra ampliar o corpus: rode as planilhas de novos eventos por
tools/coletar_corpus (ou cole os cells) e regrave workouts_reais.json.
"""
import json
import pathlib

from parsers import parse_workout_text, _extrair_arena, validar_workout_schema

_CORPUS_PATH = pathlib.Path(__file__).parent / "corpus" / "workouts_reais.json"
CORPUS = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def _parse(raw: str):
    _, texto = _extrair_arena(raw)
    return parse_workout_text(texto, 1)


def test_corpus_carregou():
    assert len(CORPUS) >= 100, "corpus encolheu — regravou errado?"


def test_corpus_parser_nao_crasha():
    """O parser não pode levantar exceção em NENHUM workout real."""
    for item in CORPUS:
        _parse(item["texto"])  # não deve levantar


def test_corpus_schema_sem_regressao():
    """Todo workout real satisfaz o schema canônico (validar_workout_schema).
    Se algum falhar, o parser regrediu ou um formato novo entrou sem suporte."""
    falhas = []
    for item in CORPUS:
        w = _parse(item["texto"])
        probs = validar_workout_schema(w, item["texto"])
        if probs:
            falhas.append((item["fonte"], item["aba"], w.get("nome"), probs))
    assert not falhas, (
        f"{len(falhas)} workout(s) real(is) com problema de schema:\n"
        + "\n".join(f"  {f[0]}/{f[1]} {f[2]!r}: {f[3]}" for f in falhas[:25])
    )
