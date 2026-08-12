# Performance — SciTech Ear · Backend

Registro de instrumentação e medições de performance do pipeline. Diferente
de `docs/PENDENCIAS.md` (achados/decisões gerais do projeto), este arquivo é
específico para números de tempo/latência e o raciocínio por trás de
otimizações testadas — aplicadas ou revertidas.

## Contexto

Percepção relatada: queda de performance após a etapa de extração de
perguntas, mesmo com `ENABLE_IMPLICIT_QUESTIONS=false` (só explícitas
rodando). Investigação em duas fases: medir antes de otimizar (Fase 1),
depois agir só sobre o que a medição confirmou (Fase 2).

## Fase 1 — Instrumentação e medição

**Instrumentação adicionada** (sem alterar nenhum comportamento):
- `JobRecord.status_history` (`app/repositories/job_repository.py`):
  histórico de transições de status com timestamp; `stage_durations()`
  calcula segundos por estágio a partir desse histórico — não uma medição
  paralela.
- `MeetingPipelineFacade._log_duracao_por_estagio` (`pipeline_facade.py`):
  loga o breakdown por estágio ao final de todo job (sucesso ou erro).
- `question_service._chamar_ollama` ganhou `contexto` (rótulo de log) e loga
  `load_duration`/`prompt_eval_duration`/`eval_duration` (a API do Ollama
  devolve os três em nanossegundos) por chamada.

**Job de teste**: áudio sintético (TTS, `macOS say`) de 3,33 min, 2
falantes, pipeline real completo (WhisperX + pyannote + SpeechBrain +
Ollama/`qwen3:14b`), sem mocks. `ENABLE_IMPLICIT_QUESTIONS=false`.

### Tempo por estágio (job completo, 296.49s total)

| Estágio | Tempo | % do total |
|---|---|---|
| transcribing (WhisperX) | 57.23s | 19,3% |
| diarizing (pyannote) | 114.34s | 38,6% |
| identifying (SpeechBrain) | 0.71s | 0,2% |
| summarizing | 0.00s | 0% (pulado — flag confirmada) |
| extracting (Ollama, só explícitas) | 124.21s | 41,9% |

### Breakdown do Ollama — `extract_explicit_questions`

| Componente | Valor |
|---|---|
| `load_duration` | 4.75s (0.13s em chamada subsequente com modelo já quente) |
| `prompt_eval_duration` | 12.67s (2964 tokens de entrada) |
| `eval_duration` | **106.73s** (~86% da chamada) |
| `eval_count` | 2598 tokens gerados |

**Causa confirmada por medição direta** (não hipótese): uma chamada crua ao
Ollama para a mesma tarefa devolveu os campos `thinking` e `response`
separados — `thinking` (raciocínio em cadeia, em inglês) tinha 6120
caracteres (~1530 tokens estimados); `response` (o JSON final de verdade,
em português) tinha só 2093 caracteres (~523 tokens estimados). **~74% do
texto gerado era raciocínio nunca usado**, numa tarefa de varredura textual
literal ("extraia sentenças terminadas em '?'").

**Confirmado**: `_chamar_ollama` tinha `"think": True` hardcoded,
incondicional, aplicado a toda chamada — inclusive `extract_explicit_questions`.

**Fora do escopo desta rodada**: `diarizing` (114s) é quase tão caro quanto
`extracting` — maior estágio isolado depois de extracting. Não investigado
aqui por decisão explícita (fica para uma rodada futura).

## Fase 2 — think=False só para extract_explicit_questions: TESTADO E REVERTIDO

**Mudança tentada**: `_chamar_ollama` ganhou parâmetro `think: bool = True`;
`extract_explicit_questions` passou a chamar com `think=False` (única
chamada alterada — sumarização/implícitas mantidas em `think=True`).

