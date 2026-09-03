# AGENTS.md — SciTech Ear · Backend

Este arquivo define como trabalhar **no repositório do backend**
do SciTech Ear. Leia-o por completo
antes de editar qualquer arquivo. O frontend Flutter vive em um repositório separado.

## Fonte de verdade

O documento **`SciTech_Ear_Especificacao_Final_Implementacao.docx`**
(na raiz deste repositório) é o contrato de implementação. Quando a documentação
antiga divergir do código real, siga as decisões consolidadas desse documento.

Os protótipos originais do backend (notebooks e scripts já validados —
`transcricao.ipynb`, `etapa2b_diarizacao.py`, `etapa3_biometria.py`,
`cadastro_vozes.py`, `pipeline.py`, `banco_vozes/`) ficam na pasta **`legacy/`**
deste repositório e são a fonte a partir da qual os serviços em `app/services/`
serão extraídos. Não os execute em produção/testes integrados; servem para
rastreabilidade e extração. Antes de propor mudanças, leia integralmente a
especificação e o conteúdo de `legacy/`, e registre um baseline em
`docs/BASELINE.md`.

## O que é o projeto

Integração de um **frontend Flutter** (cliente fino, já existente) com um
**backend Python/IA** (prototipado em notebooks/scripts) que transcreve o áudio
de uma reunião, identifica quem falou por biometria de voz e extrai as perguntas
discutidas. Todo o processamento de IA acontece no backend.

Pipeline do backend, em ordem:
WhisperX (transcrição + alinhamento) → pyannote (clusters de fala) →
SpeechBrain ECAPA (identidade biométrica) → formatter de transcrição →
perguntas explícitas (LLM) → sumarização (LLM) → perguntas implícitas (LLM) →
resultado canônico.

## Regras invioláveis

1. **Flutter é cliente fino.** Nenhum modelo de IA roda no dispositivo.
2. **A API é a única fronteira** entre frontend e backend.
3. **Identidade de falante é do backend, via biometria.** NUNCA mapear
   `SPEAKER_00` para participante por posição/ordem no Flutter.
4. **`participant_id` estável é a chave** entre frontend e backend. O nome é
   apenas atributo de exibição, nunca chave nem caminho de arquivo.
5. **Erro real do backend NUNCA vira resultado fictício.** Modo demo só quando
   `DEMO_MODE=true`, de forma explícita. Falhas devem ser exibidas ao usuário.
6. **Nada de `google.colab`, Google Drive ou `/content/drive`** no caminho de
   execução da aplicação. Colab, se usado, é só runtime temporário de GPU
   (launcher que instala deps, sobe Ollama/FastAPI e abre túnel); nenhum
   algoritmo vive nele.
7. **Segredos só via variável de ambiente** (HF_TOKEN etc.). Nunca no código
   versionado.
8. **Preserve UI e algoritmos já validados.** Refatore só o necessário para
   integrar. Não introduza frameworks nem refatorações que a spec não exige.
9. **Preserve os prompts de LLM semanticamente.** Mudança de formato deve ser
   mínima e versionada (ex.: migrar a saída para JSON sem alterar critérios
   semânticos do prompt).
10. **Integração ponta a ponta primeiro, otimização depois.** Não troque
    modelos nem adicione fila/caching antes de ter um E2E funcional e testes de
    regressão.

## Separações que não podem ser violadas

- **Diarização ≠ biometria.** pyannote produz *cluster* de fala (`SPEAKER_00`);
  SpeechBrain identifica a *pessoa* (`participant_id`). São campos distintos no
  resultado. Falante não identificado permanece como cluster — sem associação
  posicional.
- **Score não entra no nome.** Nunca retornar `"Leandro (0.82)"` no campo
  `speaker`. Use campos separados: `cluster`, `participant_id`, `speaker`,
  `identified`, `confidence`.
- **Enrollment de voz é uma vez por participante**, não a cada reunião. As
  reuniões referenciam `participant_id`; amostras não são reenviadas sempre.

## Escopo da V1

- **Android apenas** (Android Emulator no Mac). iOS é preservado no repositório,
  mas não é critério de aceite desta fase.
- **Backend Python convencional**, sem lógica de negócio em notebooks.
- Portável entre ambientes Linux/GPU; nenhum provedor de nuvem pode contaminar
  os serviços de domínio.

## Contrato HTTP (rotas exatas que o Flutter já chama)

