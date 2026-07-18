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

## Fase 2 — IA como fallback/reparador ✅

Regex faz a 1ª passada (rápida, grátis). Quando o parse FALHA no
`validar_workout_schema`, o app chama o reparador de IA.

- `parsers.parse_workout_text_robusto`: regex → valida → (se falhar) reparador →
  **só adota o reparo se ele passar no schema** (nunca pior que a regex). O
  parser expõe `registrar_reparador(fn)` (injeção de dependência — `parsers.py`
  não importa IA/anthropic; segue testável sozinho).
- `ai_parser.reparar_workout_ia`: a IA devolve um JSON limpo (contrato estável),
  e `_ia_json_para_workout` (puro/testável) converte pro dict interno. **Cache
  por hash do texto** → re-importar é grátis e determinístico. A chamada da API
  fica isolada em `_chamar_reparo_ia` (fácil de mockar).
- `sumula_app`: registra o reparador no startup só quando `AI_ATIVO`.

Só workouts que a regex não deu conta chamam a IA (85%+ nunca tocam a API).
O conversor cobre for_time / for_time_goal / amrap e **AMRAP multi-janela**
(reaproveita o render do PWRD Loop). Formato novo desconhecido → a IA estrutura,
o schema valida, sem código novo.

## Fase 3 — IA confere a fidelidade da leitura ✅

Pega o que a Fase 2 não pega: workout que passa no schema mas foi lido ERRADO
(tipo/rounds/pontuação plausíveis mas incorretos — ex: "Workouts 05 & 06").

- Cada workout carrega o texto cru do Excel em `_raw` (anexado no import por
  `parse_workout_text_robusto`).
- `ai_parser.revisar_leitura_ia(config)`: dedupe por hash do `_raw` (o mesmo
  workout repete entre categorias), monta {texto_excel, parse (resumo
  estrutural)} e pede pra IA listar SÓ divergências reais (movimento
  faltando/sobrando, reps/carga, tipo, rounds, pontuação, time cap, chegada).
  1 chamada pro evento todo.
- Endpoint `/api/ai/revisar-leitura` + botão "🔍 Conferir leitura" no banner
  pós-import → mostra as divergências no mesmo modal de validação, ANTES de
  gerar as súmulas.

Fluxo completo de robustez: regex (grátis) → schema (pega falha estrutural) →
IA repara o que falhou (Fase 2) → IA confere fidelidade do resto no preview
(Fase 3). O corpus (Fase 1) trava regressão em cima de tudo.
