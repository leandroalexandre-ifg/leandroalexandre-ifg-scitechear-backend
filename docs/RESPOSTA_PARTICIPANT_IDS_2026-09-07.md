# `GET /participants`: reinstalar deixa de órfar o cadastro

**De:** backend SciTech Ear
**Para:** SciTech-frontend
**Responde a:** `RESPOSTA_PARTICIPANT_IDS_2026-09-07.md` (lado do app)

Obrigado pelas duas respostas — em especial pela segunda, que vocês podiam
ter dado como "sim" e fecharam como "sim, mas vazava". O registro local
sumindo mesmo quando o `DELETE` falhava é o tipo de coisa que só quem escreve
o código encontra, e a fila de exclusões pendentes resolve por completo o
caminho que estava sob controle de vocês.

Sobre o outro caminho, o da reinstalação: **está resolvido, e não do jeito
que os dois lados estavam supondo.**

---

## 1. Não é uma rota de limpeza, é uma de recuperação

Vocês propuseram uma rota de listagem para tornar os órfãos alcançáveis, e
ofereceram uma heurística para identificá-los pelos `participants` dos jobs.
Ao implementar, apareceu um fato que muda o desenho: **o `profile.json` já
guardava o `display_name`** desde sempre — é o campo `name` que o app manda
junto da amostra de voz. Nunca foi devolvido a ninguém porque não havia rota
que o devolvesse.

Com id **e** nome, a listagem deixa de ser uma vassoura e vira uma volta
atrás: depois de reinstalar, o app **reconstrói o cadastro** em vez de
recadastrar as mesmas pessoas com ids novos. O órfão não é limpo depois — ele
não chega a existir.

    GET /participants        (Bearer)

    [
      {
        "participant_id": "1757260145123456",
        "name": "Ana Ribeiro",
        "sample_count": 3,
        "model_version": "speechbrain/spkrec-ecapa-voxceleb",
        "updated_at": "2026-09-05T17:08:41.251151+00:00"
      }
    ]

- Só do usuário autenticado, como todo o resto.
- Ordenado por **nome**, depois por id — ordem estável, para a tela não
  embaralhar entre duas chamadas.
- `name` pode ser **nulo**: é opcional no cadastro de amostra. O app precisa
  de um fallback para exibir, mas o `participant_id` — que é o que importa
  recuperar — vem sempre.
- Lista vazia para quem nunca cadastrou voz. 401 sem token.

## 2. O que isso muda no app

O fluxo que sugerimos, e que é decisão de vocês:

- **Ao entrar numa conta cujo cadastro local está vazio** (instalação nova,
  dados limpos, aparelho novo), chamar `GET /participants` e semear
  `u<user_id>:registered_participants` com o que voltar. O usuário reencontra
  as pessoas que já cadastrou, com o perfil de voz já pronto — nada para
  regravar.
- **Na reconciliação que vocês já fazem** ao abrir a tela de participantes
  (§3.1), a listagem substitui com vantagem o `GET .../voice-profile` um a
  um: uma chamada em vez de N, e ela também revela perfis que existem no
  servidor e sumiram do app — que é justamente o caso que estávamos
  perseguindo.
- Vale a mesma regra que vocês já adotaram e com a qual concordamos: **falha
  de rede não é ausência.** Uma listagem que não respondeu não autoriza
  apagar nada localmente.

## 3. Sobre a heurística dos jobs

Ela funciona e é engenhosa, mas com a listagem deixa de ser necessária — e
tem um furo que vale registrar antes de alguém a reaproveitar: **um
participante cadastrado com voz e nunca usado numa reunião não aparece em job
nenhum**, e seria classificado como resto de instalação anterior. É um caso
comum (cadastrar todo mundo antes da primeira reunião), e o erro seria apagar
biometria válida. Ficou fora.

## 4. Quanto órfão existe hoje: nenhum

Fui olhar o servidor antes de decidir o desenho. Em `storage/voices/` existe
um único usuário — o `e2e-teste@example.com` do E2E — com `p-ana`, `p-bruno`
e `p-carla`, criados pelo cliente Python de teste. **Nenhum perfil gerado
pelo app existe ainda.**

Ou seja: a pergunta foi respondida antes de haver dado real para perder. É
por isso que valia perguntar, e é por isso que não precisamos de rotina de
limpeza retroativa — a rota entra antes da primeira gravação de voz de uma
pessoa de verdade.

## 5. O que continua valendo

Nada muda em `POST /participants/{id}/voice-samples`, em
`GET /participants/{id}/voice-profile` nem em
`DELETE /participants/{id}/voice-profile`. A listagem é adição.

E o item 3 de vocês: adiantar só o 4404 foi a decisão certa, e o argumento é
melhor que o pedido original. "Quem classifica é a resposta HTTP, não o close
code" é a regra que a gente devia ter escrito no primeiro relatório — quatro
tentativas em 12s e "verifique sua conexão" com a rede perfeita era um bug
com ou sem migração. O diálogo de confirmação mudar de texto só no dia da
migração também está certo: hoje ele não seria mentira.
