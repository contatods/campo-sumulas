# Roadmap 2.0 — Import blindado + robustez

Objetivo do 2.0: sair do "gera → testa → reporta → conserta" para um import que
**valida, mostra preview e revisa com IA** antes de gerar — sobre uma base mais
madura. Sem scoring digital nem novo backend (ficam pra um projeto próprio).

O marco **2.0** é atingido quando Fases 1+2+3 estiverem no ar sobre a Fase 4.
Até lá, cada entrega sobe como `1.x` incremental (com teste).

## Fase 1 — Linter determinístico

Estende `ai_rounds.validar_evento` (que já retorna `{severidade, msg, onde}`) e
os `avisos_import` do parser. Cada regra nasce de um problema real do Pwrd by
Coffee 2026 encontrado à mão:

| Regra | Origem (Pwrd) | Onde detectar |
|---|---|---|
| Categoria da grade sem nenhuma bateria (não gera) | Masters/Duplas sumindo | parser (sabe grade × baterias) |
| Colisão de bateria (número duplicado na arena / horário sobreposto) | bateria #72 | `validar_evento` (config) |
| Carga fora do rol de Equipamentos | dumbbell 16kg | `validar_evento` + `equipamento` |
| Carga faltando (mov de barra sem carga onde outras divisões têm) | Rocket Master F | `validar_evento` |
| Movimento não reconhecido / provável typo | "atlhetes" (Flex) | `validar_evento` + dict de movimentos |

Padronizar o shape dos avisos (hoje o parser usa `nivel`, o validador usa
`severidade`).

## Fase 2 — Preview antes de gerar

Grid das súmulas renderizadas no app **antes** do ZIP. O render já existe; é UI.
Deixa o organizador pegar erro visual (enunciado, escala, layout) sem baixar.

## Fase 3 — Review por IA embutida

Camada IA (usa `ANTHROPIC_API_KEY`, já suportada) pro que o linter determinístico
não pega: **escalonamento invertido** (Fat Bar 10kg no PWRD Loop), padrão de
movimento, sanidade de carga entre divisões. Estende o "explicar avisos" atual
para "revisar programação".

## Fase 4 — Robustez / polish

- Unificar movimentos: dict interno (43) → base canônica `canonical_v2` (108).
- Cobrir mais formatos/edge-cases de Excel; expandir testes.
- Performance da geração em eventos grandes.

## Histórico que pavimentou o 2.0 (v1.54–v1.59, Pwrd by Coffee 2026)

- v1.54 — import de programação sem montagem/roster (súmula em branco)
- v1.55 — match de categoria tolerante (gênero/ordem/±) + rounds por extenso
- v1.56 — For Load: janelas A/B/C, unidade kg, corte de NOTAS
- v1.57 — Stack Bad: buy-in de distância + bloco `then N rounds of`
- v1.58 — multi-pontuação (Muscle Swim + 3k vira composto)
- v1.59 — auditoria: dupla multi-pontuação + soma de complexes
