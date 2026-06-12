# Guia de escrita do Excel — Súmulas Digital Score

Objetivo: dar ao organizador um padrão claro pra preencher o Excel de programação do evento de modo que o sistema gere as súmulas corretamente, **sem ajustes de código entre eventos**.

Cada seção abaixo descreve uma aba do Excel + as convenções que o parser do sistema espera. No fim tem um **checklist de envio** — bate antes de mandar o arquivo.

---

## 1. Aba `Inscritos`

Lista de categorias do evento + faixa de número de cada uma + se é modalidade individual ou em grupo.

### Estrutura

| Nome | Max. Insc. | Qnt. Pago | Nº. Inicial | Nº. Final | Individual |
|------|-----------|-----------|-------------|-----------|------------|
| Rx Masculino | 20 | 17 | 101 | 199 | Sim |
| Rx Feminino | 15 | 13 | 201 | 299 | Sim |
| Dupla Rx Masculino | 20 | 11 | 101 | 199 | Não |

### Regras

- **`Nome`**: nome exato da categoria. **Deve ser idêntico** ao usado nas abas de Workouts e cronograma. Não usar abreviação aqui e nome completo lá.
- **`Nº. Inicial` / `Nº. Final`**: faixa contígua de números. Atletas dessa categoria recebem números dentro dessa faixa.
- **`Individual`**: `Sim` ou `Não`. **Obrigatório quando houver Individuais e Duplas no mesmo evento** com faixas que colidem (ex: Rx Masculino e Dupla Rx Masculino usando 101-199). Sem essa coluna, o sistema não consegue separar Individual de Dupla com mesma faixa.
- **Múltiplos blocos**: pra eventos com Individuais E Duplas, pode usar 2 blocos separados por linha vazia, cada um com seu cabeçalho — o parser entende.

### Erros comuns

- ❌ `Nome` da categoria diferente entre `Inscritos` e cronograma. → Sistema pode descartar a categoria silenciosamente.
- ❌ Faixas sobrepostas SEM coluna `Individual`. → Atletas ficam sem categoria definida no roster.
- ❌ Nº inicial > Nº final. → Linha ignorada.

---

## 2. Abas `Workouts - <Modalidade>` (grade dos workouts)

Para eventos com múltiplas modalidades (Individuais + Duplas), use abas separadas:

- `Workouts - Individuais`
- `Workouts - Duplas`
- `Workouts - Trios` (etc., se houver)

Para eventos só com uma modalidade, pode ser apenas `Workouts`.

### Estrutura

- **Linha 1**: nomes das categorias, uma por coluna. Ordem livre.
- **Linha 2+**: cada coluna é o texto livre completo do workout daquela categoria. Linhas vazias entre workouts separam um do outro.

### Cada célula de workout deve conter, na ordem:

1. **Nome** entre aspas duplas: `"Vinte Seis"`
2. Linha em branco
3. **Tipo + diretrizes** (`For time:`, `AMRAP em X minutes:`, `For load`, `Express Formula`)
4. **Movimentos** — um por linha, formato `N <movimento> [(carga)]`
5. Linha em branco
6. **Time cap** quando aplica: `Time cap: 9 minutes`
7. Opcionalmente, abaixo: `─── NOTAS ───` + regulamento textual (não interfere no parse)

### Exemplo — For Time simples

```
"Vinte Seis"

For time:
26 Burpees Over-the-Bar
26 Hang Cleans (115lb)
26 Thrusters (115lb)

Time cap: 15 minutes
```

### Exemplo — For Time com Goal (Simple Dimension / Mind)

Goal libera a chegada — atleta acumula reps de UM movimento alvo ao longo do workout.

```
"Simple Dimension"

For time:
Part 1 (0:00–6:00)
30 Cal Air Bike
Max Snatches (115lb)

Time cap: 15 minutes

Goal: 60 Snatches + finishing rep (cross the line).
```

**A linha `Goal: N <movimento> + finishing rep` é OBRIGATÓRIA** pra o sistema detectar como For Time Goal e renderizar o banner GOAL + a caixa de acumulado. Sem `finishing rep` ou `cross the line`, sai como For Time normal.

### Exemplo — Composto (`"X" + "Y"`)

Dois workouts encadeados na mesma súmula com pontuações separadas.