| Método | Rota | Função |
|---|---|---|
| POST | `/participants/{participant_id}/voice-samples` | Cadastrar/atualizar amostra de voz; (re)calcula embedding. |
| GET | `/participants/{participant_id}/voice-profile` | Diagnóstico do perfil biométrico. |
| DELETE | `/participants/{participant_id}/voice-profile` | Excluir perfil biométrico. |
| POST | `/upload` | Criar job. Multipart: `file` (WAV 16 kHz mono), `title?`, `participants` JSON, `expected_speaker_count?`. Retorna **202** + `job_id`. |
| GET | `/status/{job_id}` | Status e estágio atual. |
| WS | `/ws/{job_id}` | Progresso em tempo real. Opcional no início; **polling é fallback obrigatório**. |
| GET | `/resultado/{job_id}` | Resultado final canônico. |
| GET | `/health` | Saúde da API; **não carrega modelos**. |
| GET | `/ready` | Prontidão de worker/modelos/GPU. |

**Estados do job (exatos):** `queued`, `transcribing`, `diarizing`,
`identifying`, `summarizing`, `extracting`, `done`, `error`.

**Resultado canônico:** `segments[]` com
`id, cluster, participant_id, speaker, identified, confidence, start, end, text`;
`questions[]` com `id, type (explicit|implicit), text, participant_id?,
speaker?, time?, source_segment_ids[]`; e `metadata{}` com as versões de modelo.
Perguntas implícitas podem ter `participant_id/speaker/time` nulos.

## Método de trabalho

- Trabalhe em uma **branch de integração**; nunca altere `main` diretamente.
- **Commits pequenos por fase.** Ao final de cada fase, rode os testes e entregue:
  (a) arquivos alterados, (b) decisões tomadas, (c) pendências. Aguarde OK antes
  de avançar de fase.
- Ao mover scripts/notebooks para `legacy/`, faça **depois** de extrair o serviço
  equivalente. **Nunca apague as fontes originais.**
- Faça mudanças pequenas e verificáveis. Prefira testes de contrato com fixtures
  a rodar GPU no ciclo de desenvolvimento.

## Ordem de implementação

Contrato **antes** do pipeline. A sequência de fases é:
0. Preparação e baseline · 1. Schemas + contrato HTTP (com fixture) ·
2. Biometria (`VoiceRepository` + enrollment por `participant_id`) ·
3. `TranscriptionService` (WhisperX) · 4. Diarização + biometria desacopladas ·
5. Formatter + `QuestionService` · 6. `PipelineFacade` + estados ·
7. Ajustes no Flutter (remover mapeamento posicional e fallback demo) ·
8. E2E no Android Emulator; só então WebSocket e otimizações.

## Configuração por ambiente

Todas as variáveis vêm de `.env` (ver `.env.example`). Mínimas:

```env
HF_TOKEN=
STORAGE_ROOT=./storage
WHISPERX_MODEL=turbo
WHISPERX_LANGUAGE=pt
WHISPERX_BATCH_SIZE=16
DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
VOICE_MODEL=speechbrain/spkrec-ecapa-voxceleb
VOICE_IDENTIFICATION_THRESHOLD=0.30
VOICE_MIN_MARGIN=0.05
VOICE_OUTLIER_THRESHOLD=0.45
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:14b
ENABLE_IMPLICIT_REFINEMENT=false
DEMO_MODE=false
```

Flutter (Android Emulator no Mac) recebe a base URL por `--dart-define`
(`SCITECH_API_BASE_URL`, `SCITECH_WS_BASE_URL`); default `10.0.2.2:8000`. Em
runtime remoto/túnel, apenas os `dart-define` mudam.

## Pontos calibráveis (não bloqueiam a V1)

Thresholds de voz, min/max de falantes, peso do Qwen3 14B no runtime gratuito e
a escolha futura de fila (Celery/Redis ou equivalente) são calibráveis e **não
devem bloquear** o E2E inicial. Autenticação real e produção iOS ficam fora do
critério de aceite da V1.

## Definição de pronto da V1

No Android Emulator do Mac, um usuário consegue: cadastrar participantes,
sincronizar amostras de voz uma vez, gravar uma reunião em WAV 16 kHz mono,
enviar ao backend Python (em runtime com GPU), acompanhar o job, receber
transcrição diarizada com identificação biométrica quando confiável e visualizar
perguntas explícitas e implícitas reais — sem troca manual de arquivos, sem
Google Drive como barramento e sem fallback fictício ocultando falhas.
