# BASELINE — SciTech Ear · Backend

Registrado em 2026-08-09, branch `feat/estrutura-inicial`, antes do início da Fase 1.
Baseado na leitura integral de `SciTech_Ear_Especificacao_Final_Implementacao_Claude.docx`,
`CLAUDE.md`, `docs/PLANO_CLAUDE_CODE.md`, `legacy/` e `prompts/`.

## O que já existe

### Estrutura (`app/`)
Só pacotes vazios (`__init__.py`) em `app/`, `app/api/`, `app/models/`,
`app/services/`, `app/repositories/`. Nenhuma lógica implementada ainda.
Não há `app/main.py` nem `app/config.py`.

### `legacy/scripts/` (algoritmos validados a extrair)
- **`etapa2b_diarizacao.py`** — pyannote `speaker-diarization-community-1`;
  `HF_TOKEN` já vem de env (`os.environ`); carregamento do pipeline é **global no
  import** (precisa virar lazy load); `MIN_SPEAKERS=4` / `MAX_SPEAKERS=7` fixos
  (a remover, virar `expected_speaker_count`); associação segmento↔cluster por
  **maior sobreposição temporal** (preservar).
- **`etapa3_biometria.py`** — SpeechBrain `EncoderClassifier`
  (`spkrec-ecapa-voxceleb`), device cuda/cpu, `_classifier` cacheado por
  processo (lazy). Constantes: `LIMIAR_IDENTIFICACAO=0.30`,
  `MARGEM_MINIMA=0.05`, `LIMIAR_OUTLIER=0.45`. Funções-chave: `gerar_embedding`
  (cadastro), `extrair_embedding_segmento`/`extrair_embedding_concatenado`
  (reconhecimento — concatenação de trechos preferida à média), normalização
  L2, `identificar_speaker` (threshold + margem, retorna `None` se ambíguo),
  `_remover_outliers` (só atua com 3+ trechos, nunca descarta tudo),
  `aplicar_biometria` (top-5 segmentos ≥1.5s por speaker). **Problema a
  corrigir na extração para serviço**: hoje o próprio `aplicar_biometria`
  escreve `f"{nome} ({score:.2f})"` no campo `speaker` — é exatamente o
  padrão proibido pela regra "score não entra no nome"; o novo
  `voice_service.py` deve devolver campos separados.
- **`cadastro_vozes.py`** — chave atual é **nome** (pasta
  `banco_vozes/<nome>/audios/` + `embedding.pt`), recalcula a média dos
  embeddings de todas as amostras a cada cadastro/atualização (comportamento
  de consolidação a preservar, só migrando a chave para `participant_id`).
- **`pipeline.py`** — só orquestra diretórios (`audios_brutos/`,
  `transcricoes/`, `banco_vozes/`, `resultados/`); assume que a transcrição
  já existe em JSON; chama `diarizar()` → `aplicar_biometria()` → salva JSON.
  Não chama WhisperX nem LLM. É o modelo para `pipeline_facade.py`, mas
  precisa passar a receber um job único (não varrer diretório).

### `legacy/notebooks/` (referência, nunca executar)
- **`transcricao.ipynb`** — WhisperX: `model_size="turbo"`, `language="pt"`,
  `batch_size=16`, `device=cuda/cpu`, `compute_type=float16/int8`; usa
  `whisperx.load_audio` (aceita qualquer formato/SR, reamostra internamente),
  `whisperx.load_model` → `transcribe` → libera memória → `load_align_model` →
  `align` (preserva `words` com score). Usa **Google Drive** (`drive.mount`)
  e paths `/content/drive/...` — tudo isso deve ser removido na extração para
  `transcription_service.py`. JSON de saída já tem forma próxima do contrato:
  `metadata{}` + `segments[]{id,start,end,text,words[]}`.
- **`diarizacao.ipynb`** — orquestra Drive, upload manual de arquivos, chama
  `cadastrar_ou_atualizar_pessoa` e depois `!python scripts/pipeline.py`. Usa
  `google.colab.userdata` para o `HF_TOKEN` (o script `.py` já usa env var
  puro, que é o padrão correto a seguir). Confirma que o pipeline real hoje
  é 100% manual/Drive-driven — nenhuma lógica nova aqui além dos scripts já
  lidos.
