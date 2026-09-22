# Comparativo v4 × v6 — perguntas implícitas

**Data:** 22/09/2026 · **Branch:** `feat/perguntas-implicitas-v6` ·
**Modelo:** `qwen3:14b` (Ollama, `think=true`, `temperature=0`, `seed=42`,
`num_ctx=32768`) · **GPU:** RTX 5090 (GPU1; a GPU0 segue fora de operação).

Fase 3 do trabalho do prompt v6. O v6 abandona a saída JSON e o campo
`linhas_evidencia`, então a validação programática anti-confabulação do v4 não
tem insumo nesse caminho — **esta leitura manual é o que a substitui**, e foi
feita pergunta por pergunta contra a transcrição original, não contra a
sumarização.

Artefatos brutos (transcrições renderizadas, sumarizações, respostas do modelo
e o script que rodou) em [`repro/implicitas-v4-v6/`](repro/implicitas-v4-v6/).

## Método

Nenhum áudio foi reprocessado: os `segments` vêm de resultados reais já
gravados. Por transcrição rodou **uma** sumarização, reusada pelos dois
prompts, de modo que a única variável entre v4 e v6 é o prompt. Um job por vez
(placa compartilhada).

**Teto declarado antes de rodar: 30 min.** Consumido: **2 min 35 s** — bem
abaixo da estimativa de ~11 min, porque o modelo já estava carregado e as
transcrições são menores do que o pior caso previsto.

O corpus usa `6150ce54` no lugar da transcrição do carro, que não existe mais.
**É equivalente em forma** — conversa trivial real, sem conteúdo de projeto —
**não a mesma entrada** que expôs a confabulação do v3.

## Resultado quantitativo

| Job | Forma | Segs | Áudio | v4 | v6 | Sumarização | v4 (s) | v6 (s) |
|---|---|---|---|---|---|---|---|---|
| `2e335c5c` | R5 — reunião Ana/Bruno | 18 | 80 s | **15** | **4** | 29,2 s | 13,8 | 9,7 |
| `00c2ff18` | Controle — ata sem questão aberta | 10 | 39 s | **15** | **2** | 15,6 s | 11,3 | 8,9 |
| `6150ce54` | Controle — conversa trivial | 21 | 56 s | **0** | **0** | 10,7 s | 3,6 | 2,6 |
| `50098d37` | Reunião acadêmica (RUFAS) | 117 | 737 s | **15** | **5** | 29,8 s | 13,2 | 7,0 |
| | **Total** | | | **45** | **11** | | | |

Dois fatos que salta aos olhos antes de qualquer leitura de conteúdo:

- **O v4 bateu exatamente 15 em três dos quatro jobs**, inclusive na ata de
  alinhamento que não tem uma única questão aberta. O teto está sendo tratado
  como meta — foi justamente o que a reformulação do v4 tentou corrigir por
  texto de prompt, e não corrigiu.
- **O v6 nunca se aproximou do teto** (4, 2, 0, 5). A quantidade passou a
  variar com o material, que é o comportamento pedido. O aviso de "acima de
  15" nunca disparou.

O v6 também é mais rápido (menos tokens de saída): 7,0 s contra 13,2 s na
reunião de 12 min.

**O sentinela funcionou com o modelo real, não só em fixture:** na conversa
trivial o v6 devolveu literalmente `Não possui`, e o parser converteu em zero
perguntas sem erro. O v4, no mesmo caso, devolveu `{"perguntas_implicitas": [],
"total_perguntas": 0}`. Os dois controles de confabulação passaram.

## Leitura manual — v6, pergunta por pergunta

Critério aplicado (é o do próprio prompt v6): só vale se houver **evidência
textual na transcrição** de que os participantes demonstraram dúvida,
incerteza, necessidade de decisão, problema ou necessidade de validação sobre
aquela questão.

### `2e335c5c` — R5 (4 perguntas)

