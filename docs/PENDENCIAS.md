# Pendências — SciTech Ear · Backend

Registro vivo de achados que não bloqueiam a fase corrente, mas precisam de
acompanhamento — calibração de prompt/modelo, comportamento a reverificar
antes de considerar algo definitivamente resolvido, etc. Diferente de
`docs/BASELINE.md` (retrato pontual da Fase 0): este arquivo é atualizado ao
longo do projeto.

## Resolvida — Perguntas explícitas: prefixo `[Nome]: ` vazando no campo `text`

**Onde:** `question_service.extract_explicit_questions` (prompt
`prompts/explicit_questions_v4.json`).

**O quê:** validando o pipeline completo com `qwen3:4b` (modelo local, usado
só para testar o caminho feliz — não é o modelo de produção), o campo
`text` da pergunta explícita às vezes vem com o prefixo `[Nome]: ` colado,
ex.: `"[Leandro]: Qual é o prazo final para entregar a integração
completa?"` em vez de só `"Qual é o prazo final para entregar a integração
completa?"`.

**Causa:** o `TranscriptFormatter` monta cada linha da transcrição como
`"N -> seg_XXXX -> [Nome]: texto"` para os prompts. O prompt
(`explicit_questions_v4.json`) e seu exemplo few-shot deixam claro que o
campo `pergunta` deve conter só o texto após os dois-pontos — o rótulo
`[Nome]:` é parte do formato de linha, não da pergunta. Com `qwen3:4b`, o
modelo às vezes copia o rótulo junto.

**Por que não foi corrigido no código:** o serviço repassa `item.pergunta`
literalmente, por design — a regra é "não corrigir o texto da pergunta"
(nem a resposta do LLM, nem o texto original do segmento). Tratar isso no
código seria decidir, sem saber a real intenção do modelo, o que cortar da
string — o problema é de fidelidade do modelo ao prompt, não do pipeline.
É um ponto de calibração (junto com thresholds de biometria, min/max
speakers etc., que a spec já marca como não bloqueantes para a V1).

**Próximo passo:** reverificar com `qwen3:14b` (modelo de produção,
pinado na spec) antes de decidir se isso precisa de ajuste de prompt. Se o
`qwen3:14b` também vazar o prefixo, considerar reforçar a instrução do
prompt (algo como "não inclua o rótulo `[Nome]:` no campo `pergunta`") —
mudança de prompt, versionada, sem alterar os critérios semânticos
existentes (regra do AGENTS.md).

**Reverificação com `qwen3:14b` (2026-09-05, E2E da Fase 8 — ver
`docs/E2E_FASE8.md`):** o problema **persiste no modelo de produção**, então
não era limitação do `qwen3:4b`. Mas a reverificação trouxe um recorte que o
registro original não tinha: das sete perguntas explícitas extraídas nos cinco
cenários, **as duas que vazaram o prefixo foram exatamente as do único cenário
em que o falante não foi identificado** — nele o rótulo da linha é
`[SPEAKER_00]`, e saiu `"[SPEAKER_00]: Juno, tudo certo?"`. Nos cenários com
falante identificado, em que o rótulo é um nome próprio, nenhuma das cinco
perguntas veio com prefixo.

Hipótese que isso sugere (ainda não testada isoladamente): um nome próprio é
reconhecido pelo modelo como rótulo de formato, enquanto `[SPEAKER_00]` —
sintético e sem semântica de pessoa — é tratado como parte da fala. Se
confirmado, o ajuste de prompt deve mirar especificamente o caso do falante
não identificado, e não a instrução geral.

**Correção (2026-09-05, `prompts/explicit_questions_v5.json`):** feita por
prompt, versionada, com os critérios de extração intactos — o serviço continua
repassando `item.pergunta` literalmente, sem cortar string nenhuma em Python.
Três edições cirúrgicas sobre o v4:

1. uma regra nova dizendo que o rótulo entre colchetes que abre a linha
   (`[Leandro]: `, `[SPEAKER_00]: `) é formato da transcrição e não pertence ao
   campo `pergunta`, explicitamente inclusive quando é identificador genérico;
2. um segundo exemplo few-shot com falante **não identificado** — o v4 só tinha
   exemplo com nome próprio, que era justamente o caso que já funcionava;
3. o exemplo de sentença curta em `instrucoes_importantes` passou a mostrar o
   texto extraído (`extraia 'Verdade?'`) em vez da linha inteira
   (`'SPEAKER_00: Verdade?'`), que reforçava o comportamento errado.

**Validação A/B nos quatro cenários do E2E, com `qwen3:14b` e os mesmos
áudios:**

| Cenário | v4 | v5 |
|---|---|---|
| R4 (falante não identificado) | `[SPEAKER_00]: Juno, tudo certo?` | `Juno, tudo certo?` |
| R1 (2 identificados, 2 perguntas) | correto | idêntico ao v4 |
| R2 (1 pergunta) | correto | idêntico ao v4 |
| R3 (nenhuma pergunta) | lista vazia | lista vazia |

O único caso ruim foi corrigido e os três bons ficaram idênticos ao baseline —
inclusive preservando o erro de ASR ("estação" no lugar de "extração"), o que
confirma que a cópia literal continua valendo.

**Limitação desta validação:** uma execução por cenário, com áudio sintético.
A geração é determinística (`temperature=0`, `seed=42`), mas isso não descarta
que outra transcrição provoque o vazamento por outro caminho. Mesma ressalva
que `docs/PERFORMANCE.md` faz sobre a validação de `think=False`.