- **`llm.ipynb`** — instala Ollama, `ollama pull qwen3:14b`, e roda 4 chamadas
  sequenciais a `POST /api/generate` (`temperature=0, top_p=1, top_k=1,
  repeat_penalty=1.0, num_ctx=32768, seed=42, think=true`): explícitas
  (`PromptDeExtracaoDePerguntasExplicitasV4.json`) → parseia `response` como
  JSON; sumarização (`PromptSumarizacaoV1.txt`) → texto puro; implícitas
  (`PromptGerador.txt`, usa sumarização + transcrição) → texto numerado, não
  JSON; refinamento (`PromptRefinadorPerguntas.txt`) → texto, hoje não
  ligado a nada (standby confirmado pela spec). Tudo via arquivos de
  passagem (`.txt`/`.json` no filesystem local do runtime) — é o padrão a
  substituir por chamadas em memória no `question_service.py`.

### `prompts/` (já versionados, preservar semanticamente)
- `explicit_questions_v4.json` — regra estrita: só sentenças terminando em
  `?`, cópia literal, sem correção; já pede JSON estruturado
  (`perguntas[]{id,pergunta,falante,linha_transcricao,segmentos_anteriores}`)
  e `linha_transcricao` referencia a numeração de linha que o
  `TranscriptFormatter` (a criar) precisa produzir.
- `meeting_summary_v1.txt` — saída estruturada em texto (não JSON), muitas
  categorias com prefixos de ID fixos (P, PE, T, RSP, PR, F, D, ...); artefato
  interno, não é contrato do Flutter — pode continuar texto na V1.
- `implicit_questions_v2.txt` — hoje produz **lista numerada em texto puro**,
  sem JSON, sem speaker/time. É o prompt que a spec manda versionar para
  saída JSON estruturada (`type=implicit`, campos opcionais) **sem alterar os
  critérios semânticos** (máx. 15, não inventar fatos, etc.).
- `implicit_refiner_v1.txt` — existe mas fica em standby
  (`ENABLE_IMPLICIT_REFINEMENT=false`); não plugar no caminho padrão da V1.

### Configuração e infraestrutura de repositório
- `.env` (não versionado) e `.env.example` já têm todas as variáveis da spec
  (`HF_TOKEN`, `STORAGE_ROOT`, `WHISPERX_*`, `DIARIZATION_MODEL`,
  `VOICE_MODEL`, `VOICE_*_THRESHOLD`, `OLLAMA_*`,
  `ENABLE_IMPLICIT_REFINEMENT=false`, `DEMO_MODE=false`).
- `.gitignore`, `storage/` (só `.gitkeep`), `tests/` (vazio), `README.md` e
  `CLAUDE.md` já refletem a arquitetura alvo.
- `docs/CLAUDE_frontend_referencia.md` — cópia do CLAUDE.md do repositório
  Flutter (separado), útil como referência do contrato do lado cliente; não
  precisa ser editado aqui.

## O que falta implementar (por fase, conforme `docs/PLANO_CLAUDE_CODE.md`)

- **Fase 1** — schemas Pydantic do contrato canônico, `app/config.py`,
  `app/api/{jobs,participants,health}.py`, `app/main.py`; `/resultado`
  devolvendo fixture válido (sem IA ainda).
- **Fase 2** — `VoiceRepository` (chave `participant_id`),
  `voice_enrollment_service.py` extraído de `cadastro_vozes.py`, endpoints de
  voz ligados de verdade, utilitário de migração nome→id não destrutivo.
- **Fase 3** — `transcription_service.py` extraído de `transcricao.ipynb`,
  sem Colab/Drive, com teste de contrato via fixture.
- **Fase 4** — `diarization_service.py` (lazy load, sem 4/7 fixos) e
  `voice_service.py` (campos separados, sem score no nome) extraídos dos
  scripts já lidos.
- **Fase 5** — `transcript_formatter.py` (mapa linha→segmento) e
  `question_service.py` (Ollama, explícitas/sumarização/implícitas,
  implícitas em JSON, refinamento e RAG fora do caminho padrão).
- **Fase 6** — `pipeline_facade.py` orquestrando as 7 etapas por job, com
  repositories desacoplados do filesystem.
- **Fase 7** — ajustes no Flutter (repositório separado): remoção de
  fallback demo automático e do mapeamento posicional `SPEAKER_N`.
- **Fase 8** — E2E no Android Emulator; só então WebSocket real e
  otimizações; mover scripts/notebooks para `legacy/` só depois de os
  serviços equivalentes existirem (já estão lá desde o início deste repo,
  então esse passo já está coberto — não é destrutivo, os originais
  permanecem).

Nenhum arquivo de `app/`, `legacy/` ou `prompts/` foi alterado nesta etapa —
apenas leitura e este registro de baseline.
