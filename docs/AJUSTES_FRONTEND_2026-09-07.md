# Ajustes pedidos ao app — resposta ao relatório do frontend de 07/09/2026

**De:** backend SciTech Ear (`main`, `10092e6`)
**Para:** SciTech-frontend (`main`, `82af9b4`)
**Base:** relatório do frontend de 07/09/2026

Tudo abaixo foi conferido contra o código do backend, com arquivo e linha.
Está ordenado por consequência: o que quebra o teste conjunto primeiro, o
que é melhoria depois. No fim há a lista do que **não** precisa mudar — as
premissas do §3 do relatório estão todas confirmadas, e vale ler essa parte
antes de mexer em qualquer coisa da sessão.

---

## 1. Bloqueadores — sem isto o teste conjunto não passa do passo 3

### 1.1. Tratar **403** no `POST /auth/register`

O servidor está com uma allowlist institucional ligada:

    .env:89   AUTH_ALLOWED_EMAIL_DOMAINS=ifg.edu.br

`AuthService._checar_dominio_permitido()` (`app/services/auth_service.py`)
recusa qualquer e-mail fora dela com **403** e
`detail: "Registro restrito a e-mails institucionais."`

O relatório lista como tratados 401, 409, 429 e 422. **403 não está na
lista**, então hoje quem tentar se cadastrar com um e-mail pessoal vê o
texto genérico com o código HTTP — que é exatamente o problema que o §6 do
relatório acabou de corrigir, reaparecendo por outro caminho.

**Ajuste:** tratar 403 no cadastro como erro de campo do e-mail, exibindo o
`detail` do servidor. É uma condição permanente da conta (não adianta tentar
de novo), diferente de 409 (e-mail já existe) e de 429 (tente mais tarde).

Dois detalhes que mudam o comportamento esperado:

- **O 403 conta como tentativa falha no rate limit de registro** — é
  deliberado (`_checar_dominio_permitido` chama `_registrar_falha` antes de
  levantar), senão dava para varrer domínios indefinidamente, já que a
  resposta diz qual foi recusado. São **10 falhas por IP a cada 60 min**.
- Com `adb reverse`, o aparelho inteiro é `127.0.0.1` — um balde só para
  todas as contas do teste. Errar o domínio 10 vezes trava o cadastro por
  uma hora.

### 1.2. As duas contas do teste precisam ser `@ifg.edu.br`

Consequência direta do item acima, e vale repetir porque afeta o roteiro do
§8: os passos 3 a 7 exigem **dois e-mails institucionais distintos**. Não
vamos desligar a allowlist para o teste — ela existe porque a API alcança a
rede 10.4.0.0/16, que é a instituição inteira, não só o laboratório.

### 1.3. Verificar se o app fecha o WebSocket depois da primeira mensagem

