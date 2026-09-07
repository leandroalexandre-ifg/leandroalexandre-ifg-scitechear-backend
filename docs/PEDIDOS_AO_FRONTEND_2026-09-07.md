# Pedidos ao app — o que o backend precisa do frontend

**De:** backend SciTech Ear (`main`, `e7d8ad1`)
**Para:** SciTech-frontend
**Data:** 07/09/2026

Do nosso lado não há nada bloqueado: o §3.2 foi implementado e o contrato
está em `docs/RESPOSTA_MEETINGS_2026-09-07.md`. O que sobra são pedidos, em
ordem de importância. O item 1 é o único que eu mandaria mesmo que fosse
sozinho — ele pode estar produzindo problema agora, em silêncio.

---

## 1. Os `participant_id` são estáveis? (precisamos da resposta)

Os perfis de voz vivem assim no servidor:

    storage/voices/<user_id>/<participant_id>/
        samples/        # as amostras WAV enviadas
        embedding.pt    # o embedding ECAPA derivado delas
        profile.json

O `user_id` é nosso (uuid4, imutável, já confirmado). **O `participant_id` é
gerado pelo app**, e o backend não tem rota que liste participantes — só
`POST /participants/{id}/voice-samples`, `GET /participants/{id}/voice-profile`
e `DELETE /participants/{id}/voice-profile`, as três exigindo que o chamador
já saiba o id.

Isso significa que um perfil cujo `participant_id` o app esqueceu fica
**invisível e inapagável**: ninguém consegue listar para descobrir que existe,
e ninguém consegue remover sem o id. Num servidor compartilhado isso é
acúmulo permanente de gravações de voz de pessoas reais — o dado mais
sensível que o sistema guarda, e o que menos deveria sobrar por acidente.

**Duas perguntas concretas:**

1. O `participant_id` sobrevive a **reinstalar o app** e a **trocar de
   aparelho**, para a mesma conta? Ou é gerado de novo junto com o cadastro
   local de participantes?
2. Quando o usuário **apaga um participante** no app, ele chama
   `DELETE /participants/{id}/voice-profile`, ou o participante só some da
   lista local?

Se a resposta a qualquer uma das duas for "não", o problema é **nosso** para
resolver — provavelmente uma rota de listagem por usuário, ou derivar a chave
de algo estável em vez do id do app. Mas precisamos saber antes de projetar a
saída, porque as duas soluções são diferentes: uma limpa o que já acumulou,
a outra impede que acumule.

Não é urgente no sentido de travar alguém. É urgente no sentido de que cada
semana que passa acumula mais, e não temos como medir quanto.

## 2. O teste conjunto — precisamos de uma data

É o que fecha a conta. Vale reler o que os dois lados já escreveram: os 26
testes do app usam um adaptador HTTP falso, e o nosso E2E da Fase 8 usou um
cliente Python. **A conversa real entre o app e o backend nunca aconteceu.**

Cada rodada de relatório aumenta a superfície de coisas integradas e não
exercitadas. Hoje isso inclui autenticação inteira, upload com token,
WebSocket com `?token=`, escopo por usuário e agora as três rotas de
`/meetings`.

**Sugestão de ordem:** o teste conjunto **antes** da migração do histórico. O
roteiro de vocês (§8 do primeiro relatório) valida autenticação, upload,
WebSocket e pipeline ponta a ponta, que é a base de tudo o mais. A migração
do `/meetings` pode vir depois, com a base já provada — e aí um bug aparece
com uma causa possível, não com cinco.

Do nosso lado o que precisa estar de pé é a API e o worker
(`python -m app.worker`), e os logs de 401 e de fechamento do WS já estão
prontos para ajudar a investigar o que aparecer.

## 3. Três coisas para a migração do `/meetings`

O contrato completo está em `docs/RESPOSTA_MEETINGS_2026-09-07.md`. Estes
três pontos são os que mudam comportamento de tela, não só de parser:

- **Confirmação antes de remover.** Era uma operação local e reversível; agora
  apaga o WAV e o `result.json` do servidor. Não há lixeira, não há desfazer.
- **409 durante o processamento** é a única resposta genuinamente nova do
  `DELETE`. O `detail` traz o status atual.
- **O 4404 novo do WebSocket.** Reunião removida de outra tela enquanto a de
  processamento está aberta. Até ontem isso fechava com 1000 (encerramento
  normal), indistinguível de "o job terminou"; agora fecha com 4404. Vocês
  caem no polling, que responde 404 — e isso precisa virar **"reunião
  removida"**, não "o processamento falhou".

## 4. Dois detalhes do `/meetings` que costumam passar batido

- **Paginação existe e o default trunca.** `limit` tem default **50** (máximo
  200) e há `offset`. Um `GET /meetings` sem parâmetros devolve as 50 mais
  recentes **em silêncio** — quem passar de 50 reuniões simplesmente para de
  ver as antigas, sem erro nenhum na tela. Ordenação é `created_at DESC`.
- **A lista passa a exigir rede.** O cache local de vocês cobre o *resultado*
  de uma reunião, não a *lista* delas. Hoje o histórico funciona offline por
  acidente de arquitetura (é `shared_preferences`); depois da migração, não
  mais. Vale decidir o que a tela mostra sem conectividade antes de migrar,
  não depois.

---

## O que **não** vale pedir

Para não gastarem tempo: a ordenação já é `created_at DESC`, que é a que
vocês usam. A duração ficou de fora a pedido de vocês e concordamos.
E o polling **fica** — não vamos pedir a remoção dele.
