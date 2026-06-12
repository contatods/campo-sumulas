#!/bin/bash
# Gerar PDFs.command — duplo clique: abre a interface local do gerador de
# PDFs por bateria no navegador.  [macOS]
cd "$(dirname "$0")" || exit 1
python3 pdf_gui.py
