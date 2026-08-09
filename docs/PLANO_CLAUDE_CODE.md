# Plano de Execução no Claude Code — SciTech Ear (Integração V1)

> Como usar: cole o **Prompt-Mestre** uma vez no início da sessão do Claude Code.
> Depois cole **um Prompt de Fase por vez**, na ordem. Só avance para a fase seguinte
> quando os testes e o checklist da fase atual passarem. Isso respeita a regra da spec:
> mudanças pequenas, verificáveis e com commit por fase.

---

## PROMPT-MESTRE (colar uma vez, no começo)

```
Você vai me ajudar a integrar o frontend Flutter (já existente) com o backend
Python/IA (já prototipado em notebooks/scripts) do projeto SciTech Ear.

FONTE DE VERDADE
- O documento "SciTech Ear — Especificação Final Consolidada de Implementação"
  (na raiz do repositório) é o contrato de implementação. Leia-o INTEGRALMENTE
  antes de editar qualquer arquivo. Quando a documentação antiga divergir do
  código real, siga as decisões consolidadas do documento.
- Leia também, integralmente, os dois repositórios (frontend e backend) antes
  de propor mudanças. Registre um baseline do que existe.

REGRAS INVIOLÁVEIS (valem para toda a sessão)
1. Flutter é cliente fino: nenhum modelo de IA roda no dispositivo.
2. A API é a única fronteira entre frontend e backend.
3. Identidade de falante é do BACKEND, via biometria. NUNCA mapear SPEAKER_00
   para participante por posição no Flutter.
4. participant_id estável é a chave entre frontend e backend. Nome é só exibição.
5. Erro real do backend NUNCA vira resultado fictício. Demo só com DEMO_MODE=true.
6. Nada de google.colab, Google Drive ou /content/drive no caminho de execução.
7. Todo segredo (HF_TOKEN etc.) vem de variável de ambiente. Nunca no código.
8. Preserve UI e algoritmos já validados. Refatore só o necessário para integrar.
   Não introduza frameworks ou refatorações não exigidos pela spec.
9. Preserve os prompts de LLM semanticamente. Mudança de formato deve ser mínima
   e versionada (ex.: passar saída para JSON sem alterar critérios semânticos).
10. Antes de otimizar ou trocar modelos, conclua a integração ponta a ponta e
    crie testes de regressão.

MÉTODO DE TRABALHO
- Trabalhe em uma branch de integração; nunca altere main diretamente.
- Faça commits pequenos por fase. Ao final de cada fase, rode os testes e me
  entregue: (a) arquivos alterados, (b) decisões tomadas, (c) pendências.
- Não avance de fase sem meu OK.
- Ao mover scripts/notebooks para legacy/, só faça DEPOIS de extrair o serviço
  equivalente. Nunca apague as fontes originais.

ESCOPO DA V1
- Android apenas (Android Emulator no Mac). iOS é preservado, mas não é critério
  de aceite agora.
- Backend Python convencional, sem lógica em notebooks. Colab, se usado, é só
  runtime temporário de GPU (launcher que instala deps, sobe Ollama/FastAPI e
  abre túnel) — nenhum algoritmo vive nele.

Confirme que leu e entendeu. Antes de codar, produza:
- um resumo do baseline dos dois repositórios (estrutura e pontos-chave);
- a lista de fases que vamos seguir (vou te passar uma por vez);
- e aguarde meu OK para iniciar a Fase 0.
```

---

## FASE 0 — Preparação e baseline

```
FASE 0 — Preparação (não altera lógica ainda).

1. Crie a branch de integração (ex.: feat/integracao-v1). Não toque na main.
2. Faça um inventário do FRONTEND e do BACKEND e registre um baseline em
   docs/BASELINE.md: estrutura de pastas, arquivos-chave, o que já funciona,
   e onde estão os algoritmos validados (WhisperX, pyannote, SpeechBrain, LLM).
3. Crie a estrutura de diretórios do backend conforme a seção "Estrutura
   recomendada" da spec (app/, app/api, app/services, app/repositories,
   app/models, prompts/, legacy/, storage/ [gitignored], tests/), com arquivos
   vazios/stubs onde ainda não houver conteúdo. NÃO mova nada para legacy/ ainda.
4. Crie .env.example com TODAS as variáveis da seção "Configuração por ambiente"
   da spec (HF_TOKEN, STORAGE_ROOT, WHISPERX_*, DIARIZATION_MODEL, VOICE_MODEL,
   VOICE_*_THRESHOLD, OLLAMA_*, ENABLE_IMPLICIT_REFINEMENT=false, DEMO_MODE=false).
5. Adicione storage/ ao .gitignore.

Ao final: liste os arquivos criados, confirme que nenhuma lógica foi movida ou
alterada, e aguarde meu OK.

Checklist de saída:
- [ ] branch de integração criada
- [ ] docs/BASELINE.md com inventário dos dois repos
- [ ] árvore de diretórios do backend criada (stubs)
- [ ] .env.example completo
- [ ] storage/ no .gitignore
```

