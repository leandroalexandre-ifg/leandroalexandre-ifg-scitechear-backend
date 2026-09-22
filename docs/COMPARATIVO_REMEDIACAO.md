# Remediação do sumarizador — filtro estrutural + `meeting_summary_v2`

**Data:** 22/09/2026 · **Branch:** `feat/filtro-estrutural-sumario` ·
**Modelo:** `qwen3:14b` (Ollama, `think=true`, `temperature=0`, `seed=42`,
`num_ctx=32768`) · **GPU:** RTX 5090 (GPU1; a GPU0 segue fora de operação).

Movimento 3 do trabalho sobre o sumarizador. Fecha o ciclo aberto pelo
[comparativo v4 × v6](COMPARATIVO_IMPLICITAS_V4_V6.md), que rastreou toda
premissa sem lastro das perguntas implícitas até o sumário e recomendou
sanear o insumo antes de decidir entre os prompts.

Artefatos brutos (transcrições, os oito sumários, respostas do modelo e o
script) em [`repro/remediacao-sumarizador/`](repro/remediacao-sumarizador/).

## Método

Nenhum áudio foi reprocessado: os `segments` vêm dos mesmos quatro resultados
reais do comparativo anterior. Duas condições por job, **uma única execução**:

| Condição | Sumarizador | Filtro estrutural |
|---|---|---|
| **baseline** | v1 | desligado |
| **corrigido** | **v2** | **ligado** |

Por transcrição rodaram 2 sumarizações (v1 e v2 — o prompt mudou, não dá para
reusar) e 4 extrações de implícitas (v4 e v6 × baseline e corrigido): 24
chamadas ao LLM.

**Teto declarado antes de rodar: 35 min. Consumido: 5 min 24 s.**

O baseline reproduziu o comparativo de 22/09 **número a número** (45 e 11) —
o harness é fiel e o determinismo se sustenta.

## As duas correções medidas

- **Filtro estrutural** (`app/services/summary_filter.py`): descarta as seções
  "Conhecimento implícito" e "Lacunas" e os elementos criados só para declarar
  ausência. Não toca em prompt algum — muda o **consumo** do sumário.
- **`meeting_summary_v2.txt`**: o v1 com duas edições e nada mais. O campo
  `Resumo` ganha descrição (era o único campo do schema sem nenhuma) e a regra
  de validação 20 proíbe deduzir, converter ou completar dado factual.

## Resultado quantitativo

| Job | Forma | v4 base | v4 corr | v6 base | v6 corr |
|---|---|---|---|---|---|
| `2e335c5c` | R5 — reunião Ana/Bruno | 15 | 15 | 4 | **3** |
| `00c2ff18` | Controle — ata sem questão aberta | 15 | **10** | 2 | **0** |
| `6150ce54` | Controle — conversa trivial | 0 | 0 | 0 | 0 |
| `50098d37` | Reunião acadêmica (RUFAS) | 15 | 15 | 5 | **7** |
| | **Total** | **45** | **40** | **11** | **10** |

## 1 · O "30 de outubro" acabou

| | v1 | v2 |
|---|---|---|
| `PE1` (Pendências) | "antes do prazo final **(30 de outubro)**" | "A validação do desempenho em uma reunião longa **ainda não foi realizada**." |
| "outubro" nos 4 sumários | 1 | **0** |
| Texto da pergunta gerada | "prazo estabelecido (30 de outubro)" | "cumprir **o prazo de 30 do mês**" |

As **seis** referências ao prazo no sumário v2 preservam a expressão relativa
("o dia 30 deste mês", "o prazo de 30 do mês"), que é exatamente o que a regra
20 manda. A correção atravessou o pipeline inteiro até o texto da pergunta.

O `PR1` (Prazos), que no v1 já estava correto, seguiu correto — a regra não
custou a informação que existia.

## 2 · Leitura manual do v6 corrigido (10 perguntas)

Mesmo critério do comparativo anterior: só vale se houver evidência textual na
transcrição de dúvida, incerteza, necessidade de decisão, problema ou
necessidade de validação.

### `2e335c5c` — R5 (3 perguntas)

| # | Veredito |
|---|---|
| I1 — redução do tempo da estação de perguntas, "quase metade do tempo total" | **Sustentada e limpa.** A expressão é literal da linha 14; linhas 15–16 sustentam a dúvida. **Sem a data inventada.** |
| I2 — critérios para validar desempenho em reunião longa, "prazo de 30 do mês" | **Sustentada e limpa.** Linha 9 sustenta a validação pendente; a data está como a linha 8 a registra. |
| I3 — impacto da redução de contexto sobre precisão e completude da transcrição | **Núcleo sustentado, extensão inferida.** Linha 16 é a dúvida real; ninguém afirmou que reduzir contexto afetaria a precisão da transcrição. |

A redundância do baseline (I1/I4, mesmo núcleo) **desapareceu**.

### `00c2ff18` — controle, ata sem questão aberta (0 perguntas)

**Correto.** O controle que devia dar zero agora dá zero. As duas perguntas do
baseline — a de premissa invertida e a da "data exata da reunião anterior" —
vinham ambas do sumário e sumiram com ele saneado.

### `6150ce54` — controle, conversa trivial (0 perguntas)

**Correto**, como no baseline.

### `50098d37` — RUFAS (7 perguntas)