```
"Barbells and Jump" + "Run In The Park"

"Barbells and Jump" (0:00-5:00)

For time:
Parte 1 (0:00–2:00)
15 Deadlifts (115lb)
10 Snatches (115lb)
Max Box Jump Over (60cm)

Goal: 45 Box Jump Over + finishing rep (cross the line).

Descanse um minuto, depois...

"Run In The Park" (6:00-9:00)
For time:
10 Snatches (135lb)
200m Run
10 Snatches (135lb)

Time cap: 9 minutes
```

**Regras do composto**:

- 1ª linha = nomes das duas fórmulas entre aspas, separadas por ` + `: `"X" + "Y"`
- Cada fórmula abre com seu nome novamente + janela `(min:seg-min:seg)`
- Cada fórmula tem seu próprio `For time:` / `AMRAP`
- Linha `Descanse um minuto, depois...` entre F1 e F2 (opcional, mas ajuda a leitura)
- `Time cap:` no final aplica ao workout inteiro
- Tipos suportados em F1/F2: `for_time`, `for_time_goal`, `amrap`

### Movimentos: convenções de escrita

- `<N> <Movimento>` → `15 Deadlifts`. N é número inicial.
- Carga entre parens: `15 Deadlifts (115lb)`. Aceita `lb` e `kg`.
- Distância colada à unidade: `200m Run`, `500m Row`, `5km Run`.
- Calorias: `30 Cal Air Bike`, `30/24 Cal Row` (gendered M/F).
- Descritor entre parens NO FIM é OK: `200m Run (dois atletas)`, `300m Sprint (um atleta)`.
- Para movimentos `Max` (sem rep total fixo, usado em For Time Goal): começa com `Max`: `Max Box Jump Over (60cm)`.

### Erros comuns

- ❌ Faltou linha em branco entre `For time:` e o primeiro movimento. → Parse pode confundir o tipo.
- ❌ Movimento sem número inicial: `Burpees over the bar`. → Ignorado. Sempre `N <movimento>`.
- ❌ `Goal: N X` sem `finishing rep` / `cross the line`. → Detectado como For Time normal, sem banner GOAL.
- ❌ Composto sem janela `(N:NN-N:NN)` na abertura de F2. → Parser não acha onde F2 começa, descarta o composto.

---

## 3. Aba `<Dia>` (cronograma de baterias)

Uma aba por dia do evento. Nome simples: `Sábado`, `Domingo`, `Sexta` (PT-BR ou EN).

### Estrutura

| Eventos | Categoria | Bateria | Arbitragem | Quantidade | Aquecimento | Duração Aquec. | Fila | Duração Fila | Horário | Cap | Transição |
|---------|-----------|---------|------------|-----------|-------------|----------------|------|--------------|---------|-----|-----------|
| `"Vinte Seis"` | `Rx Masculino (Single Heat)` | 1 | | 17 (17) | 06:50 | 00:40 | 07:15 | 00:15 | 07:30 | 00:15 | 00:10 |

### Regras

- **Coluna `Eventos`**: nome do workout em aspas. Pode estar vazia se a bateria roda o mesmo workout da linha anterior.
- **Coluna `Categoria`**: nome da categoria + descritor opcional entre parens.
  - Descritores aceitos: `(Single Heat)`, `(Heat 1)`, `(Heat 2)`, `(Final Heat)`. Removidos automaticamente pra match com Inscritos.
  - **Bateria mista** (várias categorias compartilhando horário): separar por ` & ` ou `, `:
    - `Rx Masculino (Heat 1) & Intermediario Masculino (Heat 2)`
    - `Dupla Iniciante Masculino, Dupla Iniciante Feminina & Dupla Iniciante Mista (Single Heat)`
- **`Bateria`**: número sequencial da bateria DO DIA, começando em 1. Em eventos multi-arena, cada arena tem sua numeração própria.
- **`Horário`**: horário oficial da bateria (formato `HH:MM`).

### Erros comuns

- ❌ Categoria no cronograma com nome diferente do `Inscritos` sem padrão consistente.
  - `Inscritos`: `Teen Intermediario 16-17 Masculino`
  - Cronograma: `16-17 Masculino`
  - **Funciona** se houver coluna `Individual` no Inscritos (sistema deduce pela faixa de número).
- ❌ Bateria mista com separador diferente de ` & ` ou `, `. → Pode descartar categoria.
- ❌ Falta do número da bateria. → Bateria ignorada.

---

## 4. Aba `<Dia> - Montagem` (alocação de atletas)

Lista os atletas alocados em cada bateria com raia + número + nome + box.