---

## FASE 1 — Schemas e contrato HTTP (antes do pipeline)

```
FASE 1 — Schemas Pydantic e contrato HTTP, com pipeline ainda em stub.

Implemente PRIMEIRO o contrato, para o Flutter poder integrar cedo.

1. app/models/: schemas Pydantic do contrato canônico da spec:
   - Participant (id, name);
   - Job/Status (job_id, status, progress, error) com os estados EXATOS:
     queued, transcribing, diarizing, identifying, summarizing, extracting,
     done, error;
   - Result canônico: segments[] (id, cluster, participant_id, speaker,
     identified, confidence, start, end, text) e questions[] (id, type
     [explicit|implicit], text, participant_id?, speaker?, time?,
     source_segment_ids[]) e metadata{}.
2. app/config.py: Pydantic Settings lendo o .env (todas as variáveis da Fase 0).
3. app/api/jobs.py: rotas EXATAS que o Flutter já chama:
   - POST /upload (multipart: file, title?, participants JSON,
     expected_speaker_count?) -> 202 {job_id, status:"queued"};
   - GET /status/{job_id};
   - GET /resultado/{job_id};
   - WS /ws/{job_id} pode ficar como stub por enquanto.
4. app/api/participants.py: POST /participants/{id}/voice-samples,
   GET e DELETE /participants/{id}/voice-profile (podem devolver stub coerente).
5. app/api/health.py: GET /health (não carrega modelos) e GET /ready.
6. app/main.py: FastAPI, CORS de desenvolvimento, routers, lifecycle.
7. O PipelineFacade ainda NÃO existe de verdade: /upload cria um job e o
   /resultado devolve um fixture canônico VÁLIDO (marcado como stub), só para
   validar o contrato. Nada de IA nesta fase.

Testes desta fase (crie em tests/):
- upload de WAV válido responde 202 com job_id;
- upload inválido é rejeitado;
- status de job inexistente;
- resultado antes de done;
- o fixture de resultado valida contra os schemas Pydantic.

Ao final: liste arquivos, decisões e pendências. Aguarde meu OK.

Checklist de saída:
- [ ] schemas do contrato canônico completos e validados
- [ ] rotas /upload /status /resultado no ar (com fixture)
- [ ] rotas de voz e health/ready respondendo
- [ ] testes de contrato passando
- [ ] /health não carrega modelos
```

---

## FASE 2 — Biometria: VoiceRepository e enrollment por participant_id

```
FASE 2 — Enrollment de voz por participant_id (a base da identidade).

1. app/repositories/voice_repository.py: persistência do perfil de voz com
   CHAVE = participant_id (NÃO por nome). Guarde: embedding consolidado,
   metadados (model_version, updated_at, n_amostras). Abstraia o filesystem
   (nada de assumir pastas por nome como o legado fazia).
2. app/services/voice_enrollment_service.py: refatore cadastro_vozes.py.
   - endpoint de enrollment cria/atualiza o embedding consolidado do participante;
   - recalcular embedding SÓ no cadastro/atualização, nunca a cada reunião.
3. Ligue os endpoints da Fase 1 (voice-samples POST, voice-profile GET/DELETE)
   a este serviço de verdade.
4. Migração de chave: se houver banco_vozes/<nome>/, escreva um utilitário de
   migração nome -> participant_id (não destrutivo; preserve o original).

Testes:
- enrollment cria perfil e associa ao participant_id;
- nova amostra recalcula o embedding consolidado;
- GET voice-profile devolve existe/quantidade/model_version/updated_at;
- DELETE remove o perfil.

Preserve o algoritmo de extração de embedding já validado (SpeechBrain ECAPA).
Ao final: arquivos, decisões, pendências. Aguarde meu OK.

Checklist de saída:
- [ ] VoiceRepository com chave participant_id
- [ ] enrollment recalcula embedding só no cadastro/atualização
- [ ] endpoints de voz funcionais
- [ ] utilitário de migração nome->id (não destrutivo)
- [ ] testes de enrollment passando
```

---

## FASE 3 — TranscriptionService (WhisperX) com teste de contrato

```
FASE 3 — Extrair a transcrição para um serviço, sem Colab/Drive.

1. app/services/transcription_service.py: extraia do transcricao.ipynb o uso de
   WhisperX (modelo turbo, language=pt, batch_size=16, float16 em CUDA / int8 em
   CPU). Execute o alinhamento e PRESERVE 'words' internamente (artefato interno).
2. Remova qualquer dependência de google.colab e de caminhos /content/drive.
3. Crie um teste de contrato do serviço usando um resultado fixture (não precisa
   rodar GPU no teste): a saída deve ter segmentos com start/end/text.

Preserve o algoritmo; refatore só para virar serviço puro e portável.
Ao final: arquivos, decisões, pendências. Aguarde meu OK.

Checklist de saída:
- [ ] TranscriptionService isolado, sem Colab/Drive
- [ ] segmentos alinhados; words preservados internamente
- [ ] teste de contrato com fixture passando
```

