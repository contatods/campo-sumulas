#!/usr/bin/env python3
"""bump_version.py — incrementa (ou imprime) VERSION em sumula_app.py.

Uso:
    python3 bump_version.py            # patch  (1.1.0 → 1.1.1)
    python3 bump_version.py patch      # idem
    python3 bump_version.py minor      # 1.1.0 → 1.2.0
    python3 bump_version.py major      # 1.1.0 → 2.0.0
    python3 bump_version.py show       # imprime versão atual sem alterar

Convenção:
    patch  — fix, refactor, polimento, ajuste pequeno
    minor  — feature visível ao usuário (ex: pacote UX inteiro)
    major  — mudança que quebra fluxo existente

Imprime a nova versão (ou a atual, em modo show) no stdout.
"""
import re
import sys
import pathlib

APP = pathlib.Path(__file__).parent / 'sumula_app.py'
PATTERN = r"^VERSION\s*=\s*['\"](\d+)\.(\d+)\.(\d+)['\"]"

src = APP.read_text()
m = re.search(PATTERN, src, re.M)
if not m:
    sys.exit(f"VERSION constant not found in {APP.name}")

maj, mi, pa = map(int, m.groups())
scope = (sys.argv[1] if len(sys.argv) > 1 else 'patch').lower()

if scope in ('show', '--show', 'current', '--current'):
    print(f"{maj}.{mi}.{pa}")
    sys.exit(0)

if scope == 'major':
    maj, mi, pa = maj + 1, 0, 0
elif scope == 'minor':
    mi, pa = mi + 1, 0
elif scope == 'patch':
    pa += 1
else:
    sys.exit(f"unknown scope: {scope!r}. Use patch | minor | major | show.")

new = f"{maj}.{mi}.{pa}"
new_src = re.sub(
    r"^VERSION\s*=\s*['\"][^'\"]+['\"]",
    f"VERSION = '{new}'",
    src,
    count=1,
    flags=re.M,
)
APP.write_text(new_src)
print(new)
