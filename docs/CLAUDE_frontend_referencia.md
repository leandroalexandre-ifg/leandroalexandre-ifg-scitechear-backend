# CLAUDE.md — SciTech Ear · Frontend (Flutter)

Este arquivo define como o Claude Code deve trabalhar **no repositório do app
Flutter** do SciTech Ear. É carregado automaticamente em toda sessão. O backend
Python/IA vive em um repositório separado.

## Contexto

O SciTech Ear capta o áudio de uma reunião, identifica quem falou (por biometria,
no backend) e extrai as perguntas discutidas. Este repositório é **apenas o
cliente**: ele grava, envia e exibe. Todo o processamento de IA acontece no
backend, acessado exclusivamente pela API.

A especificação completa da integração
(`SciTech_Ear_Especificacao_Final_Implementacao_Claude.docx`) é mantida no
repositório do backend, que é a fonte de verdade do contrato. Em caso de dúvida
sobre o formato de dados, siga o contrato canônico resumido abaixo.

## Regras invioláveis (cliente)

1. **Flutter é cliente fino.** Nenhum modelo de IA roda no dispositivo.
2. **A API é a única fronteira** com o backend.
3. **Identidade de falante vem do backend.** NUNCA mapear `SPEAKER_00` para
   participante por posição/ordem da lista. Exiba o `speaker` que o backend
   devolve; quando não identificado, mostre o `cluster`.
4. **`participant_id` estável é a chave** compartilhada com o backend. O nome é
   só exibição.
5. **Erro real do backend NUNCA vira resultado fictício.** Sem fallback demo
   automático: falhas de upload/status/resultado devem ser exibidas ao usuário
   (com opção de repetir). Demo só com flag explícita de build.
6. **Amostra de voz é sincronizada uma vez** por participante, no
   cadastro/atualização — não reenviada a cada reunião.
7. **Preserve a UI existente.** Refatore só o necessário para o novo contrato.
   Não introduza gerenciador de estado ou dependências que a integração não pede.
8. **Base URL por `--dart-define`** (`SCITECH_API_BASE_URL`,
   `SCITECH_WS_BASE_URL`); default `10.0.2.2:8000` (Android Emulator no Mac).
   Nunca fixe URLs de túnel no código.

## O que o app consome do backend

Rotas: `POST /upload` (multipart: `file` WAV 16 kHz mono, `title?`,
`participants` JSON, `expected_speaker_count?`) → **202** + `job_id`;
`GET /status/{job_id}`; `GET /resultado/{job_id}`; `WS /ws/{job_id}`
(com **polling como fallback obrigatório**); e os endpoints de voz
`POST /participants/{id}/voice-samples`, `GET`/`DELETE
/participants/{id}/voice-profile`.

**Estados do job:** `queued`, `transcribing`, `diarizing`, `identifying`,
`summarizing`, `extracting`, `done`, `error`.

**Resultado canônico** que o app precisa parsear:
- `segments[]`: `id, cluster, participant_id, speaker, identified, confidence,
  start, end, text`.
- `questions[]`: `id, type (explicit|implicit), text, participant_id?, speaker?,
  time?, source_segment_ids[]` — em perguntas implícitas, `participant_id`,
  `speaker` e `time` podem ser **nulos**.

## Mudanças esperadas neste repo (resumo)

- `lib/config.dart`: base URL/WS por `--dart-define`.
- `participant.dart`: `id` como identidade compartilhada; flag de sincronização
  do perfil de voz.
- `participant_service.dart`: sincronizar amostra com o backend uma vez; remoção
  solicita exclusão remota.
- `upload_service.dart`: parar de enviar `voice_samples[]` em toda reunião;
  enviar `participants` como JSON; timeout e erros explícitos.
- `status_service.dart`: aceitar os novos estados; preservar WebSocket + polling;
  não traduzir indisponibilidade para demo.
- `meeting_result.dart`: novos campos de segmento e `Question.type`;
  `speaker`/`time` opcionais.
- `recording_screen.dart` / `processing_screen.dart`: remover o fallback que cria
  resultado fictício; exibir erro real; oferecer repetir/voltar.
- `result_screen.dart`: eliminar o mapeamento `SPEAKER_N` → posição; exibir o
  `speaker` do backend e o `cluster` quando desconhecido.
- `offline_service.dart`: preservar isolado; só via flag de demo explícita.

## Escopo da V1

Android apenas (Android Emulator no Mac). iOS é preservado, mas não é critério de
aceite agora.

## Método de trabalho

- Branch de integração; nunca alterar `main` diretamente.
- Mudanças pequenas e verificáveis, com commit por fase. Ao final de cada fase:
  arquivos alterados, decisões e pendências.
- Testes de widget/parsing para o novo JSON: falante identificado, cluster
  desconhecido, pergunta implícita sem speaker/time, erro de upload sem demo
  silencioso, polling quando o WebSocket falha.