`tests/test_question_service.py` trava as duas metades da decisão: que o prompt
ativo tem a regra e o exemplo com rótulo genérico, e que o código **não**
sanitiza o texto devolvido pelo LLM (se alguém "ajudar" cortando o prefixo em
Python, o teste quebra).

**Status:** resolvida.

---

## Aberta — Fronteira de turno: primeira palavra curta de um turno é atribuída ao falante anterior

**Onde:** `app/services/diarization_service._atribuir_clusters` (a rigor, a
fronteira devolvida pelo pipeline do pyannote).

**O quê:** no E2E da Fase 8 (2026-09-05, cenário R3 — `docs/E2E_FASE8.md`),
dois segmentos saíram com o falante errado, ambos com o mesmo padrão: uma
interjeição curta que **abre** um turno foi atribuída a quem falou antes.

    26,79-27,99  SPEAKER_00 → p-ana     "Combinado."    (era da Carla)
    34,63-35,01  SPEAKER_01 → p-carla   "Perfeito."     (era da Ana)

**Causa:** `_atribuir_clusters` escolhe, para cada segmento da transcrição, o
cluster de maior sobreposição temporal — o que está correto. O deslocamento
vem da fronteira de turno do pyannote, que chega ~1s atrasada; o segmento
curto inteiro cai antes dela e herda o cluster anterior.

**Impacto:** 1,6s de 173,8s de fala (0,9%) no E2E, sempre em palavra isolada.
Não afeta o corpo das falas nem nenhuma pergunta extraída. É sistemático (não
aleatório), o que facilita reconhecer o padrão em produção.

**Por que não foi corrigido:** qualquer correção aqui é heurística — mover a
fronteira, ou reatribuir segmentos curtos ao cluster seguinte, exige decidir
sem evidência qual dos dois lados está certo, e pode piorar casos em que a
interjeição realmente pertence ao turno anterior ("Combinado." dito por quem
já estava falando). Precisa de mais dados reais antes de virar regra.

**Status:** aberta, baixo risco, não bloqueia a V1.

---

## Aberta — Falas curtas alternadas colapsam a diarização num cluster só

**Onde:** `app/services/diarization_service.diarizar`.

**O quê:** no E2E da Fase 8 (cenário R4: nove falas de 1 a 3 palavras,
alternando dois falantes, mais um trecho sobreposto), o pyannote **encontrou**
dois clusters — o log registra `SPEAKER_00, SPEAKER_01` com
`Pouca duração de fala para SPEAKER_01: 2,6s` — mas nenhum dos nove segmentos
da transcrição teve o `SPEAKER_01` como cluster de maior sobreposição. O
resultado final saiu com **um cluster só**.

**Desdobramento (o comportamento desejado):** o embedding do cluster misturado
deu 0,609, abaixo do threshold de 0,75, e ninguém foi identificado. O sistema
preferiu não responder a responder errado — é a política que a recalibração do
threshold quis garantir, funcionando num caso que ela não foi projetada para
cobrir.

**Relação com a pendência de áudio distante/ruidoso:** é o mesmo tipo de falha
(o pyannote não separa bem) por outra causa — ali é a captação, aqui é a
duração dos turnos. As duas convergem para a mesma mitigação: a identificação
degrada para "não identificado" em vez de errar a pessoa.

**Achado colateral de custo:** R4 foi o job **mais caro** (24,5s de extração,
3.397 tokens gerados) apesar de ter o áudio mais curto (20,1s) — 4,6× mais
tokens de saída que a reunião estruturada de 80s. Áudio fragmentado custa mais
que áudio longo, não menos. Relevante para o dimensionamento de uma reunião
real com muitas trocas rápidas de turno.

**Status:** aberta, não bloqueia a V1.

---

## Aberta — Perguntas implícitas: redundância e um detalhe factual alucinado

**Onde:** `question_service.extract_implicit_questions` /
`summarize_meeting`, com `ENABLE_IMPLICIT_QUESTIONS=true`.

**O quê:** no E2E da Fase 8 (cenário R5, `qwen3:14b`, reunião de 80s com nove
falas), a extração devolveu 2 perguntas explícitas e **15 implícitas**.

O que funcionou: **todas as 15 apontam para `source_segment_ids` que existem
de fato** no resultado, e nenhuma é pergunta genérica de roteiro sem lastro —
a correção de confabulação (commit `94cebe2`) continua valendo com dados
novos.

Os dois problemas:

1. **Redundância pesada.** Seis das quinze derivam do mesmo `seg_0016`, e
   várias são paráfrases umas das outras — "Quais critérios serão utilizados
   para determinar se a redução do contexto é viável e eficaz?" ao lado de
   "Como a eficácia da redução do contexto será mensurada e validada?".
   Confirma, com número, o achado de redundância do `qwen3:14b` já registrado
   em `805fe4d`.
2. **Um detalhe factual inventado.** Duas perguntas citam "o prazo final de 30
   de outubro"; a transcrição diz apenas "o dia trinta deste mês". A evidência
   aponta para um segmento real, mas o **texto da pergunta** acrescenta um
   fato que não está nele. É uma falha diferente da confabulação já corrigida
   (que inventava a pergunta inteira, sem lastro): aqui o lastro existe e o
   enfeite está no enunciado.

**Custo:** 56,4s contra 15,1s no mesmo áudio (3,7×), quase todo concentrado em
`summarizing` (28,2s).

**Status:** aberta. Reforça a decisão de manter `ENABLE_IMPLICIT_QUESTIONS=false`
em produção (flag introduzida em `be8dc49`). Não bloqueia a V1, que não depende
de implícitas.

## Resolvida — Perguntas implícitas confabulando roteiro genérico sem lastro na transcrição

**Onde:** `question_service.extract_implicit_questions` (prompt
`prompts/implicit_questions_v3.txt`, substituído por `v4`).

