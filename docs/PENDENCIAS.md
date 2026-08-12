# Pendências — SciTech Ear · Backend

Registro vivo de achados que não bloqueiam a fase corrente, mas precisam de
acompanhamento — calibração de prompt/modelo, comportamento a reverificar
antes de considerar algo definitivamente resolvido, etc. Diferente de
`docs/BASELINE.md` (retrato pontual da Fase 0): este arquivo é atualizado ao
longo do projeto.

## Aberta — Perguntas explícitas: prefixo `[Nome]: ` vazando no campo `text`

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
existentes (regra do CLAUDE.md).

**Status:** aberta, não bloqueia fases seguintes.

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
