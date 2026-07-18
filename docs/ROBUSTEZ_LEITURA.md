# Robustez da leitura dos workouts do Excel

Cada evento novo expunha um formato que o parser lia errado (Muscle Swim,
Muscle Coffee, Rocket, Stack Bad, chegada, PWRD Loop…). Diagnóstico: a célula
do Excel é **texto livre em linguagem natural** com variação infinita, e regex
sozinho nunca cobre tudo — vira "acha bug → escreve regex" pra sempre.

Plano **faseado** (escolhido pelo usuário): começar pelo que é grátis e
determinístico (corpus + schema), depois ligar a IA como fallback.

## Fase 1 — Corpus real + schema canônico ✅ (em andamento)

- **Corpus de workouts reais** (`tests/corpus/workouts_reais.json`): workouts
  extraídos das planilhas de eventos passados (hoje: Monstar + exemplo, 109
  workouts). Testar em cima da REALIDADE, não de frases sintéticas.
  - Crescer com: `python3 tools/coletar_corpus.py <evento.xlsx>` (dedup por hash).
- **Schema canônico** (`parsers.validar_workout_schema`): invariantes que todo
  parse deve satisfazer (tipo válido, tem conteúdo, nome não é 'Arena:',
  pontuação Max/Goal não pode ser dropada, time cap capturado). Reutilizável
  pelo linter de import.
- **Teste de regressão** (`tests/test_corpus.py`): parseia os 109 e valida o
  schema. Parser não pode crashar nem regredir num formato que já funcionava.
- **Bugs que o corpus já achou e corrigimos**: time cap `12:30 minutes` (mm:ss)
  e time cap no fim do texto (depois de Note/Score) — ~15% dos workouts.

Gaps conhecidos (formatos complexos ainda não modelados por completo, passam no
schema básico mas merecem revisão): "Workouts 05 & 06" (3 partes A/B/C com
AMRAP+For-time e pontuação dupla).

## Fase 2 — IA como fallback/reparador (próxima)

Regex faz a 1ª passada (rápida, grátis). O que falhar no `validar_workout_schema`
ou tiver baixa confiança vai pra IA (haiku/sonnet), que devolve o schema
canônico. **Cache por hash do texto** → re-importar é grátis e determinístico.
Formato novo não precisa de código novo: a IA lê, o linter valida, o preview
mostra antes de imprimir as súmulas.

## Fase 3 — IA valida sempre + preview

A revisão por IA compara "o que parseei" vs "o texto cru" e sinaliza divergências
no preview, pra pegar leitura errada ANTES de gerar 300 súmulas.
