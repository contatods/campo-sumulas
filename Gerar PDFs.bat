@echo off
rem Gerar PDFs.bat — duplo clique: abre a interface local do gerador de
rem PDFs por bateria no navegador.  [Windows]
rem Requisitos: Python 3 (python.org, com "Add Python to PATH") e Google
rem Chrome ou Microsoft Edge (o Edge ja vem com o Windows).
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo X Python nao encontrado. Instale em https://python.org ^(marque
  echo   "Add Python to PATH" na instalacao^) e rode de novo.
  pause
  exit /b 1
)

%PY% pdf_gui.py
pause
