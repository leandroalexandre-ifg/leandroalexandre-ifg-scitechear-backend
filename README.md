# SciTech Ear — Backend

Backend Python/IA do SciTech Ear: recebe o áudio de uma reunião, transcreve
(WhisperX), separa os falantes (pyannote), identifica quem é cada um por
biometria de voz (SpeechBrain ECAPA) e extrai as perguntas explícitas e
implícitas (LLM via Ollama). Expõe uma API FastAPI consumida pelo app Flutter,
que vive em um repositório separado.

## Fonte de verdade

`SciTech_Ear_Especificacao_Final_Implementacao.docx` (na raiz) é o contrato
de implementação. `AGENTS.md` resume as regras que valem em todo o desenvolvimento.
O plano de execução por fases está em `docs/PLANO_EXECUCAO.md`.

## Estrutura

    app/
      main.py       # a API FastAPI
      worker.py     # processo separado que consome a fila e roda o pipeline na GPU
      config.py     # Pydantic Settings (lê o .env)
      api/          # rotas: auth, jobs (upload/status/resultado/ws), participants, health
      models/       # contrato canônico: job, participant, result, user
      services/     # transcrição, diarização, biometria, perguntas, pipeline_facade, auth
      repositories/ # job (SQLite), result, storage, user, voice
    prompts/        # prompts de LLM versionados
    legacy/         # protótipos originais (notebooks + scripts) — NÃO executar em produção
      notebooks/    # transcricao / diarizacao / llm (usam Colab/Drive; só referência)
      scripts/      # etapa2b_diarizacao, etapa3_biometria, cadastro_vozes, pipeline
      banco_vozes/  # banco legado (não versionado; recriado por participant_id)
    storage/        # artefatos por job (dev/teste; não versionado)
    tests/          # testes
    docs/           # arquitetura, deploy, pendências, E2E, performance

## Primeiros passos

1. `cp .env.example .env` e preencha o `HF_TOKEN`.
2. Python **3.12** (o que está fixado em `.python-version`, e o que o servidor
   de deploy tem): `python3.12 -m venv .venv && source .venv/bin/activate &&
   pip install -r requirements.txt`. WhisperX, pyannote.audio e SpeechBrain
   exigem Python 3.10+. O desenvolvimento começou em 3.13 num Mac (ver o
   relatório da Fase 2), mas o alvo passou a ser o 3.12 do Ubuntu 24.04 do
   NumbERS — todo o stack (torch, torchaudio, ctranslate2, numba) tem wheels
   prontos nas duas versões.
3. FFmpeg (necessário para `whisperx.load_audio`, que chama o binário `ffmpeg`
   via subprocess): `apt install ffmpeg` no Linux, `brew install ffmpeg` no
   Mac.
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
5. Trabalhe em uma branch de integração (nunca na `main`). **No servidor de
   deploy isso tem uma consequência**: as unidades systemd rodam direto do
   checkout, então a branch que estiver ativa é o que sobe no próximo restart
   — ver [`docs/DEPLOY.md`](docs/DEPLOY.md).
6. Siga a ordem de fases de `docs/PLANO_EXECUCAO.md`. As fases 0–6 e 8 estão
   feitas: os serviços em `app/services/` já foram extraídos dos protótipos em
   `legacy/`, e o backend roda de ponta a ponta no servidor (ver
   [`docs/E2E_FASE8.md`](docs/E2E_FASE8.md)). A Fase 7 — o app Flutter como
   cliente real — é o que falta.

## Regras que não mudam

Cliente fino no app; a API é a única fronteira; identidade de falante é do
backend (biometria), nunca por posição; `participant_id` é a chave; erro real
nunca vira resultado fictício; nada de Colab/Drive no caminho de execução;
segredos só via ambiente. Detalhes no `AGENTS.md` e na especificação.

## Arquitetura

Documentação completa da arquitetura — pensada para que qualquer pessoa,
mesmo sem contexto prévio do projeto, consiga entender o sistema do zero.
Inclui um glossário de termos, o raciocínio por trás de cada decisão
(não só "o quê", mas "por quê"), e diagramas do fluxo completo.

![Contexto geral do sistema](docs/diagrams/01-system-context.svg)

| Documento | Conteúdo |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Visão geral do sistema, glossário, contexto e motivação, máquina de estados do job, contrato de dados |
| [`docs/BACKEND_ARCHITECTURE.md`](docs/BACKEND_ARCHITECTURE.md) | Camadas (API/Services/Repositories/Models), cada serviço explicado, `legacy/`, `prompts/`, como rodar localmente |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Como o backend está implantado: serviços, portas, como o app alcança o backend, armadilhas conhecidas |
| [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md) | Pendências de calibração em acompanhamento |
| [`docs/E2E_FASE8.md`](docs/E2E_FASE8.md) | Relatório do E2E no servidor de deploy: cenários, identificação medida por tempo de fala, achados |
| [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) | Instrumentação e medições de tempo por estágio (Mac e servidor NumbERS) |

Se você é novo neste projeto, comece por
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — a introdução e o glossário
já dão uma visão de 80% do sistema antes de entrar nos detalhes de cada
camada.

## Rodando com o app em dispositivo físico (Android)

Ao testar o app em um tablet/celular físico via USB (ver README do frontend),
suba o backend assim:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` é necessário para o servidor aceitar conexões de fora do
`localhost`. O app se conecta via `adb reverse tcp:8000 tcp:8000` (configurado
no lado do frontend), então não é preciso descobrir o IP da máquina nem lidar
com isolamento de rede Wi-Fi entre os aparelhos.

> Isso vale para o backend rodando **na própria máquina de desenvolvimento**.
> Para alcançar o backend **implantado no servidor** (que fica em loopback, na
> porta 18080), o caminho é outro — túnel SSH sobre a VPN. Ver
> [`docs/DEPLOY.md`](docs/DEPLOY.md).
>
> O loopback lá é deliberado: o bind na rede só reabre depois de confirmada a
> regra de firewall da porta e definido um plano de TLS — hoje o tráfego é HTTP
> puro, e a rede do IFG é a `10.4.0.0/16` inteira.
