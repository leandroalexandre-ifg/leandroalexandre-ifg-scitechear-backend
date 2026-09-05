# E2E da Fase 8 — execução no servidor NumbERS

Relatório da primeira execução ponta a ponta **com biometria de voz realmente
cadastrada** no servidor de deploy. Executado em 2026-09-05.

O E2E anterior (2026-09-05, mais cedo) só cobria o caminho das perguntas
explícitas: sem perfis cadastrados, o estágio `identifying` passava em 0,06s
sem comparar nada. Este relatório fecha essa lacuna e cobre também os cenários
de falso positivo, de reunião sem perguntas, de falas curtas/sobrepostas e de
perguntas implícitas.

## Como foi montado

- **Áudio**: sintetizado com `piper-tts` 1.8.0 (venv descartável), vozes pt_BR
  do repositório `rhasspy/piper-voices`, convertido para WAV 16 kHz mono via
  FFmpeg. Não há áudio de reunião real nem TTS instalado no servidor.
- **Elenco**: `faber` → Ana, `cadu` → Bruno, `jeff` → Carla (os três cadastram
  voz, 3 amostras cada) e `edresson` → convidado externo, que **nunca** cadastra
  amostra nenhuma.
- **Validade do elenco**: antes de qualquer conclusão, a similaridade coseno
  ECAPA entre as quatro vozes foi medida. O par mais parecido (Ana × Bruno)
  deu **0,340**, muito abaixo do threshold de produção (0,75). As vozes são
  separáveis, então um eventual erro de identificação seria do sistema e não
  artefato do TTS.
- **Caminho exercido**: a API real (`127.0.0.1:18080`), o worker real e os
  modelos reais. Usuário criado por `POST /auth/register`, perfis por
  `POST /participants/{id}/voice-samples`, reuniões por `POST /upload`,
  acompanhamento por `GET /status/{job_id}` e resultado por
  `GET /resultado/{job_id}`. Nenhum mock em nenhum ponto.
- **Aferição**: o gerador de áudio grava um gabarito com o intervalo de tempo
  de cada fala, então a identificação é medida por **segundos de fala
  corretamente atribuídos**, não por leitura impressionista do resultado.

## Resultado por cenário

| Cenário | Áudio | Status | Tempo | Veredito |
|---|---|---|---|---|
| R1 — 2 participantes cadastrados | 80,0s | `done` | 15,1s | ✅ ambos identificados, 69,3s de fala, 0 erros |
| R2 — 1 cadastrado + 1 desconhecido | 61,9s | `done` | 14,2s | ✅ **o falso positivo não se reproduz** |
| R3 — sem nenhuma pergunta | 39,0s | `done` | 10,4s | ✅ 0 perguntas (não inventou), 1,6s de troca de falante |
| R4 — falas curtas + sobreposição | 20,1s | `done` | 30,3s | ⚠️ degradou, mas com segurança |
| R5 — perguntas implícitas (flag ligada) | 80,0s | `done` | 56,4s | ⚠️ funciona, com redundância e um detalhe alucinado |

Todos os cinco jobs percorreram os estágios reais e terminaram em `done`.
Nenhum job travou, nenhum resultado veio de fixture (`metadata.stub: false` em
todos).

### R2 — o cenário que motivou a recalibração do threshold

Este era o teste mais importante: replica o incidente em que um participante
sem voz cadastrada foi identificado como outra pessoa. O convidado foi listado
nos `participants` do job (como no incidente), mas nunca cadastrou amostra.

    falante real     atribuído pelo backend      fala    confiança
    desconhecido     (não identificado)         36,1s      0,280
    ana              ana                        21,1s      0,968

A voz sem perfil ficou em 0,280 — bem abaixo do threshold de 0,75 — e o
sistema corretamente **não identificou ninguém**. Com o threshold antigo de
0,30 essa mesma fala teria sido atribuída a Ana. A recalibração documentada em
`PENDENCIAS.md` está confirmada com dados novos.

### Identificação somada nos quatro cenários

De 173,8s de fala processada:

- **161,3s (92,8%)** com comportamento correto — identificação certa, ou
  corretamente recusada para quem não tem perfil;