| # | Veredito |
|---|---|
| I1 — lacuna de estudos sobre metano em novilhas | **Sustentada.** Linhas 32–36. |
| I2 — desafios da geração de datasets sintéticos | **Limítrofe.** Datasets são mencionados (linha 95); ninguém levantou dificuldade em gerá-los. |
| I3 — limites de não envolver geógrafos/químicos | **Sustentada — a melhor do corpus.** Linhas 89–92 são a dúvida; 93–94 a decisão explícita. |
| I4 — interface "intuitiva" para produtores com "diferentes níveis de familiaridade com tecnologias digitais" | **Não sustentada.** `intuitiv`, `familiaridade` e `digitais` aparecem **0 vezes** na transcrição. É conhecimento geral sobre produtores rurais — o que o próprio v6 proíbe. |
| I5 — dependência de dados do produtor, "conforme o PDF da base do Farmer" | **Não sustentada.** A linha 107 existe e é puramente descritiva. Converte informação apresentada em pergunta, que o v6 proíbe literalmente. |
| I6 — implicações de priorizar a ferramenta em vez de especialistas | **Redundante com I3** — mesmo núcleo. |
| I7 — como validar a hipótese de que a GUI permite decisões mais precisas | **Inferida.** A premissa tem lastro (linhas 36 e 101); a necessidade de validá-la não foi levantada por ninguém. |

### Placar

| Categoria | Baseline (11) | Corrigido (10) |
|---|---|---|
| Sustentadas e limpas | 4 | **4** |
| **Fato alucinado** | **1** | **0** |
| Redundantes entre si | 2 | **1** |
| Não sustentadas | 3 | **2** |
| Limítrofes / inferidas | 1 | 3 |

## 3 · O que era do insumo e o que é do prompt

**Os cinco defeitos rastreados até o sumário desapareceram todos:** o "30 de
outubro", as duas perguntas da ata, a dependência GUI↔datasets e a "falta de
prazos definidos". Mais a redundância do R5.

**Os três que restam são todos do prompt v6, e todos no mesmo job:** RUFAS I4
(conhecimento geral), I5 (informação apresentada virando pergunta) e I6
(redundância). Nenhum é alcançável por filtro nem por prompt de sumarização —
a matéria-prima deles está corretamente registrada no sumário saneado.

É a resposta que o comparativo anterior não podia dar: **o insumo respondia
por 5 dos 8 defeitos duros do v6.** O que sobra é a taxa própria do prompt.

## 4 · Os sumários não empobreceram

Era o risco declarado antes de rodar: que o v2 preservasse "antes desta data"
onde o v1 escrevia algo mais informativo. **Não aconteceu.**

| Job | Chars v1 → v2 | Elementos |
|---|---|---|
| `2e335c5c` | 8024 → 7711 (−4%) | 20 → 19 |
| `00c2ff18` | 4650 → **7156 (+54%)** | 13 → 15 |
| `6150ce54` | 2193 → **3538 (+61%)** | 0 → 7 |
| `50098d37` | 8942 → 8640 (−3%) | 28 → 27 |
| | | **61 → 68** |

O `PE1` é o caso exemplar: trocou uma data inventada por uma afirmação fiel,
sem perder informação.

**Um efeito a registrar.** O `6150ce54` (conversa trivial) saiu de 0 elementos
para 7. Lidos um a um, são fatos fiéis ("Daniel gosta de jogar Roblox",
"Daniel foi para a escola hoje") — não invenções; o v1 simplesmente recusava
extrair. **Hipótese, não causa provada:** dar descrição a um campo que antes
era só a palavra `Resumo` pode ter tornado o modelo mais disposto a
preenchê-lo. O controle não foi prejudicado — as implícitas seguiram em 0 nos
dois prompts.

## Dois achados colaterais

- **O v2 mudou a renderização dos cabeçalhos** — as categorias passaram a
  terminar em dois-pontos. O filtro estrutural atravessou isso sem erro nos
  quatro sumários v2, porque casa por nome com pontuação normalizada. Foi
  robustez de desenho, não previsão; fica como caso de regressão.
- **O teto do v4 não é contaminação.** Mesmo com insumo limpo o v4 seguiu em
  15 no R5 e no RUFAS; só a ata cedeu (15 → 10). Tratar o teto como meta é
  comportamento do prompt v4 e independe do insumo.

## Conclusão

As duas correções fazem o que foram desenhadas para fazer, e nenhuma custou o
que se temia. A confabulação herdada do sumarizador acabou; a residual do v6 é
dele.

Sobre **v4 × v6**, a recomendação de 22/09 se mantém por um motivo diferente:
o v6 continua melhor em tudo que se mede (10 contra 40, controles corretos,
mais rápido) e sua confabulação residual agora é comprovadamente própria. Não
há mais insumo para limpar — o que sobrar exige mexer no v6 ou aceitar a taxa.

Sobre o **default do `meeting_summary_v2`**, nada foi decidido: quatro jobs
não bastam para promover um prompt que muda a saída do LLM em toda reunião.
Fica registrado como pendência em aberto, para revisitar com volume real do
piloto. Ver [`PENDENCIAS.md`](PENDENCIAS.md).

**Nenhum default foi alterado por este trabalho.** `MEETING_SUMMARY_PROMPT_VERSION`
segue `v1`, `IMPLICIT_QUESTIONS_PROMPT_VERSION` segue `v4` e
`ENABLE_IMPLICIT_QUESTIONS` segue `false`. A única mudança ligada por padrão é
`ENABLE_SUMMARY_FILTER=true`, inerte enquanto a etapa de implícitas estiver
desligada.