**O quê:** validado com um job real (16 segmentos, conversa curta e trivial
entre Leandro e a mãe sobre um carro novo — só "estou gostando", "muito bom
pra dirigir", "estou adorando até hoje", nada além disso). Resultado: 4
perguntas explícitas corretas + **15 perguntas implícitas** formando um
roteiro genérico de avaliação de compra de carro (eficiência energética,
segurança, valor de revenda, impacto ambiental etc.) — nenhum desses temas
foi mencionado ou sugerido na conversa real. Confabulação, violando as
próprias restrições do prompt v3 ("não invente fatos que não ocorreram").

**Causa raiz — reproduzida e confirmada** com uma transcrição sintética
equivalente (mesmo formato: conversa trivial e curta), rodada localmente
contra `qwen3:4b` e `qwen3:14b` via Ollama, comparando `v3` (baseline) com
`v4` (corrigido):

- `v3` + `qwen3:4b`: 5 perguntas confabuladas, nenhuma relacionada ao
  conteúdo real (giram em torno de "bem-estar"/"equilíbrio trabalho-saúde",
  temas nunca discutidos).
- `v3` + `qwen3:14b`: **exatamente 15 perguntas confabuladas** — bateu no
  teto do prompt, reforçando a hipótese de que "até, no máximo, 15" estava
  sendo tratado como meta, não limite. Contra a intuição, o modelo **maior**
  confabulou mais (em quantidade), não menos: o problema não era capacidade
  do modelo, era ancoragem de prompt.
- Achado adicional (não hipotetizado antes, encontrado ao revisar o v3): o
  esqueleto JSON de "Formato de saída" do v3 mostrava 1 item no array mas
  `"total_perguntas": 15"` — uma inconsistência estrutural que reforçava a
  âncora "15" antes mesmo do few-shot real (que já estava correto).

**Correção aplicada:**
1. `prompts/implicit_questions_v4.txt` (v3 preservado para rastreabilidade,
   ver `prompts/README.md`): teto de 15 reformulado como limite absoluto —
   nunca meta —, lista vazia declarada explicitamente como saída válida e
   esperada para conteúdo trivial; corrigido o esqueleto JSON inconsistente;
   novo campo obrigatório por pergunta, `linhas_evidencia` (linhas reais da
   transcrição, mesma numeração usada nas explícitas, que fundamentam a
   inferência). Critérios semânticos (linguagem formal, não redundância,
   foco em tomada de decisão) preservados.
2. `question_service._resolver_evidencia_implicita`: validação programática
   — não confia só na instrução do prompt. Resolve cada linha citada via
   `TranscriptFormatter.get_line` (mesmo mecanismo já usado para
   `linha_transcricao` das explícitas); descarta a pergunta inteira se a
   maioria das linhas citadas não existir na transcrição (tolera erro de
   contagem pontual do modelo, tipo off-by-one; não tolera pergunta
   majoritariamente inventada que só "ancorou" numa linha real de forma
   oportunista). `source_segment_ids` passa a ser preenchido para perguntas
   implícitas (antes sempre `[]`); `participant_id`/`speaker`/`time`
   continuam `null` — implícita pode cruzar várias linhas/falantes.
3. Testes de contrato em `tests/test_question_service.py` (fixtures,
   `monkeypatch` em `_chamar_ollama`, sem LLM real): evidência válida
   preenche `source_segment_ids`; sem `linhas_evidencia` descarta; maioria
   das linhas inválida descarta a pergunta inteira; maioria válida mantém
   só as linhas reais; teste de regressão espelhando o incidente (2
   perguntas com lastro real + 17 confabuladas → só as 2 sobrevivem).

**Validação empírica pós-correção** (mesma transcrição sintética,
`qwen3:4b` e `qwen3:14b`): **0 perguntas implícitas geradas nos dois
modelos** — o próprio modelo já não confabulou, a validação programática
não precisou descartar nada nesse caso específico. Ressalva: como o modelo
já retornou lista vazia, essa rodada não exercitou a rede de segurança de
código (descarte por evidência majoritariamente inválida) contra uma
alucinação real — isso está coberto pelos testes de fixture, não pela
chamada real ao LLM. Recomenda-se reverificar com jobs reais diversos
(não só cenários triviais) ao longo do tempo.

**Hipóteses secundárias testadas, não implementadas (conforme escopo
pedido):**
- **Refinador** (`prompts/implicit_refiner_v1.txt`,
  `ENABLE_IMPLICIT_REFINEMENT=true`) rodado sozinho sobre a saída
  confabulada do v3 baseline: reduz a quantidade (`qwen3:4b`: 5→3,
  `qwen3:14b`: 15→10) mas **não audita lastro** — as perguntas remanescentes
  continuam sobre temas não discutidos na conversa real. Confirma a
  ressalva original: o refinador reformula/consolida texto, não verifica
  evidência; não é solução para a confabulação, só reduz volume. Achado
  extra fora do escopo desta calibração: com `qwen3:4b`, a saída do
  refinador veio **em inglês** (possível falha de fidelidade de idioma do
  modelo menor com esse prompt específico) — vale investigar depois, não
  bloqueia.
- **Tamanho do modelo**: `qwen3:14b` (modelo de produção, já default em
  `.env`) **não reduziu** a confabulação em relação a `qwen3:4b` — bateu
  exatamente no teto de 15 no baseline v3. Confirma que a causa raiz era a
  ancoragem do prompt na meta de 15, não a capacidade do modelo — hipótese
  principal do usuário, confirmada empiricamente.

**Status:** corrigido (prompt v4 + validação programática + testes de
contrato). Monitoramento de longo prazo recomendado: um modelo adversarial
poderia, em tese, citar 1 linha real e inventar contexto ao redor dela para
burlar a maioria estrita — a validação atual não elimina esse caso
extremo, é uma redução de risco, não uma prova formal. Não bloqueia fases
seguintes.

**Validação adicional — v4 não ficou conservador demais:** rodado contra
uma segunda transcrição sintética, dessa vez substantiva (decisões reais:
ajuste de threshold de biometria, bug de alinhamento do WhisperX em fala
sobreposta, instabilidade da GPU do Colab, decisão WebSocket vs. polling,
responsabilidade por `DEMO_MODE=false` em staging). Resultado: `qwen3:4b`
gerou 3 perguntas implícitas legítimas e ancoradas; `qwen3:14b` gerou 15,
todas com `linhas_evidencia` reais (100% mantidas na validação
programática) e genuinamente relacionadas ao conteúdo discutido — nenhum
roteiro genérico desconectado, ao contrário do caso trivial do carro.
Confirma que a correção suprime confabulação sem suprimir perguntas
legítimas quando o conteúdo sustenta.

**Achado novo, fora do escopo desta calibração — redundância em
`qwen3:14b`:** nas 15 perguntas geradas para a reunião substantiva, há
sobreposição temática real entre itens (ex.: duas perguntas quase
idênticas sobre a decisão de manter polling em vez de WebSocket; duas
sobre o mesmo ponto de monitorar o threshold 0.35; duas sobre plano de
contingência da GPU). O prompt já pede explicitamente "não repetitivas ou
redundantes", mas o modelo maior não filtrou isso quando o volume de
conteúdo se aproxima do teto de 15. Isso é uma questão de qualidade/
deduplicação, distinta da confabulação (as perguntas têm evidência real,
só se repetem) — registrado aqui como pendência separada, não implementado
ainda; possível endereçamento futuro seria pós-processamento de
similaridade textual entre `pergunta`s antes de retornar o resultado, ou
reforço adicional no prompt.

**Atualização (2026-08-12) — etapa inteira temporariamente desativada por
decisão do usuário:** apesar da correção acima (prompt v4 + validação
programática de evidência), a extração de perguntas implícitas foi
desligada por padrão via nova flag `ENABLE_IMPLICIT_QUESTIONS` (default
`false`, `app/config.py`) — não confundir com `ENABLE_IMPLICIT_REFINEMENT`
(já desligado antes, continua desligado). Motivo: isolar o comportamento do
restante do sistema (transcrição, diarização, biometria, perguntas
explícitas) enquanto a qualidade da extração implícita é validada
separadamente — a confabulação original foi corrigida e parcialmente
validada (ver acima, branch `fix/perguntas-implicitas-evidencia`), mas
ainda não em volume/diversidade suficiente de reuniões reais para confiar
nela em produção. Quando `ENABLE_IMPLICIT_QUESTIONS=false`:

- `pipeline_facade._extrair_perguntas` não chama
  `question_service.extract_implicit_questions` nem, por consequência,
  `refine_implicit_questions` (que só faz sentido sobre uma saída implícita
  que não existe).
- `question_service.summarize_meeting` também não é chamado — hoje ela só
  existe como insumo interno para as implícitas, sem outro consumidor no
  pipeline; pular as duas juntas evita uma chamada ao Ollama sem uso.
  Estágios de job continuam passando por `summarizing` e `extracting`
  normalmente (contrato de estados inalterado); só o trabalho real dessas
  etapas é pulado.
- `MeetingResult.questions` passa a conter só perguntas `explicit` — sem
  itens vazios ou placeholder no lugar das implícitas.
- **Nada do trabalho já feito foi removido**: `extract_implicit_questions`,
  o prompt v4 e a validação de evidência continuam intactos em
  `question_service.py`, só não são chamados. Reativar é trocar a flag para
  `true` (`.env` ou `.env.example`).
- Regressão: `tests/test_pipeline_facade.py::test_pipeline_pula_etapa_implicita_quando_flag_desligada`
  trava que, com a flag desligada, nem `summarize_meeting` nem
  `extract_implicit_questions` são chamados e o resultado final só tem
  perguntas explícitas.

## Aberta — Identificação biométrica: falso positivo com `VOICE_IDENTIFICATION_THRESHOLD=0.30`, recalibrado para 0.75; risco residual documentado

**Onde:** `app/services/voice_service.identificar_speaker` /
`VOICE_IDENTIFICATION_THRESHOLD` (`app/config.py`, `.env`, `.env.example`).

**Incidente:** em teste real com 4 participantes (3 cadastraram voz, 1 nunca
cadastrou nenhuma amostra), o participante não-cadastrado apareceu no
resultado identificado como um dos outros três — falso positivo de
identificação, mais grave que um falso negativo (atribuir a fala de uma
pessoa a outra é problema de confiança/privacidade, não só de qualidade).

**Investigação (dados reais, não hipotéticos):** reproduzido com áudio TTS
sintético (macOS `say`, pt-BR/pt-PT) — 3 participantes cadastrados de
verdade no `VoiceRepository` (embeddings ECAPA reais), 1 nunca cadastrado.
Rodando `identificar_speaker`/`aplicar_biometria` de produção:

- O pool de comparação (`banco`) já estava corretamente restrito aos
  participantes daquela reunião com embedding cadastrado
  (`pipeline_facade._carregar_banco_e_nomes`) — **não** compara contra todo
  o `VoiceRepository`. Essa hipótese foi descartada.
- Não é bug de lógica de decisão: threshold e margem funcionam exatamente
  como documentado. O problema é calibração: com `THRESHOLD=0.30`, testei o
  falante não-cadastrado contra o banco de 3 perfis e depois testei mais 6
  falantes não-cadastrados diferentes contra o mesmo banco — **6 de 7**
  deram falso positivo, a maioria com margem folgada (não foram rejeições
  "quase certas" que passaram raspando).
- Coletei o piso real de match GENUÍNO com mais amostras (15 = 3 pessoas
  cadastradas x 5 frases novas cada, comparadas contra o próprio perfil):
  **mínimo 0.9157, máximo 0.9543, média 0.9369.**
- Teto de score de impostor, desconsiderando 1 outlier suspeito (ver
  abaixo): **0.6214.**

**Correção aplicada:** `VOICE_IDENTIFICATION_THRESHOLD` alterado de **0.30**
para **0.75** — comfortavelmente abaixo do piso genuíno observado (folga de
0.166) e acima do teto de impostor não-outlier (folga de 0.129), deliberadamente
mais perto do piso genuíno do que do teto de impostor (risco assimétrico:
falso negativo é preferível a falso positivo). `VOICE_MIN_MARGIN` (0.05)
mantido como defesa secundária, não a única — a decisão real que barra a
maioria dos impostores agora é o threshold, a margem cobre o caso de dois
candidatos cadastrados muito parecidos entre si.

**PROVISÓRIO — pendente de revalidação:** 0.75 foi calibrado inteiramente
com embeddings de voz sintética (TTS), não gravações humanas reais. Antes de
produção, revalidar com um conjunto de vozes humanas reais (idealmente
incluindo pares foneticamente parecidos) para confirmar que o piso genuíno e
o teto de impostor observados aqui se sustentam.

**Risco residual em aberto, NÃO resolvido por este threshold:** um dos 7
impostores testados (voz "Reed" do macOS, nunca cadastrada) obteve score
**0.9555** contra o perfil cadastrado de "Eddy" — margem de 0.899 para o
segundo colocado. Esse score cai **dentro** da própria faixa de match
genuíno observada (piso 0.9157), então nenhum threshold plausível de
similaridade de cosseno bloqueia esse caso sem também rejeitar matches
genuínos legítimos. Suspeita (não confirmada): Eddy/Reed são vozes
"novelty" do macOS que aparentemente compartilham o mesmo motor de síntese
base com efeito de pitch/formante por cima, o que infla artificialmente a
similaridade — mas o risco estrutural (duas vozes humanas naturalmente
parecidas, ou parentes) não é hipotético e não tem solução só de threshold.
Esse teste está travado propositalmente como "falha esperada, não
corrigida" em
`tests/test_voice_identification_real_regression.py::test_outlier_reed_eddy_NAO_e_bloqueado_pelo_threshold_075_limitacao_conhecida`
— não deve ser "consertado" trocando o threshold sem antes discutir uma
mudança estrutural (ex.: normalização de score, verificação adicional,
revisão humana para casos limítrofes).

**Regressão:** `tests/test_voice_identification_real_regression.py` usa
embeddings ECAPA reais (não sintéticos/aleatórios) congelados em
`tests/fixtures/voice_identification_real_embeddings.json` — reprodutíveis
via os scripts usados nesta investigação (áudio TTS + `VoiceRepository` +
`voice_service.gerar_embedding`). Trava: os 6 impostores não-outlier
rejeitados, as 15 amostras genuínas identificadas corretamente, e o outlier
Reed/Eddy **não** rejeitado (limitação conhecida).

**Revalidação com voz humana real — EM ANDAMENTO (2026-08-13):** primeiro
caso real reportado — reunião de 1 falante com voz cadastrada apareceu como
NÃO IDENTIFICADO. Diagnóstico (sem reprocessar pipeline; score lido do
`result.json` já persistido e reproduzido isoladamente via
`voice_service` contra os embeddings salvos):

- Job `873111cc-0ada-413f-8742-3f11b10d74a8` (12/08 20:21): score **0.7304**,
  abaixo do threshold 0.75 → rejeitado corretamente pela lógica atual (não é
  bug de decisão). 5 de 7 segmentos qualificaram para o embedding (≥1.5s,
  ~27s concatenados, nenhum outlier) — não é caso de poucos segmentos.
- Dois outros jobs de 1 falante rodados **depois** do fix do threshold
  (commit `86d6c99`, 12/08 19:37) com a mesma pessoa: job `189e5d28`
  (11/08) = 0.7684 (identificado); job `75d7669d` (12/08 19:44) = 0.7621
  (identificado, por pouco).
- **Os 3 scores genuínos reais pós-fix caem em 0.73–0.77** — bem abaixo do
  piso genuíno medido com TTS (0.9157–0.9543). A folga entre o piso
  genuíno real observado e o teto de impostor sintético (0.6214) caiu de
  0.166 (TTS) para **~0.11**. Ainda não há sobreposição confirmada, mas a
  margem de segurança encolheu, como era de se esperar ao trocar TTS por
  voz humana real.
- **Achado colateral corrigido:** o `VoiceRepository` tinha 4 perfis
  "Leandro"/"leandro" duplicados (`participant_id` = timestamp gerado no
  momento do cadastro — cada teste manual do endpoint de enrollment criou
  um participante novo em vez de reutilizar um existente). Confirmado que
  **não é bug de backend**: este serviço não gera `participant_id`, ele é
  puramente definido por quem chama `POST /participants/{participant_id}
  /voice-samples` (contrato do AGENTS.md, regra 4) — os IDs eram lixo de
  testes manuais do endpoint, anteriores à integração com um cliente
  estável. Um dos duplicados batia como 2º colocado (0.7077, margem 0.0227
  para o 1º) no caso acima, o que teria acionado rejeição por
  `VOICE_MIN_MARGIN` mesmo se o threshold fosse reduzido — duplicatas
  distorcem a margem e não podem entrar em dados de calibração. Os 3
  perfis mais antigos foram removidos via `VoiceRepository.delete_profile`
  em 2026-08-13, mantendo só o mais recente (`1786574452078827`). Os
  outros 4 perfis cadastrados (Mãe, Maria, Pedro, Samuel) são pessoas
  reais distintas, sem duplicação.

**Decisão atual: threshold MANTIDO em 0.75.** Ainda não há dados
suficientes para recalibrar com segurança — só uma pessoa real testada até
agora (3 amostras dela mesma), e falta testar impostor real (pessoa A
contra perfil de pessoa B, via microfone, não TTS). Aceitar o falso
negativo específico documentado acima é consistente com a prioridade
assimétrica já definida (falso negativo é preferível a falso positivo).
Pendente: gravar 2-3 frases de pelo menos mais uma pessoa real distinta
para (a) confirmar o piso genuíno humano com mais de 1 amostra/pessoa e
(b) medir impostor real. Só então decidir um novo número, com o mesmo
rigor da calibração anterior.

## Aberta — Performance do pipeline: extração de perguntas explícitas é ~42% do tempo total; think=False testado e revertido

**Onde:** `app/services/question_service.py` (`_chamar_ollama`,
`extract_explicit_questions`), `app/repositories/job_repository.py`
(instrumentação de tempo por estágio).

**Ver `docs/PERFORMANCE.md`** para a medição completa (tempo por estágio,
breakdown load/prompt_eval/eval do Ollama) e o teste antes/depois de
`think=False` para `extract_explicit_questions`: reduziu o tempo em 77,3%,
mas mudou o CONTEÚDO extraído (perdeu uma pergunta genuína, ganhou uma
frase que não era pergunta) — revertido, `think=True` mantido. Testado com
uma única transcrição sintética; não repetido com dados diversos.

## Aberta — Diarização mistura falantes em áudio distante/ruidoso/sobreposto; não é problema de threshold nem de min/max speakers

**Onde:** `app/services/diarization_service.diarizar` (pyannote pipeline
`pyannote/speaker-diarization-community-1`, `VBxClustering`).

**Incidente (2026-08-16):** reunião informal de 3 pessoas (Leandro, mãe,
terceiro falante), gravada com tablet longe da boca dos falantes, ambiente
ruidoso e fala frequentemente sobreposta. Job
`30343d67-76d1-47ad-a313-8552fa094b87`. Os 3 clusters (`SPEAKER_00/01/02`)
saíram da identificação biométrica com scores muito baixos e uniformes
(0.14–0.33) — bem abaixo tanto do threshold atual (0.75) quanto da faixa
0.73–0.77 já documentada acima como "genuíno real, mas abaixo do
threshold". A uniformidade e a magnitude dos scores sugeriam outra causa,
não simplesmente calibração de threshold.

**Investigação (áudio real ouvido pelo usuário, não hipotético):**
extraídos e concatenados, por cluster, todos os trechos de áudio daquele
cluster (script ad hoc com `soundfile`, não versionado — cada cluster virou
um WAV próprio). O usuário ouviu os 3 arquivos e confirmou por escuta:
**os 3 clusters têm vozes misturadas** — não é um caso isolado, é
generalizado nesta reunião. Confirma que o problema é de diarização
(agrupamento errado, antes até da comparação de embedding), não de
threshold de identificação.

**Descartada a hipótese de min/max speakers mal configurado:**
reprocessada só a etapa de diarização (sem re-rodar WhisperX) com
`num_speakers=3` explícito (`exact_speaker_count=True`, contornando o
range default `DIARIZATION_MIN_SPEAKERS=1`/`DIARIZATION_MAX_SPEAKERS=10`).
Resultado: clusters **idênticos** aos do job original — mesmas fronteiras,
mesmas durações por cluster (SPEAKER_00: 9 segmentos/8.69s; SPEAKER_01: 7
segmentos/15.27s; SPEAKER_02: 12 segmentos/53.63s). O pyannote já
convergia para 3 falantes sozinho dentro do range default; forçar o número
exato não mudou a atribuição. O problema não é o pipeline errar a
CONTAGEM de falantes, é errar QUEM fala em cada trecho.

**Overlap detection já ativo:** inspecionado o pipeline instanciado —
`embedding_exclude_overlap = True` (default), ou seja, a mitigação padrão
para fala sobreposta na extração de embedding de clustering já estava
ligada. Parâmetros de clustering default: VBx `threshold=0.6`, `Fa=0.07`,
`Fb=0.8`; `segmentation.min_duration_off=0.0` — não ajustados (fora do
escopo aprovado para esta rodada).

**Achado auxiliar:** só 1 dos 3 clusters teve mais de 1 segmento válido
(≥1.5s) disponível para gerar o embedding de identificação biométrica —
`SPEAKER_00` teve exatamente 1 candidato (1.98s), `SPEAKER_01` teve
exatamente 1 candidato (12.21s), `SPEAKER_02` teve 5. Como
`_remover_outliers` só age com ≥3 embeddings, nem `SPEAKER_00` nem
`SPEAKER_01` passaram por filtragem de outlier — mas isso é consequência
da diarização já ter misturado/fragmentado os falantes, não a causa raiz.

**Avaliação:** os dados apontam para uma limitação estrutural do modelo de
diarização diante de áudio de campo distante, ruidoso e com fala rápida
sobreposta — cenário estruturalmente mais adverso que os testes anteriores
(voz próxima, pouca sobreposição, silêncio de fundo), não um bug de
configuração corrigível trocando threshold/min-max. Não foi testado:
calibração fina de `clustering.threshold`/`Fa`/`Fb` do VBx, nem
pré-processamento (redução de ruído, normalização de volume) antes da
diarização — ambos ficaram fora do escopo desta investigação, por decisão
do usuário.

**Status:** aberta, investigação encerrada por ora sem correção aplicada.
Nenhuma mudança de comportamento foi feita — só diagnóstico. Próximo passo
(quando retomado) provavelmente exige mais dados de reuniões reais com
esse perfil de gravação (distante/ruidosa) antes de decidir entre
calibração de clustering, orientação de captura (aproximar o dispositivo)
ou aceitar a limitação como conhecida.

## Aberta — `expected_speaker_count` do job nunca vira `num_speakers` exato na diarização (bug de baixo risco, não urgente)

**Onde:** `app/services/pipeline_facade.py` (chamada a
`diarization_service.diarizar`).

**O quê:** `diarizar()` suporta `exact_speaker_count: bool = False` —
quando `True` e `expected_speaker_count` está presente, usa
`pipeline(audio_input, num_speakers=expected_speaker_count)` (contagem
exata) em vez do range `min_speakers`/`max_speakers`. Mas
`pipeline_facade.executar` chama `diarization_service.diarizar(audio_path,
transcricao, expected_speaker_count=job.expected_speaker_count)` sem
passar `exact_speaker_count=True` — então mesmo quando o app envia
`expected_speaker_count` no upload, ele hoje só vira **teto**
(`max_speakers`), nunca contagem exata. O parâmetro exato existe no
serviço mas está inacessível pelo caminho real do pipeline.

**Como foi encontrado:** durante a investigação da limitação de
diarização acima (2026-08-16), ao reproduzir manualmente
`diarizar(..., exact_speaker_count=True)` para o experimento com
`num_speakers=3`.

**Risco:** baixo — hoje o app Flutter ainda não coleta
`expected_speaker_count` na UI (fica `null` na prática), então o bug não
afeta nenhum fluxo em produção agora. Passa a importar quando essa coleta
for implementada no app.

**Correção (não aplicada agora, por decisão do usuário — só documentação
nesta rodada):** passar `exact_speaker_count=True` em `pipeline_facade.py`
quando `job.expected_speaker_count` não for `None`.

**Status:** aberta, não bloqueia fases seguintes, correção trivial quando
priorizada.

## Resolvida — Job fica congelado num estado intermediário para sempre se o servidor reiniciar durante o processamento (efeito colateral conhecido da persistência em banco)

**Onde:** `app/repositories/job_repository.py` (persistência em SQLite,
substituiu o dict em memória) + `app/services/job_executor.py` (execução
segue in-process, numa thread por job).

**O quê:** a migração de `job_repository` para SQLite (ver
`docs/BACKEND_ARCHITECTURE.md`) resolve a perda total de estado no
restart — antes, todo job em andamento simplesmente desaparecia. Mas só o
**registro** passou a sobreviver; a **execução** continua não-resiliente.
`InProcessJobExecutor` roda o pipeline numa thread do processo da API, sem
nenhum mecanismo de "quem estava processando o quê" sobrevivendo ao
processo. Se o servidor reiniciar enquanto um job está em qualquer estágio
não-terminal (`transcribing`, `diarizing`, `identifying`, `summarizing`,
`extracting`), a thread morre junto com o processo antigo — e nada no
processo novo sabe que precisa retomar, reenfileirar ou marcar erro nesse
job. O registro fica congelado no último estado alcançado antes do
restart, **indefinidamente**: um cliente fazendo polling em `/status`
nunca vai ver `done` nem `error` para esse job específico, só o mesmo
estado intermediário repetido para sempre.

**Validado empiricamente (teste manual da Fase 2 deste item):** upload
real, `kill -9` do processo com o job em `transcribing`, novo processo
apontando para o mesmo `STORAGE_ROOT`/banco — `GET /status/{job_id}`
devolveu o job intacto, mas congelado no último estado alcançado
(`extracting`, no caso testado), sem qualquer sinal de progresso ou erro
daí em diante.

**Por que não foi corrigido agora:** está fora do escopo deste item
(substituir a persistência em memória por uma real — objetivo cumprido).
Resolver de verdade — detectar jobs "órfãos" após um restart e marcá-los
como erro, ou retomar/reprocessar via workers que sobrevivem
independentemente do processo da API — é o objetivo do próximo item do
roadmap (fila real com Celery/Redis, execução resiliente). Implementar
aqui seria antecipar esse item sem a infraestrutura que o sustenta.

**Risco:** qualquer job em andamento no exato momento de um restart/deploy
em produção fica preso assim — o app cliente ficaria fazendo polling
indefinidamente num job que nunca termina, sem sinalização de erro.
Aceitável como comportamento transitório desta fase (o objetivo aqui era
parar de perder o *registro* do job, não garantir resiliência de
*execução*), mas não deve ser esquecido: todo restart em produção antes do
item 2 do roadmap corre esse risco.

**Status:** aberta, comportamento esperado e documentado — não bloqueia
esta fase, mas fica pendente até a fila real/execução resiliente (item 2
do roadmap) resolver de fato.

**Atualização — resolvida pelo item 2 (fila real com worker dedicado):**
`InProcessJobExecutor` foi removido. `/upload` não dispara mais
processamento nenhum diretamente — só grava o job (`queued`) no banco.
Quem processa é `app/worker.py`, um **processo separado** da API,
consumindo a fila via `JobRepository.next_queued()`. No boot, o worker
chama `JobRepository.requeue_orfaos()`: qualquer job num estágio
não-terminal só pode ter sido deixado por uma instância anterior do
próprio worker que morreu no meio do processamento — é reenfileirado
automaticamente (volta a `queued`), reprocessado do zero (seguro, já que
`pipeline_facade` não faz checkpoint parcial).

Proteção adicional contra "job veneno" (um job que sistematicamente
derruba o worker, ex.: um bug acionado por um áudio específico): coluna
`attempts` em `jobs`, incrementada a cada vez que o job é encontrado
órfão; excede `WORKER_MAX_ATTEMPTS_BEFORE_ERROR` (default 3) → vai direto
para `error` (`WORKER_MAX_TENTATIVAS_EXCEDIDO`) em vez de reenfileirar
para sempre.

**Validado empiricamente (teste manual do item 2):** upload real com
worker rodando; `kill -9` no worker com o job em `extracting`; novo
worker aponta pro mesmo banco, loga `"1 job(s) órfão(s) ... tratado(s)"`,
reenfileira e reprocessa do zero — job chega a `done`, com `attempts=1`
preservado (evidência de que passou pela recuperação). API derrubada no
meio do processamento não afeta o worker (processos independentes).

Tecnologia: fila no próprio SQLite (reaproveita o banco do item 1), não
Celery/Redis — decisão deliberada, ver `docs/BACKEND_ARCHITECTURE.md`
§3.8/§11 para o raciocínio completo (pipeline GPU-bound, um único worker
dedicado por servidor simplifica o problema o suficiente para não
justificar um broker externo). Teto conhecido: não escala entre máquinas
diferentes (SQLite não é seguro em filesystem compartilhado) — migraria
para Postgres ou um broker real se isso um dia for necessário.

**Status final:** resolvida. Job não fica mais congelado indefinidamente
em nenhum cenário testado (restart da API, crash do worker, job veneno).

## Resolvida — `STORAGE_ROOT` relativo dependia do cwd do processo, arriscando divergência silenciosa entre API e worker

**Onde:** `app/config.py` (`Settings.storage_root`, `SettingsConfigDict.env_file`).

**O quê:** `STORAGE_ROOT` (default `./storage`) era lido como string crua,
sem nunca ser resolvido para caminho absoluto — quem consumia
(`Path(get_settings().storage_root)`, em `app/api/participants.py`,
`app/services/voice_service.py`, `app/services/job_runner.py`) construía
um `Path` relativo, que `pathlib`/SQLAlchemy só resolvem contra
`os.getcwd()` no momento real do I/O, não na criação do objeto. Na
prática, cada processo fixava sua resolução no cwd que tinha *quando foi
iniciado*.

**Por que ficou mais urgente depois do item 2 (fila real com worker
dedicado):** antes, só a API tocava o storage — um cwd "errado" era
inofensivo, só existia um processo pra importar. Desde o worker dedicado
(`app/worker.py`, processo separado), API e worker precisam concordar
sobre onde o storage está fisicamente. Se um dos dois iniciasse de um cwd
diferente (erro de configuração no systemd, alguém rodando um dos dois
manualmente de outra pasta), os dois passariam a operar sobre diretórios
físicos diferentes — silenciosamente, sem erro, só arquivos "sumindo" da
perspectiva de um processo e não do outro. O `DATABASE_URL` default
(`sqlite:///<STORAGE_ROOT>/jobs.db`) sofreria o mesmo problema, por
derivar de `STORAGE_ROOT`.

**Correção:** `field_validator` em `storage_root` (`app/config.py`) —
valor relativo é ancorado em `_PROJECT_ROOT`
(`Path(__file__).resolve().parent.parent`, fixo, nunca o cwd do
processo); valor já absoluto passa direto, sem normalizar (não mexe em
symlink de quem já configura caminho absoluto de propósito, ex.:
produção). `database_url_efetivo` herdou a correção de graça, por
derivar de `storage_root` já resolvido.

**Achado durante a verificação manual deste item, incluído na mesma
correção:** `env_file=".env"` do `SettingsConfigDict` tinha exatamente a
mesma fragilidade — testado na prática, rodando a partir de `/tmp`,
`HF_TOKEN` voltava vazio (`''`) em vez do valor real, silenciosamente, sem
erro. Potencialmente pior que o problema original: se API e worker
divergissem de cwd, um deles poderia subir com **todas** as configs em
default, não só o storage — incluindo `JWT_SECRET_KEY` vazio, quebrando
autenticação só na hora de assinar/validar um token. Corrigido com o
mesmo padrão (`env_file=str(_PROJECT_ROOT / ".env")`).

**Defesa em profundidade:** mesmo com a causa raiz corrigida, API
(`app/main.py`, hook `lifespan`) e worker (`app/worker.py`, início de
`main()`) logam `STORAGE_ROOT`/`DATABASE_URL` absolutos resolvidos na
subida, mesmo formato de linha — um operador consegue notar visualmente
se os dois processos alguma vez divergirem, mesmo por uma causa nova,
ainda não prevista aqui.

**Validado:** `tests/test_config.py` (6 casos) — relativo resolve pro
mesmo absoluto trocando o cwd de fato via `monkeypatch.chdir`; absoluto
passa direto sem normalizar (`..` no meio do caminho preservado
literalmente); `env_file` é absoluto e não muda com o cwd. Verificação
manual adicional: `Settings()` instanciado com cwd em `/tmp` resolveu
`storage_root` para a raiz do repo (não `/tmp/storage`) e carregou
`HF_TOKEN` do `.env` real corretamente.

**Status:** resolvida. Ver `docs/BACKEND_ARCHITECTURE.md` §9 e §11 (item
4) para o detalhe completo.