| # | Pergunta | Veredito |
|---|---|---|
| I1 | Como a alta duração do processamento da estação de perguntas (7 segundos) pode ser mitigada para garantir a entrega dentro do prazo estabelecido **(30 de outubro)**? | **Núcleo sustentado, detalhe factual alucinado.** Linhas 14–16 sustentam o problema e a dúvida ("Precisamos avaliar se vale a pena reduzir o tamanho do contexto"). Mas **a transcrição diz "o dia 30 deste mês" (linha 8); "outubro" não aparece em lugar nenhum.** |
| I2 | Quais critérios serão utilizados para validar o desempenho do sistema em uma reunião longa antes do prazo final? | **Sustentada.** Linha 9: "Ainda precisamos validar o desempenho em uma reunião longa antes desta data" — necessidade explícita, critério nunca definido. |
| I3 | Qual será o impacto da redução do tamanho do contexto nas requisições sobre a eficiência geral do sistema? | **Sustentada.** Linha 16 é literalmente a dúvida em aberto. |
| I4 | Como a análise do tempo de processamento (7 segundos) será integrada à avaliação de estratégias de otimização para evitar atrasos no cumprimento do prazo? | **Sustentada, mas redundante com I1** — mesmo núcleo central (reduzir o tempo da etapa de perguntas a tempo do prazo). Viola a regra anti-redundância do próprio v6. |

**O "30 de outubro" repete no v6.** Era a pergunta direta, e a resposta é sim.

### `00c2ff18` — controle, ata sem questão aberta (2 perguntas)

Esperado: `Não possui`. A ata só registra andamento; ninguém expressa dúvida,
problema ou decisão pendente.

| # | Pergunta | Veredito |
|---|---|---|
| I1 | Como será garantida a validação das novas datas do cronograma pela coordenação, considerando que a atualização depende desse alinhamento? | **Não sustentada — inverte o fato.** A linha 8 diz que as datas **já foram acordadas** na reunião anterior com a coordenação. Não há validação pendente. |
| I2 | Qual será a data exata da reunião anterior com a coordenação? | **Não sustentada.** É uma lacuna de metadado que ninguém levantou. O próprio v6 proíbe: "A presença de uma informação... não constitui, por si só, uma pergunta implícita." |

### `6150ce54` — controle, conversa trivial (0 perguntas)

**Correto.** `Não possui`. Nada a verificar.

### `50098d37` — reunião acadêmica RUFAS (5 perguntas)

| # | Pergunta | Veredito |
|---|---|---|
| I1 | Como a ausência de estudos sobre emissões de metano em novilhas e subprodutos pode impactar a precisão e a utilidade do Rufas? | **Sustentada.** Linhas 32–36 declaram a lacuna, dizem que "não é muito bem medido" e que "é importante simular essa variável". |
| I2 | Quais são as implicações da decisão de não envolver especialistas de outras áreas (geógrafos, químicos)? | **Sustentada — a melhor das 11.** Linhas 89–92 são a dúvida levantada por uma participante; 93–94 são a decisão explícita ("Nesse momento agora, não"). |
| I3 | Como a geração de datasets sintéticos será validada para garantir representação fiel dos dados reais? | **Inferida, limítrofe.** Datasets sintéticos são mencionados (linha 95), mas ninguém levantou validação deles. Pelo "em caso de dúvida, não gere", não devia existir. |
| I4 | Quais são os riscos da dependência da interface gráfica em relação à geração de datasets sintéticos, considerando a falta de prazos definidos? | **Não sustentada.** Essa dependência **não está na transcrição** — GUI e datasets aparecem como frentes paralelas. E "falta de prazos" é ausência percebida, que o prompt proíbe como fundamento. |
| I5 | Como a falta de estudos sobre metano em novilhas pode limitar a capacidade do Rufas de simular variáveis críticas? | **Redundante com I1** — mesmo núcleo semântico, reformulado. |

### Placar da leitura manual (v6, 11 perguntas)

| Categoria | Qtd |
|---|---|
| Genuinamente sustentadas e limpas | **4** (R5 I2, I3; RUFAS I1, I2) |
| Núcleo sustentado, detalhe factual alucinado | **1** (R5 I1 — "30 de outubro") |
| Redundante com outra da mesma lista | **2** (R5 I4; RUFAS I5) |
| Não sustentadas (premissa invertida ou inferida) | **3** (ata I1, I2; RUFAS I4) |
| Limítrofe / inferida | **1** (RUFAS I3) |

## Leitura do v4, para comparar

Não vale a pena tabelar 45 perguntas; o padrão é homogêneo e está nos
artefatos brutos. O que importa:

- **R5 (15):** o mesmo "30 de outubro" aparece em I2 e I7. As 15 colapsam em
  ~5 núcleos distintos — cinco perguntas só sobre redução de contexto
  (critérios, eficácia, impacto, alternativas, impacto na transcrição), três
  sobre validação antes do prazo, duas sobre consequência dos 7 s.
