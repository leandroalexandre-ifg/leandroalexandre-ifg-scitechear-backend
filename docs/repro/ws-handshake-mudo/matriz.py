"""A matriz ORIGINAL da investigacao, com UMA amostra por celula.

NAO USE ESTE SCRIPT PARA CONCLUIR NADA. Ele esta versionado como evidencia de
como o diagnostico errado foi produzido: rodando so um cliente (o sincrono) e
uma tentativa por celula, ele "mostrou" que a falha exigia TLS *e*
permessage-deflate. Com n=30, as duas colunas de compressao ficam iguais - a
extensao nao tem nada a ver, e o cliente e que pendura.

Para medir de verdade, use matriz_clientes.py, que compara tres clientes.
"""
import ssl, sys, time
from websockets.sync.client import connect as ws_connect

ctx = ssl._create_unverified_context()
casos = [
    ("upstream direto     ws://127.0.0.1:18099", "ws://127.0.0.1:18099/ws/x", {}),
    ("Caddy HTTP puro     ws://localhost:18101", "ws://localhost:18101/ws/x?token=nao.e.um.jwt", {}),
    ("Caddy TLS interno   wss://localhost:18100", "wss://localhost:18100/ws/x?token=nao.e.um.jwt", {"ssl": ctx}),
]
for compressao in ("deflate (padrao)", "None"):
    print(f"\n--- compression={compressao} ---")
    for rotulo, url, extra in casos:
        kw = dict(extra)
        if compressao == "None":
            kw["compression"] = None
        t0 = time.monotonic()
        try:
            with ws_connect(url, open_timeout=6, **kw) as ws:
                msg = ws.recv(timeout=4)
                print(f"  {rotulo}: CONECTOU e recebeu {msg!r} (nao fechou)")
        except Exception as exc:
            code = getattr(exc, "code", None) or getattr(getattr(exc, "rcvd", None), "code", None)
            marca = f"close {code}" if code else f"{type(exc).__name__}"
            print(f"  {rotulo}: [{time.monotonic()-t0:5.2f}s] {marca}")
