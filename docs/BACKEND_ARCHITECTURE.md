# SciTech Ear — Arquitetura do Backend

> Complementa o [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) (visão geral do
> sistema). Este documento detalha só o repositório `scitechear-backend`.

## Visão em camadas

![Arquitetura em camadas do backend](diagrams/02-backend-layers.svg)

O backend segue uma separação estrita de responsabilidades, de cima para
baixo: **API → Services → Repositories → Models**, com `legacy/` e
`prompts/` como diretórios de apoio fora dessa cadeia.

### `app/api` — camada HTTP

| Arquivo | Rotas | Responsabilidade |
|---|---|---|
| `jobs.py` | `POST /upload`, `GET /status/{id}`, `GET /resultado/{id}`, `WS /ws/{id}` | Ciclo de vida do job de processamento. |
| `participants.py` | `POST/GET/DELETE /participants/{id}/voice-*` | Cadastro e consulta do perfil de voz. |
| `health.py` | `GET /health`, `GET /ready` | `/health` não carrega modelos; `/ready` verifica dependências reais (Ollama alcançável, `HF_TOKEN` presente). |
| `main.py` | — | Bootstrap do FastAPI, CORS, registro dos routers. |

### `app/services` — lógica de domínio

| Serviço | Responsabilidade | Observação |
|---|---|---|
| `transcription_service.py` | Transcrição via WhisperX (modelo `turbo`, `pt`, alinhamento por palavra). | Porta de `legacy/notebooks/transcricao.ipynb`, sem Colab/Drive. |
| `diarization_service.py` | Diarização via pyannote — agrupa a fala em clusters (`SPEAKER_00`, …). | Lê o áudio como `{"waveform": tensor, "sample_rate": sr}` via `soundfile`, **não depende de `torchcodec`**. Limites de falantes configuráveis (`DIARIZATION_MIN_SPEAKERS`/`MAX_SPEAKERS`); `expected_speaker_count` é usado como pista, nunca como valor fixo. |
| `voice_service.py` | Extração de embeddings (SpeechBrain ECAPA-TDNN) e identificação por similaridade de cosseno. | Mesmo ponto de entrada usado no cadastro e na identificação, para evitar embeddings incompatíveis. Thresholds calibráveis: identificação, margem mínima, outlier. |
| `voice_enrollment_service.py` | Cadastro/atualização do perfil de voz de um participante. | Recalcula o embedding consolidado a partir de **todas** as amostras salvas a cada nova amostra — nunca incremental. |
| `voice_migration.py` | Utilitário não destrutivo para migrar o banco de vozes legado (por nome) para `participant_id`. | Nunca apaga os originais em `legacy/banco_vozes/`. |
| `transcript_formatter.py` | Converte segmentos diarizados em linhas estáveis para os prompts, mantendo um mapa linha → segmento. | Identidade (`speaker`/`participant_id`/`time`) é sempre resolvida por este mapa — **nunca pelo texto que o LLM devolve**. |
| `question_service.py` | Orquestra as chamadas ao Ollama: sumarização → perguntas explícitas → perguntas implícitas (+ refinamento opcional). | Usa os prompts versionados em `prompts/`. Perguntas explícitas preservam o texto literal do segmento; implícitas nunca têm campos de identidade inventados. |
| `pipeline_facade.py` | `MeetingPipelineFacade` — orquestra as 7 etapas em ordem para um job. | Atualiza o status real em cada estágio; consolida o `MeetingResult` final. |
| `job_executor.py` | Executa o pipeline em uma thread de background por job. | Interface já preparada para uma fila real (Celery/Redis) no futuro, sem acoplar as rotas a essa decisão. |

### `app/repositories` — persistência

Abstraem o armazenamento em disco (sem depender de nuvem):

- `job_repository.py` — estado do job em memória (processo único).
- `result_repository.py` — resultado final, persistido como JSON.
- `storage_repository.py` — artefatos por job em `storage/jobs/<job_id>/`.
- `voice_repository.py` — perfis de voz em `storage/voices/<participant_id>/`.

### `app/models` — contrato canônico

Schemas Pydantic que definem o formato de troca com o cliente:
`participant.py`, `job.py` (os 8 estados), `result.py`
(`TranscriptSegment`, `Question`, `MeetingResult`, `ResultMetadata`). Ver o
contrato completo em [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md#4-contrato-de-dados-canônico).

## `legacy/` — protótipos originais, só como referência

Contém o código validado antes da integração — **nunca executado em
produção**:

- `notebooks/` — `transcricao.ipynb`, `diarizacao.ipynb`, `llm.ipynb`, que
  usam Google Colab/Drive.
- `scripts/` — `etapa2b_diarizacao.py`, `etapa3_biometria.py`,
  `cadastro_vozes.py`, `pipeline.py`, versões em script dos mesmos
  algoritmos.
- `banco_vozes/` — estrutura do banco de vozes legado, indexado por nome
  (substituído por `VoiceRepository`, indexado por `participant_id`).

## `prompts/` — prompts de LLM versionados

| Arquivo | Uso |
|---|---|
| `explicit_questions_v4.json` | Extrai apenas sentenças terminadas em `?`, literalmente. |
| `meeting_summary_v1.txt` | Sumarização estruturada da reunião (artefato interno). |
| `implicit_questions_v3.txt` | Perguntas implícitas em **JSON** (evolução do v2, que produzia texto puro — critérios semânticos preservados). |
| `implicit_refiner_v1.txt` | Refinamento das perguntas implícitas — **desativado por padrão** (`ENABLE_IMPLICIT_REFINEMENT=false`). |

## Pendências de calibração

Achados que não bloqueiam a arquitetura, mas precisam de acompanhamento
(modelo, thresholds) ficam registrados em `docs/PENDENCIAS.md` — por
exemplo, o comportamento de modelos menores do Ollama nem sempre respeitar
à risca o formato pedido no prompt de perguntas explícitas.

## Variáveis de ambiente

Ver `.env.example` na raiz para a lista completa. As mais relevantes para a
arquitetura:

```env
HF_TOKEN=                          # obrigatório para o pyannote (modelo gated)
STORAGE_ROOT=./storage
WHISPERX_MODEL=turbo
DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
DIARIZATION_MIN_SPEAKERS=1
DIARIZATION_MAX_SPEAKERS=10
VOICE_MODEL=speechbrain/spkrec-ecapa-voxceleb
VOICE_IDENTIFICATION_THRESHOLD=0.30
VOICE_MIN_MARGIN=0.05
VOICE_OUTLIER_THRESHOLD=0.45
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:14b
ENABLE_IMPLICIT_REFINEMENT=false
DEMO_MODE=false
```

## Escopo da V1

Backend Python convencional, portável para Linux/GPU. Fila real
(Celery/Redis) e WebSocket de push nativo ficam para depois da V1 — a
interface já foi desenhada para acomodá-los sem reescrever as rotas.
