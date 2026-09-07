# As cinco rotas novas, exercitadas contra a API real

**De:** backend SciTech Ear
**Para:** SciTech-frontend
**Data:** 07/09/2026 — API implantada no NumbERS, `main`

Vocês fecharam o último relatório notando que a lista de rotas integradas e
nunca exercitadas contra o servidor tinha ganhado mais uma no dia. Estava
certo, e a resposta a isso não era outro documento.

As cinco foram exercitadas contra a API implantada, com um cliente HTTP e
WebSocket de verdade: **21 verificações, uma falha, corrigida.** Continua sem
ser o app falando com o servidor — mas o que dava para tirar da lista sem
depender de agenda de ninguém, saiu.

## O bug: o `4401` nunca chegava a cliente nenhum

`WS /ws/{job_id}` chamava `close(4401)` **antes** do `accept()`. Nessa ordem o
servidor ASGI recusa o próprio handshake com **HTTP 403**, e o cliente recebe
um erro de conexão — sem close code. O `4401` que os nossos três documentos
prometeram a vocês, e que vocês trataram no app, **não existia na prática**.

O `4404` funcionava porque aquele caminho aceita antes de fechar. Dois
`close(44xx)` no mesmo handler, com aparência idêntica no código e
comportamento diferente na rede.

Por que passou por tudo: os 12 testes de WebSocket usam o `TestClient` do
Starlette, que entrega a mensagem de close direto pelo ASGI, sem handshake
HTTP — para ele, fechar antes ou depois do `accept()` dá no mesmo. Só um
cliente real distingue.

**Corrigido** (`accept()` antes do `close(4401)`, igual ao 4404) e coberto por
`tests/test_ws_codigos_de_fechamento_reais.py`, que sobe um uvicorn de
verdade e falha com `HTTP 403` se alguém reintroduzir a ordem antiga.

**O que isso significa para vocês:** o tratamento de 4401 que já existe no app
passa a funcionar. Não há nada a mudar — o contrato é o que sempre dissemos
que era; era o servidor que não o cumpria. Se em algum teste anterior vocês
viram uma falha de conexão em vez do 4401, era isto.

## Uma correção de contrato, achada ao ler o relatório de vocês

Vocês escreveram que, na fila de exclusões pendentes, "404 encerra a
pendência". **`DELETE /participants/{id}/voice-profile` nunca devolve 404** —
devolve **204 sempre**, inclusive para perfil que não existe. É idempotente
por desenho, mesma escolha do `/auth/logout`: o repositório sabe que não achou
nada, e a rota descarta essa informação de propósito, para não revelar a
diferença entre "não é seu" e "não existe".

Se a fila desarma em 204 **ou** 404, está tudo certo e a rama do 404 é código
morto. Se desarma **só** em 404, a pendência nunca sai da fila.

## O que passou

| Rota | Verificado |
|---|---|
| `GET /participants` | 200, os 3 perfis do E2E com nome junto do id, ordem por nome |
| `GET /meetings` | `participants` com `{id, name}` e `error` presentes no corpo real |
| `PATCH /meetings/{id}` | renomeia, persiste, e o título restaurado depois |
| `POST /upload` + `DELETE /meetings/{id}` | 202 e 204; sumiu do `/meetings`, `/status` responde 404, e o diretório saiu do disco |
| `WS /ws/{id}` | empurra o estado ao conectar; fecha **4404** ao remover a reunião com a conexão aberta; fecha **4401** com token ausente e com token malformado |

O teste ficou no repositório como `scripts/smoke_contrato.py`, para ser
repetido antes do teste conjunto:

    .venv/bin/python -m scripts.smoke_contrato [url]

Serve para separar "o app está errado" de "o servidor está errado" no dia em
que algo falhar com o aparelho na mão. Deixa o banco como encontrou.

## O que continua sem verificação

O mesmo de sempre, e agora é o único item: **o app nunca falou com o
servidor.** O que foi exercitado hoje é o contrato visto por um cliente
Python. O que ele não cobre é tudo o que é do app — a sessão, a renovação de
token no meio de um upload, o `adb reverse`, a tela.

Nenhuma pressa e nenhuma data. Mas a lista, que vocês notaram estar crescendo,
hoje diminuiu pela primeira vez.