**O `/ws` deixou de ser stub.** Esta é a parte mais desatualizada do
relatório (§4.5 e §9). O commit `8f48f46` ("WebSocket de progresso deixa de
ser stub, Fase 8 item 2") entrou depois do que vocês leram, e foi validado
em 2026-09-05 — `docs/E2E_FASE8.md`, adendo final: um job acompanhado de
`queued` a `done` **só pelo WebSocket, com zero polling**.

Hoje `job_progress_ws` (`app/api/jobs.py:163`) mantém a conexão aberta e
empurra cada mudança de estado até `done`/`error`, ou até o teto de 1h por
conexão (`WS_MAX_DURATION_SECONDS`).

**Ajuste:** se o cliente WS foi escrito assumindo "manda o status uma vez e
fecha" — lendo uma mensagem e encerrando por conta própria —, ele descarta o
push real e cai no polling sem necessidade. Não é bug visível (o polling
cobre), mas é o recurso inteiro sendo jogado fora. Vale confirmar que o app
lê em laço até o servidor fechar.

**O polling continua obrigatório**, e isso está combinado: o handler é
escrito para não atrapalhá-lo (em qualquer dúvida ele fecha em vez de
segurar a conexão). A remoção do polling não está em discussão e não vai ser
pedida sem combinar antes.

---

## 2. Correções de contrato — coisas que o app assume e que não se sustentam

### 2.1. `progress` nunca vem preenchido

`JobStatusResponse.progress` existe (`app/models/job.py:32`) e é **sempre
`null`** — no polling e no WebSocket. Nenhum ponto do backend o escreve.

**Ajuste:** não construir barra de progresso ou percentual em cima dele. A
granularidade real hoje é o estágio (`transcribing`, `diarizing`, ...). Se
formos preencher `progress`, avisamos antes.

### 2.2. Estágios curtos podem não aparecer

O WS empurra o **estado atual a cada segundo**, não a sequência completa de
transições. No E2E real, `identifying` (0,07s) e `summarizing` (0,00s,
desligado por flag) não apareceram nenhuma vez.

É de propósito: é exatamente o que o polling do app veria, o que mantém os
dois caminhos consistentes. O histórico completo fica em `job_status_events`
no banco, para quem precisar medir.

**Ajuste:** nenhuma tela pode exigir que o job passe por todos os oito
estados, nem tratar um estado pulado como anomalia. `queued → transcribing →
diarizing → extracting → done` é uma sequência normal e frequente.

### 2.3. Faltou o **413** na lista de erros

Dois tetos de tamanho, ambos ausentes do §2 do relatório:

| Rota | Teto | Config |
|---|---|---|
| `POST /upload` | 300 MB | `MAX_UPLOAD_MB` |
| `POST /participants/{id}/voice-samples` | 25 MB | `MAX_VOICE_SAMPLE_MB` |

No upload o teto é aplicado **durante** a escrita em disco
(`storage_repository().save_audio_stream`), não depois de carregar o
arquivo — então o 413 pode chegar com o corpo ainda sendo enviado.

Uma reunião de 2h em WAV 16 kHz mono 16 bits dá ~230 MB, ou seja, dá para
encostar no limite de verdade. Os >10 min do passo 4 do teste dão ~19 MB,
sem risco.

**Ajuste:** tratar 413 com mensagem específica ("áudio longo demais para
envio"), separada do erro genérico de rede.

### 2.4. O `Retry-After` é a janela inteira, não o tempo restante

`_checar_rate_limit` devolve `int(window.total_seconds())`
(`app/services/auth_service.py`), não quanto falta para a tentativa mais
antiga sair da janela. Valores fixos: **900** no login, **3600** no
registro.

**Ajuste:** a mensagem "tente novamente em ~X minutos" vai superestimar —
pode dizer "em ~60 minutos" faltando um. Sugestão: "aguarde até X minutos"
ou arredondar para uma faixa. É limitação do backend; se virar incômodo real
no uso, dá para trocar por tempo restante de verdade, é só pedir.

### 2.5. Limites de rate limiting (pergunta §4.2)

| | Escopo | Limite | Janela | `Retry-After` |
|---|---|---|---|---|
| `/auth/login` | por **e-mail** | 5 falhas | 15 min | `900` |
| `/auth/register` | por **IP** | 10 falhas | 60 min | `3600` |

Valores de produção, `.env:80-84`. Regras:

- Só **falhas** contam. Login bem-sucedido limpa o contador daquele e-mail
  (`clear_failed_attempts`).
- Uma tentativa já bloqueada **não** estende a janela — `_checar_rate_limit`
  levanta antes de registrar a falha. A janela expira sozinha.
- **Cuidado no teste:** 5 senhas erradas travam a conta A por 15 minutos.

### 2.6. `error.code` é um conjunto fechado de sete (pergunta §4.3)

    AUDIO_NAO_ENCONTRADO              app/services/pipeline_facade.py:52
    TRANSCRIPTION_ERROR                                              :59
    DIARIZATION_ERROR                                                :79
    IDENTIFICATION_ERROR                                             :87
    SUMMARIZATION_ERROR                                             :102
    EXTRACTION_ERROR                                                :109
    WORKER_MAX_TENTATIVAS_EXCEDIDO    app/repositories/job_repository.py:272

O último é o job órfão: o worker morreu no meio do processamento, o job foi
reenfileirado 3 vezes e o backend desistiu.

**Ajuste (recomendado, não bloqueante):** traduzir por `code` e parar de
exibir `error.message` cru. O `message` é `str(exc)` da exceção Python —
inglês, às vezes com caminho de arquivo do servidor dentro. Não é texto para
usuário final. Se acrescentarmos códigos, avisamos.

---

## 3. Melhorias recomendadas — nenhuma bloqueia o teste

### 3.1. Existe um `GET /participants/{id}/voice-profile` que o app não usa

`app/api/participants.py:60`. Devolve
`{participant_id, exists, sample_count, model_version, updated_at}`.

Serve para a tela mostrar o estado real do cadastro de voz vindo do
servidor, em vez de inferir do que o app acha que enviou. Resolve o caso de
o app e o servidor discordarem depois de uma falha de rede no meio do envio
de amostra.

### 3.2. `GET /meetings` — implementado o que faltava (atualizado em 07/09)

Vocês responderam que o bloqueio não eram campos: o histórico não é só
leitura, e sem renomear e remover no servidor a migração perderia as duas
funcionalidades ou reintroduziria o estado local que ela existe para
eliminar. Está certo, e foi implementado. **Podem migrar.**

**`MeetingSummary` agora é:**

    {
      "job_id": "...",
      "title": "Reunião de quarta" | null,
      "status": "done",
      "participants": [{"id": "p1", "name": "Leandro"}, ...],
      "error": {"code": "TRANSCRIPTION_ERROR", "message": "..."} | null,
      "created_at": "...",
      "updated_at": "..."
    }

Os nomes dos participantes e o `error.code` que vocês pediram. Duração ficou
de fora, como vocês mesmos sugeriram — não é exibida hoje, e o dado teria que
ser produzido, não só exportado. Se a tela passar a mostrar, peçam.

Lembrete que vale para o `error` daqui também: traduzam por `code`. O
`error.message` continua sendo `str(exc)` da exceção Python.

**`PATCH /meetings/{job_id}`** → 200 com o `MeetingSummary` atualizado.

    PATCH /meetings/<job_id>
    {"title": "Nome novo"}

Só o título é editável — todo o resto é produzido pelo pipeline. `{"title":
null}` limpa o título (a reunião volta a ser identificada pela data). 404
para job inexistente ou de outro usuário, mesma indistinção do resto.

**`DELETE /meetings/{job_id}`** → 204.

Apaga a linha no banco **e** o diretório `storage/jobs/<job_id>` — áudio e
`result.json`. Decisão tomada em 07/09/2026: "remover" apaga de verdade,
porque um WAV de reunião chega a centenas de MB e o servidor é compartilhado.
**É irreversível e não há lixeira** — se a tela de vocês não pede confirmação
hoje porque a remoção era local e reversível, passa a precisar.

Respostas possíveis:

| Código | Quando | O que o app faz |
|---|---|---|
| 204 | removida | tira do histórico |
| 404 | não existe, ou é de outro usuário | tira do histórico também (já não é dele) |
| **409** | **job em processamento** | **manter na lista e avisar que precisa terminar antes** |

O 409 é a novidade a tratar. O `detail` traz o status atual
(`"Reunião em processamento (status atual: transcribing). Aguarde terminar
para remover."`). O motivo: o worker é um processo separado, e apagar por
baixo dele deixaria o pipeline recriando o diretório para gravar o resultado
— órfão em disco. Um job em `queued` **pode** ser removido (ninguém pegou
ainda); a corrida que sobra é fechada do nosso lado.

### 3.3. Remover o `AppUser.isAdmin` (pergunta §4.6)

Não há plano de papéis. `UserPublic` (`app/models/user.py`) tem `user_id`,
`email` e `name`, e não existe nenhuma noção de papel em lugar nenhum do
backend. Podem remover o campo vestigial e o selo da tela inicial. Se um dia
houver papéis, avisamos antes de mexer no schema.

---

## 4. Confirmado — não mexer, está tudo certo

### As três premissas do §3

**3.1 — O refresh token É rotacionado, e sem janela de graça.**
`AuthService.refresh()` revoga o `jti` apresentado **antes** de emitir o par
novo. Uso único, estrito. **A serialização de renovações concorrentes que
vocês implementaram é obrigatória, não opcional** — mantenham.

Um alívio importante: **não há detecção de reuso em cascata**. Reapresentar
um token já revogado devolve 401 só para aquela chamada; não invalida a
família nem derruba a sessão nova. Um refresh concorrente que escape da
serialização custa uma chamada, não a conta do usuário. Se formos adicionar
reuse-detection (que mudaria isso), avisamos antes.

**3.2 — `expires_in` é a validade do access token, em segundos.**
`_emitir_par_de_tokens`: `jwt_access_token_expire_minutes * 60`, hoje
`30 → 1800`. O refresh token vale 30 dias e **não aparece em nenhum campo**
da resposta — se precisarem dele no cliente, peçam. A renovação proativa a
2 min do fim está correta.

**3.3 — `user_id` é imutável.** É um `uuid4()` gerado em
`UserRepository.create_user` e usado como chave primária de `users`. Nenhum
caminho do código o reescreve, e **não existe endpoint de exclusão de
conta** — então não há como recriar conta com o mesmo e-mail e ganhar id
novo pela API. O único cenário de mudança seria apagar o `jobs.db` na mão no
servidor; se isso acontecer, avisamos. **Podem escopar o armazenamento local
nele com segurança.**

### Outras confirmações

- **`/auth/logout` revoga só aquele refresh token** (pergunta §4.1).
  `logout()` revoga um `jti` só; sair num aparelho não derruba os outros. E
  é idempotente de propósito: token alheio, já revogado ou inexistente
  devolvem 204 igual, sem vazar qual foi o caso.
- **O formato de erro é o `detail` do FastAPI** em todas as rotas, e não há
  plano de mudar. A correção do §6 (ler `detail` em vez de `message`) está
  certa. Se mudarmos, avisamos.
- **`/status` e `/resultado` devolvem 404** tanto para job inexistente
  quanto para job de outro usuário — `get_owned` não distingue, de
  propósito. Não tratem 404 como "job sumiu".
- **Os perfis de voz já são escopados por `user_id` no servidor**
  (`VoiceEnrollmentService.add_sample(user_id=...)`). O isolamento dos
  passos 6–7 do teste está garantido dos dois lados, não só no
  armazenamento local — inclusive se as duas contas gerarem o mesmo
  `participant_id`.
- **Áudio truncado (§6 do relatório): nenhuma mudança necessária.**
  Processa como qualquer outro, sem tratamento especial. Único aviso: um WAV
  muito curto tende a sair com poucos segmentos ou cair em
  `DIARIZATION_ERROR` — não há erro dedicado para "áudio curto demais".
- **`DEMO_MODE` do backend é inerte** (`app/config.py:127`, não é lido em
  lugar nenhum). Confirma o §5 do relatório: se aparecer transcrição
  plausível sem servidor no ar, é a flag do app, não fallback do backend.
- **O contrato de `/upload`, `MeetingResult` e amostra de voz está em dia**,
  como o relatório já dizia. `Participant` é exatamente `{id, name}`.

---

## 5. Para o teste conjunto do §8

O roteiro está bom. Do lado do backend, o `python -m app.worker` está certo
— sem ele o job fica em `queued` para sempre.

Antes de rodar, com o que está acima:

1. Separar **dois e-mails `@ifg.edu.br`** (item 1.2).
2. Tratar 403 no cadastro, ou pelo menos saber que ele existe para não
   perder tempo achando que é bug de rede (item 1.1).
3. Não errar senha 5 vezes na mesma conta (item 2.5).
4. Conferir se o cliente WS lê em laço (item 1.3) — se não ler, o teste
   ainda passa, só não exercita o push real.

**O log de 401 e o motivo do fechamento do WS que vocês pediram estão
prontos.** No journal do servidor, em INFO:

    401 em GET /meetings: cabeçalho Authorization ausente ou sem o prefixo 'Bearer '.
    401 em GET /status/<job_id>: Token de acesso inválido ou expirado.
    WS /ws/<job_id> fechado com 4401: token de acesso ausente ou inválido.
    WS /ws/<job_id> fechado com 4404: job inexistente ou de outro dono (user_id do token: ...).

Nenhuma dessas linhas contém o token: o log do 401 usa o caminho da URL sem
a query string, que é onde o WebSocket carrega a credencial. Mesmo motivo do
filtro de redação que já existia (`app/main.py`) — um token válido chegou ao
journal do servidor uma vez, em 06/09, e não deve chegar de novo por uma
porta nova.

Isso continua distinguível do lado do app pelo corpo da resposta: os
`detail` são distintos (`"Token de acesso ausente."` vs `"Token de acesso
inválido ou expirado."` vs `"Token não é um access token."`), e os códigos
de fechamento do WS são **4401** (token ausente ou inválido) e **4404** (job
não existe ou não é desse usuário).
