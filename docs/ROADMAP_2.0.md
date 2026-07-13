# Roadmap 2.0 — Import blindado + robustez

Objetivo do 2.0: sair do "gera → testa → reporta → conserta" para um import que
**valida, mostra preview e revisa com IA** antes de gerar — sobre uma base mais
madura. Sem scoring digital nem novo backend (ficam pra um projeto próprio).

> **✅ 2.0.0 LANÇADO.** Fases 1+2+3 no ar (v1.60→v1.66, cravado em v2.0.0). A
> Fase 4 vira melhoria contínua do 2.x, feita quando surgir necessidade real.

## Fase 1 — Linter determinístico ✅ (v1.60, v1.61, v1.63)

Estende `ai_rounds.validar_evento` (que já retorna `{severidade, msg, onde}`) e
os `avisos_import` do parser. Cada regra nasce de um problema real do Pwrd by
Coffee 2026 encontrado à mão:

| Regra | Origem (Pwrd) | Onde detectar |
|---|---|---|
| Categoria da grade sem nenhuma bateria (não gera) | Masters/Duplas sumindo | parser (sabe grade × baterias) |
| Colisão de bateria (número duplicado na arena / horário sobreposto) | bateria #72 | `validar_evento` (config) |
| Carga fora do rol de Equipamentos | dumbbell 16kg | `validar_evento` + `equipamento` |
| Carga faltando (mov de barra sem carga onde outras divisões têm) | Rocket Master F | `validar_evento` |
| Movimento não reconhecido (typo no NOME do movimento) | — | `validar_evento` + dict de movimentos |
| Typo em palavra-chave de anotação (`athletes`/`atletas`/`sync`/`reps`/`cal`) | "**atlhetes**" (Flex) — é o marcador de nº de atletas, NÃO um movimento | spell-check dirigido |

Padronizar o shape dos avisos (hoje o parser usa `nivel`, o validador usa
`severidade`).

## Fase 2 — Preview antes de gerar ✅ (v1.65)

Grid das súmulas renderizadas no app **antes** do ZIP (`render_grid` +
`/api/preview/grid` + botões "👁 Revisar dia/evento"). Fontes embutidas uma vez.

## Fase 3 — Review por IA embutida ✅ (v1.66)

`revisar_programacao_ia` + `/api/ai/revisar-programacao` + botão "🤖 Revisar
programação". Pega escalonamento invertido / sanidade cross-divisão. Foi ela que
surfou o bug de carga dupla (`70kg/50kg`), corrigido junto.

## Fase 4 — Robustez / polish (contínua, opcional)

Sem prazo — feita quando surgir necessidade. Notas de investigação:

- **Unificar movimentos (43 → canônico 141)**: é decisão de ARQUITETURA. O
  `canonical_v2` mora no produto Movimentos; o campo-sumulas roda no Render e
  não lê aquele arquivo em runtime. Exigiria vendorizar (copiar os nomes) +
  manter 2 cópias em sincronia. Adiado até valer o custo.
- **Regra "movimento não reconhecido"**: baixo valor / alto risco de falso-
  positivo — o evento é cheio de movimentos custom legítimos (Hay Bale Burpee
  etc.). A review por IA (Fase 3) já cobre esse tipo de coisa melhor.
- Cobrir mais formatos/edge-cases de Excel conforme aparecerem; performance.

## Histórico que pavimentou o 2.0 (v1.54–v1.59, Pwrd by Coffee 2026)

- v1.54 — import de programação sem montagem/roster (súmula em branco)
- v1.55 — match de categoria tolerante (gênero/ordem/±) + rounds por extenso
- v1.56 — For Load: janelas A/B/C, unidade kg, corte de NOTAS
- v1.57 — Stack Bad: buy-in de distância + bloco `then N rounds of`
- v1.58 — multi-pontuação (Muscle Swim + 3k vira composto)
- v1.59 — auditoria: dupla multi-pontuação + soma de complexes