**Teste antes/depois**: mesma transcrição já persistida (mesmo job da Fase
1, sem re-rodar WhisperX/pyannote/SpeechBrain), duas chamadas reais ao
Ollama com o mesmo prompt — uma com `think=True`, outra com `think=False`.

| | think=True (antes) | think=False (depois) |
|---|---|---|
| Tempo | 107.54s | 24.42s |
| `eval_duration` | 107.25s (2598 tokens) | 24.13s (596 tokens) |
| Perguntas extraídas | 5 | 5 |

Ganho de tempo bruto: **83.12s, 77.3% mais rápido** — confirma a hipótese
sobre a causa da lentidão.

**Mas o conteúdo NÃO foi idêntico.** Comparação campo a campo contra o
ground truth (texto real transcrito pelo WhisperX):

| Segmento real | Termina em "?" | think=True extraiu? | think=False extraiu? |
|---|---|---|---|
| seg_0002: "Vamos começar revisando o que ficou pendente da última vez." | **não** | não (correto) | **sim (falso positivo)** |
| seg_0026: "O modelo estava inventando perguntas sobre assuntos que nunca foram discutidos na reunião, certo?" | **sim** | sim (correto) | **não (falso negativo)** |
| seg_0006, seg_0013, seg_0018, seg_0030 | sim | sim | sim |

Com `think=False`, a extração:
1. **Perdeu uma pergunta genuína** (seg_0026, termina em "?", deveria ter
   sido extraída pela regra estrita do prompt).
2. **Ganhou uma frase que não é pergunta** (seg_0002, termina em ".", não
   deveria ter sido extraída).

2 de 5 itens errados (40% de erro de conteúdo nesta amostra) — mesmo com
`temperature=0`/`seed=42`. Desligar `think` não é só "mais rápido com o
mesmo resultado": muda a trajetória de geração do modelo o suficiente para
piorar a fidelidade da regra de extração nesta tarefa específica, apesar de
parecer (à primeira vista) uma tarefa puramente mecânica.

**Decisão**: revertido. `extract_explicit_questions` continua com
`think=True` (o parâmetro `think` em `_chamar_ollama` foi mantido — é
infraestrutura inofensiva, default `True`, não muda nada em produção — só
o *uso* dele com `False` foi revertido). Testes em
`tests/test_question_service.py::test_extract_explicit_questions_mantem_think_ligado`
travam isso explicitamente, com o motivo no docstring, para não ser
"consertado" de volta para `False` sem repetir esta validação.

### Amostra única — limitação desta validação

Este teste rodou **uma vez** com **uma transcrição sintética**. Não dá para
descartar que o resultado dependa dessa transcrição específica ou que
`think=False` funcione melhor/pior em outras reuniões. Antes de reconsiderar
qualquer variação desta mudança, recomenda-se repetir com pelo menos 2-3
transcrições reais/diferentes.

### Possíveis direções futuras (não implementadas, não avaliadas ainda)

- Manter `think=True` mas restringir `num_predict` do bloco de raciocínio
  (se o Ollama/modelo suportar) para limitar o custo sem eliminar o
  raciocínio.
- Reforçar o prompt de explícitas para reduzir a tendência do modelo a
  "pensar" tanto (não teria o mesmo ganho de `eval_duration`, já que o
  `think` continuaria ligado, mas é uma alternativa mais conservadora).
- Investigar se um modelo menor (`qwen3:4b`) mantém a fidelidade da regra
  estrita para explícitas com `think=True` mais rápido — não testado aqui.
- `keep_alive` do Ollama: não parece ser o gargalo principal nesta máquina
  (`load_duration` já era baixo), mas vale confirmar com um processo
  realmente frio antes de descartar.

## Status atual

`extract_explicit_questions` continua com `think=True`, sem mudança de
comportamento em relação ao início desta investigação. A instrumentação
(Fase 1) permanece ativa em produção — não tem custo relevante e é o que
permite qualquer próxima tentativa de otimização ser medida, não adivinhada.