- **1,6s (0,9%)** de troca de falante, sempre em palavra isolada no começo de
  um turno (ver pendência de fronteira de turno, abaixo);
- **10,9s** não identificados em R4, onde a diarização colapsou os dois
  falantes num cluster só — falha de separação, não de identidade.

**Zero falsos positivos contra participante sem perfil.**

## Tempo por estágio (RTX 5090)

| Job | transcribing | diarizing | identifying | summarizing | extracting | total |
|---|---|---|---|---|---|---|
| R1 (80,0s de áudio) | 6,37s | 0,45s | 0,07s | 0,00s | 7,18s | **15,13s** |
| R2 (61,9s) | 5,81s | 0,33s | 0,07s | 0,00s | 6,86s | **14,18s** |
| R3 (39,0s) | 5,68s | 0,20s | 0,05s | 0,00s | 3,33s | **10,43s** |
| R4 (20,1s) | 5,28s | 0,10s | 0,02s | 0,00s | 24,50s | **30,32s** |
| R5 (80,0s, implícitas ON) | 6,53s | 1,74s | 0,25s | 28,17s | 18,07s | **56,40s** |

R1 processa 80s de reunião em 15,1s — cerca de **5,3× mais rápido que o tempo
real**. O perfil confirma o que `PERFORMANCE.md` já apontava: com implícitas
desligadas, a extração pelo LLM domina o custo (47% em R1). A diarização, que
no Mac era o maior gargalo (38,6%), praticamente desapareceu na GPU (3%).

## Achados

### 1. O prefixo `[Nome]: ` no campo `text` persiste no `qwen3:14b`

A pendência aberta pedia reverificar com o modelo de produção antes de decidir.
**Está reverificada: o problema persiste.** Em R4, as duas perguntas explícitas
saíram como `[SPEAKER_00]: Juno, tudo certo?` e
`[SPEAKER_00]: Você consegue terminar hoje?` — com o rótulo colado no campo
`text`.

Duas informações novas em relação ao registro anterior:

- não é limitação do `qwen3:4b`; acontece no modelo pinado na spec;
- só apareceu **no cenário em que o falante não foi identificado**, onde o
  rótulo da linha é `[SPEAKER_00]` em vez de `[Nome]`. Nos cenários com falante
  identificado (R1, R2, R5), nenhuma das cinco perguntas veio com prefixo.

Isso reposiciona o problema: a hipótese mais provável é que o rótulo sintético
`[SPEAKER_00]` seja menos reconhecível como "rótulo de formato" do que um nome
próprio, e o modelo o trate como parte da fala. É um ponto de calibração de
prompt, não de código — a regra de não corrigir o texto devolvido pelo LLM
continua valendo.

### 2. Fronteira de turno: a primeira palavra curta vai para o falante anterior

Em R3, dois segmentos foram atribuídos ao falante errado, ambos com o mesmo
padrão: uma interjeição curta que **abre** um turno é atribuída a quem falou
antes.

    26,79-27,99  SPEAKER_00 → p-ana     "Combinado."    (era da Carla)
    34,63-35,01  SPEAKER_01 → p-carla   "Perfeito."     (era da Ana)

`_atribuir_clusters` escolhe o cluster de maior sobreposição temporal, o que
está correto; a fronteira de turno devolvida pelo pyannote é que chega
deslocada em ~1s. Impacto pequeno (1,6s em 173,8s, sempre em palavra isolada),
mas é sistemático e não aleatório. Não bloqueia a V1.

### 3. Falas curtas alternadas colapsam a diarização — mas a degradação é segura

Em R4 o pyannote **encontrou** dois clusters (o log registra
`SPEAKER_00, SPEAKER_01`, com aviso de `Pouca duração de fala para SPEAKER_01:
2,6s`), mas nenhum segmento da transcrição teve o `SPEAKER_01` como cluster de
maior sobreposição — o resultado final saiu com um cluster só e todos os nove
segmentos atribuídos a ele.

O desdobramento é o comportamento desejado: o embedding do cluster misturado
deu 0,609, abaixo do threshold, e **ninguém foi identificado**. O sistema
preferiu não responder a responder errado — exatamente a política que a
recalibração para 0,75 quis garantir.

