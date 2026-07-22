#!/usr/bin/env python3
"""Empacota o "Digital Score PDFs" como app de desktop (PyInstaller).

Usado localmente (Mac) e pela esteira do GitHub Actions (Mac + Windows):

    python3 build_app.py

Saída:
    macOS   → dist/Digital Score PDFs.app        (onedir/.app com ícone)
    Windows → dist/Digital Score PDFs.exe        (onefile)

Requisitos de build: pip install pyinstaller pywebview openpyxl
(o app final NÃO exige Python nem pip do usuário — só Chrome/Edge).
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
NOME = "Digital Score PDFs"


def versao():
    m = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]",
                  (AQUI / "sumula_app.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "dev"


def _fonte_icone():
    """app_icon.png (ícone composto, squircle) se existir; senão ds_logo.png."""
    ic = AQUI / "app_icon.png"
    return ic if ic.exists() else AQUI / "ds_logo.png"


def icone_mac():
    """fonte do ícone → build/ds.icns (sips + iconutil, nativos do macOS)."""
    icones = AQUI / "build" / "ds.iconset"
    shutil.rmtree(icones, ignore_errors=True)
    icones.mkdir(parents=True)
    for tam in (16, 32, 64, 128, 256, 512):
        for escala, sufixo in ((1, ""), (2, "@2x")):
            px = tam * escala
            subprocess.run(["sips", "-z", str(px), str(px),
                            str(_fonte_icone()), "--out",
                            str(icones / f"icon_{tam}x{tam}{sufixo}.png")],
                           capture_output=True, check=True)
    icns = AQUI / "build" / "ds.icns"
    subprocess.run(["iconutil", "-c", "icns", str(icones), "-o", str(icns)],
                   capture_output=True, check=True)
    return icns


def icone_win():
    """ds_logo.png → build/ds.ico (requer Pillow; sem ele, app sem ícone)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    ico = AQUI / "build" / "ds.ico"
    ico.parent.mkdir(exist_ok=True)
    Image.open(_fonte_icone()).save(
        ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ico


def main():
    v = versao()
    (AQUI / "VERSION.txt").write_text(v, encoding="utf-8")
    print(f"→ empacotando {NOME} v{v} ({sys.platform})")

    sep = ";" if sys.platform == "win32" else ":"
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed", "--name", NOME,
        "--add-data", f"fonts{sep}fonts",
        "--add-data", f"ds_logo.png{sep}.",
        "--add-data", f"VERSION.txt{sep}.",
        # importados em runtime (não estáticos) — PyInstaller não os vê sozinho
        "--hidden-import", "parsers",
        "--hidden-import", "types_ds",
        "--hidden-import", "movimentos",
        "--hidden-import", "openpyxl",
    ]
    if sys.platform == "win32":
        args.append("--onefile")            # 1 .exe pra distribuir
        ico = icone_win()
        if ico:
            args += ["--icon", str(ico)]
    elif sys.platform == "darwin":
        args += ["--icon", str(icone_mac()),
                 # bundle id estável (Gatekeeper/preferências)
                 "--osx-bundle-identifier", "br.com.digitalscore.pdfs"]
    args.append(str(AQUI / "pdf_app.py"))

    r = subprocess.run(args, cwd=AQUI)
    if r.returncode != 0:
        sys.exit("✗ PyInstaller falhou")
    destino = AQUI / "dist" / (f"{NOME}.app" if sys.platform == "darwin"
                               else f"{NOME}.exe")
    print(f"✓ pronto: {destino}")


if __name__ == "__main__":
    main()
