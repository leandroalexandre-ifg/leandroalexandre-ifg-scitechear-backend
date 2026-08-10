# SciTech Ear — Backend

Backend Python/IA do SciTech Ear: recebe o áudio de uma reunião, transcreve
(WhisperX), separa os falantes (pyannote), identifica quem é cada um por
biometria de voz (SpeechBrain ECAPA) e extrai as perguntas explícitas e
implícitas (LLM via Ollama). Expõe uma API FastAPI consumida pelo app Flutter,
que vive em um repositório separado.

## Fonte de verdade

`SciTech_Ear_Especificacao_Final_Implementacao_Claude.docx` (na raiz) é o contrato
de implementação. `CLAUDE.md` resume as regras que valem em toda sessão do
Claude Code. O plano de execução por fases está em `docs/PLANO_CLAUDE_CODE.md`.

## Estrutura

    app/            # aplicação (a implementar): api, models, services, repositories
    prompts/        # prompts de LLM versionados
    legacy/         # protótipos originais (notebooks + scripts) — NÃO executar em produção
      notebooks/    # transcricao / diarizacao / llm (usam Colab/Drive; só referência)
      scripts/      # etapa2b_diarizacao, etapa3_biometria, cadastro_vozes, pipeline
      banco_vozes/  # banco legado (não versionado; será recriado por participant_id)
    storage/        # artefatos por job (dev/teste; não versionado)
    tests/          # testes
    docs/           # baseline, plano de execução

## Primeiros passos

1. `cp .env.example .env` e preencha o `HF_TOKEN`.
2. Python **3.13** (via `brew install python@3.13`): `python3.13 -m venv .venv &&
   source .venv/bin/activate && pip install -r requirements.txt`. WhisperX,
   pyannote.audio e SpeechBrain exigem Python 3.10+; 3.13 já vinha instalado
   via Homebrew neste Mac e tem wheels prontos para todo o stack (torch,
   torchaudio, ctranslate2, numba) — ver decisão registrada no relatório da
   Fase 2.
3. FFmpeg (necessário para `whisperx.load_audio`, que chama o binário `ffmpeg`
   via subprocess): `brew install ffmpeg`.
4. ~~`ffmpeg@7` + `DYLD_FALLBACK_LIBRARY_PATH` para o `torchcodec` do
   pyannote~~ — **obsoleto**, não é mais necessário. `diarization_service.py`
   carrega o áudio via `soundfile` e passa `{"waveform": tensor,
   "sample_rate": sr}` para o pipeline do pyannote, em vez do caminho do
   arquivo — isso evita completamente o `pyannote.audio.core.io.Audio`
   precisar do `torchcodec` para ler o WAV (mesma abordagem já usada em
   `voice_service.py` desde a Fase 2). Um job real rodado sem
   `DYLD_FALLBACK_LIBRARY_PATH` setado confirmou que a diarização completa
   normalmente. Se `brew install ffmpeg@7` já tiver sido feito antes, pode
   remover (`brew uninstall ffmpeg@7`) — nada mais depende dele.
5. Trabalhe em uma branch de integração (nunca na `main`).
6. Siga a ordem de fases de `docs/PLANO_CLAUDE_CODE.md`. Os serviços em
   `app/services/` são extraídos dos protótipos em `legacy/`.

## Regras que não mudam

Cliente fino no app; a API é a única fronteira; identidade de falante é do
backend (biometria), nunca por posição; `participant_id` é a chave; erro real
nunca vira resultado fictício; nada de Colab/Drive no caminho de execução;
segredos só via ambiente. Detalhes no `CLAUDE.md` e na especificação.

## Arquitetura

Documentação completa da arquitetura, com diagramas, em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (visão geral do sistema) e [`docs/BACKEND_ARCHITECTURE.md`](docs/BACKEND_ARCHITECTURE.md) (camadas, serviços, repositórios e legado deste repositório).

![Contexto geral do sistema](docs/diagrams/01-system-context.svg)

| Documento | Conteúdo |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Contexto geral, máquina de estados do job, sequência ponta a ponta, contrato de dados |
| [`docs/BACKEND_ARCHITECTURE.md`](docs/BACKEND_ARCHITECTURE.md) | Camadas (API/Services/Repositories/Models), `legacy/`, `prompts/` |
| [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md) | Pendências de calibração em acompanhamento |