Vale notar que R4 também foi o job **mais caro** (24,5s de extração, 3.397
tokens gerados) apesar de ter o áudio mais curto: nove falas telegráficas
custaram 4,6× mais tokens de saída que a reunião estruturada de 80s. Áudio
fragmentado é mais caro que áudio longo, não menos.

### 4. Perguntas implícitas funcionam, com evidência real — e com redundância

Com `ENABLE_IMPLICIT_QUESTIONS=true`, R5 devolveu 2 explícitas + **15
implícitas**. Pontos positivos, verificados um a um:

- **todas as 15 apontam para `source_segment_ids` que existem de fato** no
  resultado — a correção de confabulação continua valendo;
- nenhuma pergunta genérica de roteiro ("qual o orçamento?") sem lastro.

Os problemas:

- **Redundância pesada**: seis das quinze derivam do mesmo `seg_0016`, e várias
  são paráfrases umas das outras ("Quais critérios serão utilizados para
  determinar se a redução do contexto é viável e eficaz?" ao lado de "Como a
  eficácia da redução do contexto será mensurada e validada?"). Confirma o
  achado de redundância do `qwen3:14b` já registrado.
- **Um detalhe factual alucinado**: duas perguntas citam "o prazo final de 30
  de outubro". A transcrição diz apenas "o dia trinta deste mês" — o mês foi
  inventado. A evidência aponta para um segmento real, mas o texto da pergunta
  acrescenta um fato que não está lá.
- **Custo**: 56,4s contra 15,1s no mesmo áudio (3,7×), quase todo em
  `summarizing` (28,2s).
- `participant_id` e `time` vêm `None` em todas as implícitas — coerente com o
  schema e com o caso de teste previsto para o Flutter, mas o app precisa
  exibi-las sem autor.

A flag permanece `false` em produção. Os números acima reforçam a decisão.

### 5. Erros de ASR se propagam para as perguntas (e isso é o comportamento correto)

O WhisperX `turbo` cometeu erros que apareceram literalmente nas perguntas:
"extração" → "estação", "gargalo" → "gagalo", "Bruno" → "Juno", "ontem à tarde"
→ "áudio oculto". O LLM copiou o texto errado fielmente, em vez de "consertar"
— que é exatamente a regra do projeto (não corrigir o texto do segmento nem a
resposta do modelo). Uma das implícitas de R5 ficou sem sentido por herdar o
erro ("o modelo de linguagem gagalo, considerando que ele é um modelo de
linguagem").

Fica registrado como limite conhecido da qualidade de transcrição, não como
defeito do pipeline de perguntas. Vale reavaliar se o modelo `turbo` é o certo
para pt-BR antes de trocar qualquer outra coisa.

## O que este E2E ainda não prova

- **Áudio real**: tudo aqui é TTS — sem ruído de sala, sem microfone distante,
  sem sotaque variado, sem hesitação humana. A pendência de diarização em áudio
  distante/ruidoso continua aberta e **não** foi endereçada por este teste.
- **Sobreposição de verdade**: o trecho sobreposto de R4 é uma soma de duas
  faixas, não duas pessoas falando juntas numa sala.
- **O app Flutter**: nada foi exercido pelo cliente real (Fase 7 pendente).
- **WebSocket**: `/ws/{job_id}` continua stub; o acompanhamento foi por
  polling, como o app faz hoje. O polling de 3s não chegou a observar
  `diarizing`/`identifying` nos jobs sem implícitas — os estágios duram menos
  que o intervalo. Não é falha: o histórico de status do job registra todas as
  transições, e o log do worker as confirma.

## Reprodução

O material descartável está em `/data/projects/leandro/scitechear/tmp-e2e/`
(fora do checkout, como todo dado de usuário): `gerar_audio.py` (síntese +
gabarito), `e2e.py` (cenários 1–4), `e2e_implicitas.py` (cenário 5),
`analisar.py` (confronto com o gabarito), o venv do piper e as vozes baixadas
(~570 MB somados).

O cenário 5 foi rodado **sem alterar o `.env` de produção**: o worker do
systemd foi parado, um worker temporário subiu com
`ENABLE_IMPLICIT_QUESTIONS=true` apenas no ambiente do processo, e o worker de
produção foi restaurado ao final.
