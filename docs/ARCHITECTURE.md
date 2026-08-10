# SciTech Ear — Arquitetura Geral

> Este documento descreve a arquitetura do sistema como um todo — cliente
> Flutter + backend de IA. É mantido **idêntico nos dois repositórios**
> (`scitechear` e `scitechear-backend`) para que qualquer pessoa entenda o
> sistema completo a partir de qualquer um dos dois. Detalhes específicos de
> cada lado estão em `docs/BACKEND_ARCHITECTURE.md` e
> `docs/FRONTEND_ARCHITECTURE.md`.

## O que é o SciTech Ear

Aplicativo que capta o áudio de uma reunião, transcreve a fala, identifica
quem falou por biometria de voz e extrai as perguntas discutidas —
explícitas e implícitas. O processamento de IA acontece inteiramente no
backend; o app é um **cliente fino**.

## Repositórios

| Repositório | Conteúdo | Tecnologia |
|---|---|---|
| `scitechear` | Aplicativo cliente | Flutter / Dart |
| `scitechear-backend` | API + pipeline de IA | Python / FastAPI |

## 1. Contexto geral

![Contexto geral do sistema](diagrams/01-system-context.svg)

O app grava o áudio e envia via `POST /upload` (multipart), junto com a
lista de participantes em JSON. O backend responde imediatamente com um
`job_id` (HTTP 202) e processa a reunião em segundo plano, atualizando o
estado do job a cada estágio. O app acompanha esse estado (WebSocket com
fallback de polling) e, ao final, busca o resultado canônico.

Cadastro de voz é um fluxo separado: cada participante grava uma amostra
**uma única vez** (não a cada reunião); o backend extrai o embedding dessa
amostra e o guarda associado ao `participant_id`, para uso posterior na
identificação.

## 2. Máquina de estados do job

![Máquina de estados do job](diagrams/03-job-state-machine.svg)

O job percorre exatamente estes 8 estados:

`queued → transcribing → diarizing → identifying → summarizing → extracting → done`

Qualquer falha em qualquer estágio leva a `error`, com um `code` e uma
`message` específicos. **Regra invariável do projeto:** um erro real do
backend nunca é convertido em resultado fictício pelo cliente — o app exibe
o erro e oferece repetir ou voltar. O modo demo (dados fabricados
localmente) só existe atrás de uma flag explícita de build
(`SCITECH_DEMO_MODE`), nunca como reação automática a uma falha.

## 3. Sequência ponta a ponta

![Sequência ponta a ponta](diagrams/04-pipeline-sequence.svg)

Do ponto de vista de uma reunião processada com sucesso:

1. O app envia o áudio e a lista de participantes.
2. O backend aceita o upload, cria o job e devolve o `job_id` de imediato.
3. O `job_executor` roda o `MeetingPipelineFacade` em uma thread de segundo
   plano.
4. O pipeline percorre as 7 etapas (WhisperX → pyannote → SpeechBrain →
   formatter → Ollama sumarização → Ollama perguntas explícitas → Ollama
   perguntas implícitas), atualizando o status a cada estágio.
5. O app consulta o status (WebSocket, com polling como plano B) até ver
   `done`.
6. O app busca o resultado canônico em `GET /resultado/{job_id}`.

## 4. Contrato de dados canônico

![Contrato de dados canônico](diagrams/06-data-contract.svg)

O resultado de uma reunião processada segue sempre esta forma:

```json
{
  "job_id": "…",
  "status": "done",
  "segments": [
    {
      "id": "seg_0001",
      "cluster": "SPEAKER_00",
      "participant_id": "p1",
      "speaker": "Leandro",
      "identified": true,
      "confidence": 0.836,
      "start": 0.0,
      "end": 4.2,
      "text": "Bom dia a todos."
    }
  ],
  "questions": [
    {
      "id": "P1",
      "type": "explicit",
      "text": "Qual é o prazo final para entregar a integração completa?",
      "participant_id": "p1",
      "speaker": "Leandro",
      "time": 12.5,
      "source_segment_ids": ["seg_0004"]
    }
  ],
  "metadata": { "whisperx_model": "turbo", "voice_model": "…", "…": "…" }
}
```

**Duas invariantes que nunca são violadas:**

1. `confidence` vem preenchido mesmo quando `identified: false` (rejeitado
   por threshold ou por margem) — o campo que decide identidade é sempre
   `identified`, nunca a presença de `confidence`. Isso existe para permitir
   calibrar os limiares de identificação no futuro sem perder dado.
2. Perguntas implícitas nunca têm `participant_id`, `speaker` ou `time`
   inventados — ficam `null` quando o formatter não consegue resolver a
   origem com segurança.

## 5. Decisões de arquitetura que atravessam os dois repositórios

- **Cliente fino.** Nenhum modelo de IA roda no dispositivo; a API é a
  única fronteira entre app e backend.
- **Identidade é do backend.** O cliente nunca infere quem falou por
  posição de lista — só exibe o que o backend already resolveu por
  biometria.
- **`participant_id` é a chave compartilhada**, não o nome. O nome é
  apenas atributo de exibição.
- **Erro real nunca vira resultado fictício.** Em nenhum dos dois lados.
- **Sem dependência de nuvem no caminho de execução.** Notebooks e scripts
  que usam Google Colab/Drive ficam isolados como referência histórica
  (`legacy/` no backend); o runtime de produção é Python convencional,
  portável para Linux/GPU.
- **RAG está fora do escopo da V1.**

## Documentos relacionados

- [`docs/BACKEND_ARCHITECTURE.md`](./BACKEND_ARCHITECTURE.md) — camadas,
  serviços, repositórios e legado do backend.
- [`docs/FRONTEND_ARCHITECTURE.md`](./FRONTEND_ARCHITECTURE.md) — telas,
  serviços e modelos do app Flutter.
- `SciTech_Ear_Especificacao_Final_Implementacao_Claude.docx` — a
  especificação de implementação completa (fonte de verdade para decisões
  detalhadas).
