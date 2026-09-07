# `GET /meetings`: está pronto — resposta ao §3.2

**De:** backend SciTech Ear
**Para:** SciTech-frontend
**Responde a:** "Resposta do frontend — ajustes aplicados e o que falta
decidir", 07/09/2026

Vocês escreveram esse relatório contra o backend em `10092e6`. O §3.2 foi
implementado depois disso, no merge `0de0ba6` — **os dois campos e as duas
operações**. Não há decisão pendente do nosso lado: podem migrar o histórico.

Vocês acertaram o diagnóstico, e ele mudou o que fizemos. O pedido tinha
chegado como "faltam campos"; o que vocês responderam foi que o bloqueio era
o histórico não ser só leitura, e que migrar sem renomear e remover trocaria
uma divergência por outra. Foi isso que orientou a implementação.

---

## 1. `MeetingSummary`

    {
      "job_id": "5c1f...",
      "title": "Reunião de quarta" | null,
      "status": "done",
      "participants": [{"id": "p1", "name": "Ana"}, {"id": "p2", "name": "Bruno"}],
      "error": {"code": "TRANSCRIPTION_ERROR", "message": "..."} | null,
      "created_at": "2026-09-07T14:02:11Z",
      "updated_at": "2026-09-07T14:09:48Z"
    }

`participants` veio como `[{id, name}]`, não `participant_names: [str]`: era
igualmente barato (já é a coluna JSON da linha do job, exatamente como chegou
no `/upload`) e o `id` é o que liga o cartão do histórico ao cadastro de voz,
caso o cartão um dia queira mostrar quem tinha biometria.

`error` é o `JobError` inteiro, com `code` e `message`, e não só o código —
uniforme com `GET /status`, para o app poder usar um parser só. **Vale o
mesmo do §2.6:** traduzam pelo `code`; o `message` continua sendo `str(exc)`
da exceção Python.

**Duração ficou de fora**, como vocês pediram. Não é só exportar: nenhum
lugar da linha do job guarda a duração do áudio hoje, ela teria que ser
medida e persistida. Quando o cartão precisar, peçam — aí discutimos o custo.

## 2. `PATCH /meetings/{job_id}` — renomear

    PATCH /meetings/<job_id>
    {"title": "Nome novo"}     → 200 + MeetingSummary atualizado
    {"title": null}            → 200, título limpo (volta a ser exibido pela data)

Só o título é editável; todo o resto do registro é produzido pelo pipeline.
Funciona em **qualquer status**, inclusive com o job em processamento —
renomear não interfere no worker, e obrigar a esperar seria arbitrário.

404 para job inexistente ou de outro usuário, sem distinguir os dois casos,
igual ao resto da API.

## 3. `DELETE /meetings/{job_id}` — remover

    DELETE /meetings/<job_id>  → 204

Apaga a linha no banco **e** o diretório `storage/jobs/<job_id>`: o WAV e o
`result.json`. Não é ocultar, não é lápide, não há lixeira — a decisão foi
apagar de verdade, porque um WAV de reunião chega a centenas de MB e o
servidor é compartilhado; guardar o arquivo de algo que o usuário mandou
remover vazaria disco para sempre, sem ninguém para limpar depois.

**Duas consequências para a UI:**

- **É irreversível.** Se a tela hoje não pede confirmação porque a remoção era
  local (e, no pior caso, custava um recarregamento), agora precisa pedir.
- Depois do 204, `GET /status/{job_id}` e `GET /resultado/{job_id}` respondem
  **404**, e um WebSocket que já estivesse aberto para aquele job fecha com
  **4404**. Esse último caso não existia: até agora a conexão terminava com
  um encerramento normal (1000), indistinguível de "o job terminou" — foi
  corrigido junto, porque a tela de processamento aberta enquanto a reunião é
  removida de outra tela é um cenário real, e o app merecia poder diferenciar.
  É o mesmo 4404 de "job de outro usuário": os dois continuam indistinguíveis
  pelo código, de propósito.

**Respostas possíveis:**

| Código | Quando | O que o app faz |
|---|---|---|
| 204 | removida | tira do histórico |
| 404 | não existe, ou é de outro usuário | tira do histórico também — já não é dele |
| **409** | **job em processamento** | **mantém na lista e avisa que precisa terminar** |

O **409** é a única resposta genuinamente nova a tratar. O `detail` traz o
status atual: `"Reunião em processamento (status atual: transcribing).
Aguarde terminar para remover."`

O motivo é o worker ser um processo separado: apagar por baixo dele deixaria
o pipeline terminando um job que já não existe e recriando o diretório para
gravar o `result.json` — órfão em disco, exatamente o que a remoção existe
para evitar. Um job em **`queued` pode** ser removido (ninguém pegou ainda),
e a janela de corrida que sobra — o worker escolher o job entre a checagem e
a remoção — é fechada do nosso lado: o pipeline reconfere se o job ainda
existe antes de persistir, e limpa o diretório se sumiu.

Na prática, o 409 aparece na janela em que a reunião está sendo processada.
Se a tela de histórico esconde o botão de remover fora dos estados terminais,
ele vira só uma rede de segurança contra a corrida.

## 4. O cache local de resultados

Concordamos: é ortogonal. Reabrir reunião sem rede não é função do
`/meetings`, e não temos nenhum plano que dependa de vocês largarem esse
cache.

---

## 5. Outros pontos do relatório de vocês

**Log de 401 e motivo do fechamento do WS.** Também já estão prontos (mesmo
merge). Ficou registrado que não era bloqueante — foi feito porque o caso que
vocês descreveram, o app não ver resposta nenhuma, é justamente o que a
resposta HTTP não cobre. No journal, em INFO:

    401 em GET /meetings: cabeçalho Authorization ausente ou sem o prefixo 'Bearer '.
    401 em GET /status/<job_id>: Token de acesso inválido ou expirado.
    WS /ws/<job_id> fechado com 4401: token de acesso ausente ou inválido.
    WS /ws/<job_id> fechado com 4404: job inexistente ou de outro dono (user_id do token: ...).

Sem o token em nenhuma delas — o log do 401 usa o caminho da URL, nunca a
query string.

**Reuse-detection no refresh.** Compromisso registrado, e o raciocínio de
vocês está certo: hoje um refresh fora da serialização custa um 401; com
detecção em cascata passaria a custar a sessão. Se formos implementar, vocês
sabem antes de entrar.

**Amostra de voz de 25 MB inalcançável (20s, ~640 KB).** Bom saber. O teto
fica como está — ele existe contra o que não passa pela sua tela de gravação,
não contra ela.

**`Retry-After`.** "Aguarde até X minutos" resolve, e concordamos em não
trocar por tempo restante: o header estaria mentindo menos, mas a mudança
custaria uma consulta a mais no caminho do rate limit para ganhar precisão
numa mensagem que já está honesta.

---

## 6. Resumo

| Item | Situação |
|---|---|
| `MeetingSummary.participants` | ✅ `[{id, name}]` |
| `MeetingSummary.error` | ✅ `JobError` completo (traduzir pelo `code`) |
| Duração | ⛔ fora, a pedido de vocês |
| `PATCH /meetings/{job_id}` | ✅ renomeia, em qualquer status |
| `DELETE /meetings/{job_id}` | ✅ apaga banco e disco — **irreversível**, e **409** durante o processamento |
| Log de 401 / fechamento do WS | ✅ pronto |
| Cache local de resultados | ✅ fica, é ortogonal |

Nenhuma decisão pendente do lado do backend. A migração do histórico está
liberada — e nada disso foi exercitado pelo app real ainda, então o teste
conjunto continua sendo o que fecha a conta.
