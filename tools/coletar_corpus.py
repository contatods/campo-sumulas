#!/usr/bin/env python3
"""Coleta workouts REAIS de planilhas de eventos pro corpus de regressão.

Fase 1 do plano de robustez de leitura do Excel. Extrai das abas 'Workouts*'
as células multi-linha (o texto livre do workout), deduplica por hash e mescla
em tests/corpus/workouts_reais.json — sem sobrescrever o que já existe.

Uso:
    python3 tools/coletar_corpus.py <evento1.xlsx> [<evento2.xlsx> ...]
    python3 tools/coletar_corpus.py --tag pwrd <arquivo.xlsx>

Depois rode `pytest tests/test_corpus.py` pra ver se algum formato novo quebra
o schema. Quanto mais eventos entram, mais o parser é blindado contra regressão.
"""
import argparse
import hashlib
import json
import pathlib
import sys

import openpyxl

_CORPUS = pathlib.Path(__file__).parent.parent / "tests" / "corpus" / "workouts_reais.json"


def _h(txt: str) -> str:
    return hashlib.md5(txt.encode("utf-8")).hexdigest()[:8]


def coletar(xlsx: str, tag: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    achados = []
    for ws in wb.worksheets:
        if "workout" not in ws.title.lower():
            continue
        for row in ws.iter_rows(values_only=True):
            for c in row:
                if isinstance(c, str) and c.count("\n") >= 2 and len(c.strip()) > 40:
                    achados.append({"fonte": tag, "aba": ws.title, "texto": c.strip()})
    return achados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="+")
    ap.add_argument("--tag", default=None, help="rótulo da fonte (default: nome do arquivo)")
    args = ap.parse_args()

    corpus = json.loads(_CORPUS.read_text(encoding="utf-8")) if _CORPUS.exists() else []
    vistos = {_h(x["texto"]) for x in corpus}
    novos = 0
    for path in args.xlsx:
        tag = args.tag or pathlib.Path(path).stem.lower()
        for item in coletar(path, tag):
            if _h(item["texto"]) in vistos:
                continue
            vistos.add(_h(item["texto"]))
            corpus.append(item)
            novos += 1

    corpus.sort(key=lambda x: (x["fonte"], x["aba"], x["texto"][:40]))
    _CORPUS.write_text(json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"+{novos} workouts novos · corpus agora com {len(corpus)}")
    print("rode: pytest tests/test_corpus.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
