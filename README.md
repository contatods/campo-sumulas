# Súmulas Digital Score

Gerador de súmulas impressas para eventos de CrossFit. Importa Excel do
organizador (workouts + cronograma + montagem + atletas) e gera ZIP de
HTMLs prontos pra imprimir (Ctrl+P → PDF).

## Rodar local

```bash
pip install -r requirements.txt
python3 sumula_app.py    # http://localhost:8765
```

Para ativar a IA (estimar rounds em AMRAP, sugerir time cap, validar evento,
chat assistente), crie um arquivo `.env` na raiz:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Sem chave, o sistema funciona normalmente — a IA fica desativada e cai em
fallbacks algorítmicos.

## Deploy

`render.yaml` configura o serviço no Render.com com auto-deploy em push pra
`main`. A var `ANTHROPIC_API_KEY` precisa ser definida via dashboard.

## Formatos de Excel suportados

O parser detecta automaticamente 4 formatos:

| Formato | Detecção | Quando usar |
|---|---|---|
| `evento_multidia` | aba `Workouts` + `<Dia>` + `<Dia> - Montagem` | Grade unificada com coluna de dia |
| `grades_por_modalidade` | abas grade tipo `Individuais`/`Duplas` + `<Dia>` + `<Dia> - Montagem` | Sun Challenge style: workouts separados por modalidade |
| `categoria_grid` (legacy) | 1 aba grade categoria × workout | Modelo simples sem dias |
| `template` (legacy) | aba `Evento` + `WKT 1`, `WKT 2`, ... | Modelo plano com 1 workout por aba |

A aba `Inscritos` (opcional) define faixas de número por categoria — usada
pra desambiguar atletas em baterias mistas (categoria A & B na mesma bateria).

## Tipos de workout

- **For Time** — tempo até completar, com time cap
- **AMRAP** — máximo de rounds em N minutos
- **Express** — AMRAP + For Time encadeados (2 fórmulas)
- **For Load** — maior carga em N tentativas (com régua de anilhas marcáveis)

## Comandos

```bash
python3 bump_version.py [patch|minor|major]   # incrementa versão
python3 -m pytest tests/                       # roda testes
```

Versão e regras de commit: ver `CLAUDE.md` (se existir) e mensagens recentes
de `git log`. Bump obrigatório antes de cada commit do código.

## Tecnologias

- Python 3.10+ stdlib (`http.server.ThreadingHTTPServer`) — sem Flask
- Jinja2 — templates com autoescape ligado
- openpyxl — parse Excel
- Anthropic SDK (opcional) — IA
- HTML/CSS/JS vanilla — sem framework, sem build step

Frontend é servido como arquivos estáticos (`static/index.html`, `app.css`,
`app.js`). Edits requerem restart do servidor pra rebuildar o cache.

## Sistema de versões

Schema do `localStorage` é versionado (`SCHEMA_VERSION`). Mudanças que quebram
estado salvo no navegador disparam migração automática (v2 → v3 → ...).

Não bumpar pra 2.0 sem mudança real de contrato externo (ZIP, JSON exportado,
API HTTP, formato do Excel suportado).
</content>
