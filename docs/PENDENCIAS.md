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