- **Ata (15):** o caso mais grave do comparativo. Numa reunião sem uma única
  questão aberta, **as 15 são construções** ("riscos associados à ambiguidade
  do prazo 'até o final desta semana'" — ninguém levantou ambiguidade nenhuma).
  Todas passaram pela validação de evidência porque **ancoraram em linhas que
  existem**. Isso expõe o limite do mecanismo do v4: ele valida *ancoragem*,
  não *sustentação*. Uma pergunta inventada que cita uma linha real passa.
- **RUFAS (15):** I1 e I6 são boas (as mesmas que o v6 acertou). O resto
  mistura pares redundantes (I3/I13, I2/I5, I7/I15) e conversão de informação
  apresentada em pergunta (I8, I14).

## O achado que muda o diagnóstico

**A confabulação que sobra no v6 não nasce no v6. Nasce na sumarização.**

Cada premissa sem lastro que o v6 produziu já está afirmada no sumário, e o
v6 apenas a leu com fidelidade:

| Premissa sem lastro na transcrição | Onde ela já estava |
|---|---|
| "prazo estabelecido (30 de outubro)" | `2e335c5c_sumario.txt:52` — "Validação do desempenho em uma reunião longa antes do prazo final **(30 de outubro)**". O mesmo sumário cita corretamente "o dia 30 deste mês" nas linhas 73–74. Ele se contradiz internamente. |
| "a atualização depende da validação das novas datas pela coordenação" | `00c2ff18_sumario.txt:101` — e as linhas 109 e 127 do **mesmo** sumário dizem o contrário ("A coordenação já validou as novas datas"). |
| "a data exata da reunião anterior" | `00c2ff18_sumario.txt:135` — "Não há menção à data exata da reunião anterior". O sumário tem uma seção que **enumera ausências**. |
| "a interface gráfica depende da geração de datasets sintéticos" | `50098d37_sumario.txt:146`, sob um cabeçalho literalmente chamado **"Dependências implícitas"**. |
| "falta de prazos definidos" | `50098d37_sumario.txt:58` — "Não há prazo explícito mencionado para as tarefas". |

Ou seja: `meeting_summary_v1.txt` (a) inventa fato ("30 de outubro"),
(b) afirma dependências que ele mesmo rotula de implícitas e (c) enumera
ausências. O prompt de implícitas — v4 ou v6 — recebe isso como insumo e o
converte em pergunta. O v6 *manda* não fazer isso ("Não transforme
automaticamente as categorias ou elementos da sumarização em perguntas. Gere
perguntas somente quando houver sustentação na transcrição original"), e o
modelo não obedece.

Duas consequências práticas:

1. **Nenhuma versão do prompt de implícitas pode consertar isso**, e nenhum
   parser também: a informação errada chega pronta. Mexer no v6 seria mexer no
   lugar errado.
2. A montagem D2-b (transcrição logo após o banner, sumário por último) **não
   foi suficiente** para o modelo preferir a transcrição ao sumário em caso de
   conflito. Reduzir a influência do sumário é um experimento próprio — na
   direção de sanear o sumarizador, não de reescrever o v6 de novo.

## Conclusão

O v6 é **melhor que o v4 em tudo que se mediu**: 11 perguntas contra 45, sem
chegar perto do teto, com menos redundância, mais rápido, e acertando os dois
controles. As duas melhores perguntas do corpus inteiro são dele.

Mas ele **não está pronto para virar default**, por dois motivos distintos:

- **Um que é dele:** 3 das 11 não têm sustentação e 2 são redundantes entre si
  — 45% da saída. É muito melhor que o v4, e ainda é alto para uma etapa que
  perdeu a validação automática.
- **Um que não é dele:** trocar o v4 pelo v6 trocaria uma etapa **com** rede
  programática por uma **sem** nenhuma, enquanto a fonte real da confabulação
  (o sumarizador) segue intacta. Na prática, o v6 com sumário sujo herda a
  sujeira e não tem mais como filtrá-la.

**Recomendação:** manter `IMPLICIT_QUESTIONS_PROMPT_VERSION=v4` e
`ENABLE_IMPLICIT_QUESTIONS=false`, e atacar o sumarizador antes de decidir
entre v4 e v6 — é lá que estão os três defeitos que contaminam as duas
versões. Depois disso, repetir este comparativo com o sumário saneado; é o
único jeito de saber quanto da residual do v6 é dele mesmo.

Nenhum default foi alterado por este trabalho.
