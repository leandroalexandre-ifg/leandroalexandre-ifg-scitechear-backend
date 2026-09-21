> **NÃO ENVIAR. REFUTADO EM 2026-09-21, no mesmo dia em que foi escrito.**
>
> Este rascunho atribui ao Caddy um defeito que **não é dele**. Medições
> posteriores (n=15 a 50 por célula, contra o proxy de produção e contra
> Caddys descartáveis) mostraram que:
>
> - dois clientes independentes — um cliente TLS cru de stdlib e o cliente
>   **async** do próprio `websockets` — recebem o `101` e o close `4401`
>   através do mesmo proxy TLS em **20/20** e **15/15**;
> - quem pendura é só o cliente **`websockets.sync`**, e ele pendura também
>   com token válido, com job real e sem `permessage-deflate`;
> - a tabela abaixo, que separa "com deflate" de "sem compressão", é artefato
>   de **uma única amostra por célula** numa falha que ocorre em ~85% das
>   tentativas. Com n=30, as duas colunas ficam iguais.
>
> O arquivo fica versionado só para rastreabilidade do raciocínio. O relato
> correto do que foi observado está no `README.md` ao lado.

---

# WebSocket 101 + immediate close is never flushed over TLS when permessage-deflate is negotiated

> RASCUNHO — não enviado. Revisar e decidir a publicação (Leandro).

## Summary

When a WebSocket upstream accepts the handshake and closes the connection
**immediately** (101 followed at once by a close frame), the client behind a
Caddy TLS site receives **nothing**: no 101, no close frame. The connection
just hangs until the client times out.

It only happens when **both** conditions hold:

1. the site terminates TLS (`tls internal` is enough), and
2. `permessage-deflate` was negotiated (client sends
   `Sec-WebSocket-Extensions: permessage-deflate`, upstream echoes it).

Over plain HTTP the same close is delivered instantly. With compression
disabled on the client, the same TLS site delivers it instantly.

## Environment

- Caddy **v2.11.4** (current latest release at the time of writing), static
  binary, linux/amd64
- Ubuntu 24.04, kernel 6.8
- client: Python `websockets` 17.1 (its default is `permessage-deflate`)
- reproduced both with a FastAPI/uvicorn upstream and with the 60-line
  stdlib-only upstream below

## Isolation matrix

Same client, same upstream, only the path and the compression setting change:

| path | `permessage-deflate` | no compression |
|---|---|---|
| straight to the upstream (no Caddy) | close 4401 in 0.00 s | close 4401 in 0.00 s |
| through Caddy, plain HTTP | close 4401 in 0.00 s | close 4401 in 0.00 s |
| through Caddy, `tls internal` | **nothing; times out** | close 4401 in 0.00 s |

Waited **45 s** on the failing cell: nothing arrives. It is not a delay.

The failure surfaces at one of two points, varying between runs: usually the
handshake response (the 101) never arrives at all; sometimes the 101 arrives
and only the close frame is lost. Both are consistent with the response being
buffered and never flushed.

Not the cause, checked: HTTP/2 (the client speaks HTTP/1.1), the listener
address, the port, `flush_interval`, the log filter.

## Reproduction

`Caddyfile`:

```caddyfile
{
	admin off
	auto_https disable_redirects
}

https://localhost:18100 {
	bind tcp4/127.0.0.1
	tls internal
	reverse_proxy 127.0.0.1:18099
}

http://localhost:18101 {
	bind tcp4/127.0.0.1
	reverse_proxy 127.0.0.1:18099
}
```

Upstream (`upstream_ws.py`, stdlib only — accepts the handshake, echoes
`permessage-deflate` when asked, then closes at once with code 4401):
see `upstream_ws.py`, next to this file.

Client (`websockets` 17.1):

```python
from websockets.sync.client import connect
import ssl
ctx = ssl._create_unverified_context()

# hangs
with connect("wss://localhost:18100/ws", ssl=ctx) as ws:
    ws.recv(timeout=10)

# delivers close 4401 instantly
with connect("wss://localhost:18100/ws", ssl=ctx, compression=None) as ws:
    ws.recv(timeout=10)
```

## Why it matters

The close code is how the server tells the client *why* it was rejected — in
our case an expired auth token. Losing it turns a routine "your session
expired" into an indistinguishable "the network is down".