---

## FASE 4 — Diarização e biometria (algoritmos preservados)

```
FASE 4 — Diarização (clusters) + biometria (identidade), desacopladas.

1. app/services/diarization_service.py: refatore etapa2b_diarizacao.py.
   - modelo pyannote/speaker-diarization-community-1;
   - LAZY LOAD no worker (não carregar no import da API);
   - REMOVA MIN_SPEAKERS=4 / MAX_SPEAKERS=7 fixos; use expected_speaker_count do
     job como pista e limites configuráveis; num_speakers exato só se solicitado;
   - preserve a associação segmento<->cluster por maior sobreposição temporal.
2. app/services/voice_service.py: refatore etapa3_biometria.py (SpeechBrain ECAPA).
   - defaults via config: identificação 0.30, margem 0.05, outlier 0.45,
     duração mínima 1.5s, até 5 segmentos, concatenação habilitada;
   - devolva campos SEPARADOS: cluster, participant_id, speaker, identified,
     confidence. NUNCA "Leandro (0.82)" no campo speaker;
   - falante não identificado permanece como cluster (sem associação posicional).

Testes:
- merge temporal diarização<->transcrição;
- biometria: aceito, abaixo do threshold, ambíguo por margem;
- remoção de outliers.

Ao final: arquivos, decisões, pendências. Aguarde meu OK.

Checklist de saída:
- [ ] diarização com lazy load e limites configuráveis (sem 4/7 fixos)
- [ ] biometria com campos separados (sem score no nome)
- [ ] não-identificado fica como cluster
- [ ] testes de merge e biometria passando
```

---

## FASE 5 — Formatter + QuestionService (explícitas, sumário, implícitas)

```
FASE 5 — Adaptador de linhas e extração de perguntas.

1. app/services/transcript_formatter.py: transforme segmentos diarizados em
   linhas estáveis para os prompts, mantendo o mapa line -> segment (para
   recuperar speaker, time e source_segment_ids sem inferência do LLM).
   Formato: "line N -> seg_XXXX -> [Speaker]: texto".
2. app/services/question_service.py: refatore o uso de Ollama + prompts.
   - EXPLÍCITAS: preserve o prompt e a regra estrita (só sentenças terminadas
     em '?'); valide o JSON; converta linha_transcricao -> segmento/timestamp
     pelo mapa do formatter; o texto da pergunta permanece literal.
   - SUMARIZAÇÃO: artefato interno; pode continuar textual na V1.
   - IMPLÍCITAS: versione o PromptGerador para SAÍDA JSON (sem alterar critérios
     semânticos); type=implicit; speaker/time podem ser null; nada de
     speaker/time fictícios.
   - REFINAMENTO desativado por default (ENABLE_IMPLICIT_REFINEMENT=false).
   - REMOVA RAG (fora da V1). Qwen3 14B como baseline, modelo configurável.

Testes:
- formatter line->segment;
- parser/validador do JSON explícito;
- saída implícita com campos opcionais.

Ao final: arquivos, decisões, pendências. Aguarde meu OK.

Checklist de saída:
- [ ] formatter com mapa line->segment
- [ ] explícitas preservam prompt e literalidade; JSON validado
- [ ] implícitas em JSON, type=implicit, speaker/time opcionais
- [ ] refinamento e RAG desativados/removidos na V1
- [ ] testes de formatter e parsers passando
```

---

## FASE 6 — PipelineFacade e estados

```
FASE 6 — Orquestração ponta a ponta de um job.

1. app/services/pipeline_facade.py: MeetingPipelineFacade recebe UM job e chama,
   em ordem, todas as etapas em memória/artefatos por job:
   WhisperX -> pyannote -> SpeechBrain -> formatter -> explícitas ->
   sumarização -> implícitas -> resultado canônico persistido.
2. Atualize o status do job nos estágios reais: transcribing, diarizing,
   identifying, summarizing, extracting, done (ou error com code/message).
3. app/repositories/: job_repository, result_repository, storage_repository
   (storage LOCAL do runtime para testes; nada de Drive).
4. V1 pode rodar o executor in-process/background, mas deixe a INTERFACE
   preparada para fila (não implemente Celery/Redis ainda).
5. Ligue /upload -> cria job -> executa pipeline; /resultado -> canônico real.

Testes:
- pipeline com mocks das etapas pesadas (sem GPU) validando transições de estado
  e forma do resultado canônico.

Ao final: arquivos, decisões, pendências. Aguarde meu OK.

Checklist de saída:
- [ ] PipelineFacade orquestra as 7 etapas por job
- [ ] estados percorridos na ordem correta; error com code/message
- [ ] repositories desacoplados do filesystem; storage local
- [ ] interface pronta para fila (sem implementar fila)
- [ ] teste de pipeline com mocks passando
```