### Estrutura por bateria (4 linhas de cabeçalho + N atletas)

```
Linha 1: 07:30:00 | "Vinte Seis"
Linha 2: 1 | Rx Masculino (Single Heat)
Linha 3: Raia | Número | Nome | Box
Linha 4+: 1 | 101 | NOME DO ATLETA | NOME DO BOX
Linha N: 2 | 102 | OUTRO ATLETA | OUTRO BOX
... (até a próxima bateria, separada por linha vazia)
```

### Regras

- **Cabeçalho da bateria** (linha 2): número + nome da categoria, **idêntico ao cronograma**.
- **Categorias mistas com sub-blocos por raia**: quando categorias diferentes compartilham bateria, atribua **raias contíguas a cada uma**:
  - Raias 1-6: atletas Teen 14-15 Fem (números 1601-1606)
  - Raias 11-20: atletas Scaled Fem (números 6XX)
  - Sistema separa pela faixa de número do `Inscritos` automaticamente.
- **Raias vazias** (atletas faltando): pode deixar a célula em branco. Não atrapalha.
- **Atletas em "aguardando balizamento"** (categoria sem alocação prévia, balizamento sai do dia anterior): não preencha. O sistema preenche automaticamente do roster do dia, pulando essa restrição.

---

## 5. Aba `Atletas - <Dia>` (roster)

Lista de todos os atletas do dia (informativo, pra súmulas pré-evento e fallback de "aguardando balizamento").

### Estrutura

| Número | Nome | Box |
|--------|------|-----|
| 101 | MATHEUS POLACCHINI VIEIRA | STORM TANK |
| 102 | VICTOR HUGO LAVORENTE DE PAIVA | CROSSFIT CROMO |

- Sem header.
- 1 atleta por linha.
- Aceita o mesmo número aparecendo em dias diferentes (Individuais reusam números das Duplas comumente).

---

## 6. Cuidados gerais

- **Não misture línguas no mesmo workout**: PT-BR ou EN, consistente. Aceita ambas, mas usa convenções diferentes.
- **Aspas curvas (`"`, `"`) e retas (`"`)**: ambas funcionam, mas escolha uma e mantenha.
- **Caracteres especiais em parens**: `(8, 9 anos)` é OK — o sistema entende que vírgula dentro de parens é descritor, não separador.
- **Linhas vazias entre seções** ajudam a leitura do parser. Não use `\n\n\n` (3+ quebras seguidas) — pode confundir.

---

## 7. Checklist final antes de enviar

Antes de mandar o Excel pro Digital Score, confere:

- [ ] Aba `Inscritos` com todas categorias + coluna `Individual` se houver Duplas
- [ ] Nomes de categoria são IDÊNTICOS entre `Inscritos` + `Workouts - X` + cronograma
- [ ] Cada workout tem nome entre aspas + `For time:` / `AMRAP` + movimentos + Time cap
- [ ] Goal explícito com `finishing rep` ou `cross the line` quando for For Time Goal
- [ ] Composto na 1ª linha tem `"X" + "Y"` + cada F com janela `(min:seg-min:seg)`
- [ ] Cronograma com `Eventos`, `Categoria`, `Bateria`, `Horário` preenchidos
- [ ] Montagem com cabeçalho por bateria + Raia/Número/Nome/Box
- [ ] Roster `Atletas - <Dia>` completo
- [ ] Abrir o arquivo no sistema e conferir o "Diagnóstico do Import" (versão futura) — corrigir avisos antes da impressão

---

## Apêndice — Tipos de workout suportados

| Tipo | Detecção automática | Estrutura |
|------|--------------------|-----------|
| `for_time` | `For time:` na descrição | Movimentos + Time cap |
| `for_time_goal` | `Goal: N <mov> + finishing rep` | Movimentos + Time cap + alvo de reps acumuladas |
| `amrap` | `AMRAP em X minutes:` | Movimentos + janela de tempo |
| `express` | `Express Formula` | F1 AMRAP + F2 For Time |
| `for_load` | `For load` / `Max lift` | Tentativas + carga progressiva |
| `composto` | `"X" + "Y"` na 1ª linha | F1 + F2, cada um com tipo próprio |

Pra eventos que tragam um padrão novo de workout (ex: relay, EMOM com tiebreak), conversar com o Digital Score ANTES de finalizar o Excel — pode exigir extensão do parser. Mas convenções de escrita acima cobrem a maioria dos formatos vistos em competições CrossFit BR/internacionais.
