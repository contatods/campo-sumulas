#!/bin/bash
# CAMPO v7 — Gerador de Súmulas
# Duplo clique para abrir

cd "$(dirname "$0")"

clear
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   CAMPO v7 — Gerador de Súmulas"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⏳ Verificando dependências..."
pip3 install jinja2 pdfplumber openpyxl --quiet 2>/dev/null
echo "✓ Tudo pronto."
echo ""
echo "→ Abrindo no navegador em http://localhost:8765"
echo "→ Para encerrar: feche esta janela."
echo ""

python3 sumula_app.py