---

## FASE 7 — Ajustes no Flutter para o novo contrato

```
FASE 7 — Alinhar o Flutter ao contrato novo. Preserve a UI.

1. lib/config.dart: base URL e WS por --dart-define
   (SCITECH_API_BASE_URL, SCITECH_WS_BASE_URL); default 10.0.2.2:8000.
2. participant.dart: participant.id passa a ser a identidade compartilhada;
   adicione voiceProfileSynced/remoteVoiceProfile (ou equivalente).
3. participant_service.dart: ao cadastrar/atualizar amostra, sincronize com o
   endpoint de voz UMA vez; remoção solicita exclusão remota quando possível.
4. upload_service.dart: PARE de enviar voice_samples[] em toda reunião; envie
   participants como JSON (id/name); timeout e mensagens de erro explícitas.
5. status_service.dart: aceite os novos estados (identifying, summarizing);
   preserve WebSocket + polling; NÃO traduza indisponibilidade para demo.
6. meeting_result.dart: adicione ids, cluster, participant_id, identified,
   confidence e Question.type; speaker/time opcionais nas perguntas.
7. recording_screen.dart e processing_screen.dart: REMOVA o catch/fallback que
   cria resultado fictício; exiba erro real; ofereça Repetir/Voltar; preserve o
   áudio para retry durante testes.
8. result_screen.dart: ELIMINE o mapeamento SPEAKER_N -> participante[posição];
   exiba o speaker do backend e o cluster quando desconhecido.
9. offline_service.dart: preserve, mas isolado; só via flag de demo explícita.

Testes (Flutter):
- parsing do novo JSON; falante identificado; cluster desconhecido;
- pergunta implícita sem speaker/time;
- erro de upload sem demo silencioso; polling quando WS falha.

Ao final: arquivos, decisões, pendências. Aguarde meu OK.

Checklist de saída:
- [ ] sem mapeamento posicional de speaker
- [ ] sem fallback demo automático
- [ ] modelos e serviços alinhados ao contrato canônico
- [ ] base URL por dart-define
- [ ] testes de widget/parsing passando
```

---

## FASE 8 — E2E no Android Emulator, depois WebSocket e otimizações

```
FASE 8 — Integração ponta a ponta e só então extras.

1. Rode o E2E no Android Emulator do Mac apontando para o backend
   (via --dart-define). Cenários mínimos:
   - 2 participantes cadastrados e reconhecidos;
   - 1 conhecido + 1 desconhecido;
   - reunião com pergunta explícita terminada em '?';
   - reunião com ao menos uma pergunta implícita;
   - reunião sem perguntas explícitas;
   - falas curtas e sobreposição de voz.
2. SÓ DEPOIS do E2E verde: habilite o WebSocket /ws/{job_id} de verdade
   (polling continua como fallback) e otimizações de carregamento/caching.
3. Registre benchmarks de GPU e memória. NÃO troque modelos antes de ter baseline.
4. Mova scripts/notebooks para legacy/ agora que os serviços os substituíram
   (sem apagar as fontes) — se ainda não tiver movido.

Ao final: relatório do E2E, benchmarks, arquivos movidos para legacy/, pendências.

Checklist de saída (Definição de Pronto da V1):
- [ ] cadastrar participantes e sincronizar amostra uma vez
- [ ] gravar reunião WAV 16 kHz mono e enviar sem reenviar amostras
- [ ] /upload responde 202 rápido; status percorre estágios reais
- [ ] transcrição diarizada + identificação biométrica quando confiável
- [ ] perguntas explícitas e implícitas reais
- [ ] sem troca manual de arquivos, sem Drive, sem fallback fictício
- [ ] backend sem google.colab e sem /content/drive
- [ ] segredos só via env
```

---

### Observações finais de uso

- Se o Claude Code sugerir "adiantar" etapas (ex.: já implementar Celery, ou já
  trocar o modelo de LLM), lembre-o das regras 8 e 10 do Prompt-Mestre: integração
  ponta a ponta primeiro, otimização depois.
- Ao fim de cada fase, guarde o resumo (arquivos/decisões/pendências) que ele
  produzir — vira o histórico da integração e ajuda a retomar entre sessões.
- Pontos que a própria spec marca como calibráveis (thresholds de voz, min/max de
  falantes, peso do Qwen3 14B, escolha futura de fila) NÃO devem bloquear o E2E.
```
