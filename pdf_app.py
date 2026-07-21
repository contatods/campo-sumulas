#!/usr/bin/env python3
"""PDFs por Bateria — app de janela nativa (Digital Score).

Mesma interface e mesmo motor do pdf_gui.py, mas exibidos numa janela do
sistema (WKWebView no macOS, WebView2 no Windows) em vez do navegador.
É este arquivo que o PyInstaller empacota como "Digital Score PDFs.app"
(Mac) / .exe (Windows) — ver build_app.py.

Variável de ambiente PDF_APP_NOGUI=1 roda só o servidor (smoke test do
bundle na esteira de build, sem abrir janela).
"""

import os
import sys
import threading

# Congelado (PyInstaller), os módulos do repo já vêm no bundle; rodando do
# fonte, garante o import a partir da pasta deste arquivo.
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_gui import criar_server, CHROME, VERSAO


def main():
    server = criar_server()
    if not server:
        # Porta ocupada em todas as tentativas — quase sempre é outra
        # instância do próprio app aberta. Avisa e sai.
        try:
            import webview
            webview.create_window(
                "PDFs por Bateria", html="<body style='font-family:sans-serif;"
                "background:#0a0a0a;color:#f4f1ea;padding:40px'>"
                "<h2>O app já está aberto?</h2><p>Nenhuma porta livre "
                "(8777–8797). Feche outras janelas do PDFs por Bateria "
                "e tente de novo.</p></body>", width=520, height=260)
            webview.start()
        except Exception:
            print("✗ nenhuma porta livre entre 8777 e 8797")
        sys.exit(1)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    if os.environ.get('PDF_APP_NOGUI'):
        # Modo smoke-test (CI): servidor no ar, sem janela.
        print(f"NOGUI ok: {url} | chrome={bool(CHROME)} | v{VERSAO}",
              flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    import webview
    webview.create_window(
        f"PDFs por Bateria — Digital Score v{VERSAO}", url,
        width=1040, height=840, min_size=(780, 620),
        background_color='#0a0a0a')
    webview.start()          # bloqueia até a janela fechar
    server.shutdown()


if __name__ == '__main__':
    main()
