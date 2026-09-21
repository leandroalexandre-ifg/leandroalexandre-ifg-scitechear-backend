#!/usr/bin/env python3
"""Compara TRES clientes WebSocket contra o mesmo alvo, n vezes cada.

O ponto do script: mostrar que o servidor entrega o handshake corretamente e
que so um dos clientes pendura. Rode contra o proxy TLS e contra a API direta.

    python3 matriz_clientes.py wss://200.17.57.229/ws/x?token=invalido 20 \
        --cafile ../../../deploy/scitechear-root-ca.crt [--timeout 6] [--orcamento 180]

CUSTO, porque ele nao e obvio e ja custou uma sessao: cada tentativa que
pendura gasta ate 2x o timeout (o do handshake MAIS o do recv). Um lote de
n=20 nos tres clientes, com tudo pendurando, chega a 20*12*3 = 12 MINUTOS.
Por isso existe o --orcamento: o script mede o teto ANTES de comecar, avisa,
e interrompe o lote quando o tempo total estoura. Nunca rode isto contra o
servidor real sem olhar o teto que ele imprime.

Clientes comparados:
  sync  - websockets.sync.client  (o que o smoke usava ate 21/09/2026)
  async - websockets.connect      (asyncio, mesmo pacote, mesma versao)
  cru   - socket + ssl da stdlib  (sem o pacote; ver cliente_ws.py)
"""
import asyncio
import base64
import os
import socket
import ssl
import sys
import time
from urllib.parse import urlparse

GUID_HEADERS = (
    "GET {caminho} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
    "Connection: Upgrade\r\nSec-WebSocket-Key: {chave}\r\n"
    "Sec-WebSocket-Version: 13\r\n\r\n"
)


def contexto(cafile):
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl._create_unverified_context()


def tenta_sync(url, cafile, espera):
    from websockets.sync.client import connect

    kw = {"ssl": contexto(cafile)} if url.startswith("wss://") else {}
    try:
        with connect(url, open_timeout=espera, **kw) as ws:
            ws.recv(timeout=espera)
        return "entregou"
    except Exception as exc:
        return "entregou" if _codigo(exc) else "pendurou"


def tenta_async(url, cafile, espera):
    import websockets

    kw = {"ssl": contexto(cafile)} if url.startswith("wss://") else {}

    async def corpo():
        try:
            async with websockets.connect(url, open_timeout=espera, **kw) as ws:
                await asyncio.wait_for(ws.recv(), timeout=espera)
            return "entregou"
        except Exception as exc:
            return "entregou" if _codigo(exc) else "pendurou"

    return asyncio.run(corpo())


def tenta_cru(url, cafile, espera):
    """Handshake na mao: nao pede permessage-deflate, le os bytes direto."""
    u = urlparse(url)
    porta = u.port or (443 if u.scheme == "wss" else 80)
    caminho = u.path + (f"?{u.query}" if u.query else "")
    sock = socket.create_connection((u.hostname, porta), timeout=espera)
    if u.scheme == "wss":
        sock = contexto(cafile).wrap_socket(sock, server_hostname=u.hostname)
    sock.settimeout(espera)
    chave = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        GUID_HEADERS.format(caminho=caminho, host=u.hostname, chave=chave).encode()
    )
    dados = b""
    try:
        while b"\r\n\r\n" not in dados or len(dados.split(b"\r\n\r\n", 1)[1]) < 4:
            pedaco = sock.recv(4096)
            if not pedaco:
                break
            dados += pedaco
    except socket.timeout:
        return "pendurou"
    finally:
        sock.close()
    corpo = dados.partition(b"\r\n\r\n")[2]
    return "entregou" if len(corpo) >= 4 and corpo[0] == 0x88 else "pendurou"


def _codigo(exc):
    return getattr(exc, "code", None) or getattr(getattr(exc, "rcvd", None), "code", None)


def _opcao(nome, padrao, tipo=int):
    return tipo(sys.argv[sys.argv.index(nome) + 1]) if nome in sys.argv else padrao


def main() -> int:
    url = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    cafile = _opcao("--cafile", None, str)
    espera = _opcao("--timeout", 6)
    orcamento = _opcao("--orcamento", 180)

    clientes = (("sync ", tenta_sync), ("async", tenta_async), ("cru  ", tenta_cru))
    teto = n * 2 * espera * len(clientes)
    print(f"alvo: {url}   n={n} por cliente   timeout={espera}s/tentativa")
    print(
        f"teto se tudo pendurar: {teto}s (~{teto // 60} min); "
        f"orcamento total: {orcamento}s\n"
    )

    inicio = time.monotonic()
    estourou = False
    for rotulo, fn in clientes:
        entregou = feitas = 0
        t0 = time.monotonic()
        for _ in range(n):
            if time.monotonic() - inicio > orcamento:
                estourou = True
                break
            try:
                if fn(url, cafile, espera) == "entregou":
                    entregou += 1
            except Exception as exc:  # falha de conexao, nao de handshake
                print(f"  {rotulo}: erro {type(exc).__name__}: {exc}")
                break
            feitas += 1
        sufixo = "  [ORCAMENTO ESTOUROU]" if estourou else ""
        print(
            f"  {rotulo}: entregou {entregou:2d}/{feitas}   "
            f"pendurou {feitas - entregou:2d}/{feitas}"
            f"   ({time.monotonic() - t0:.0f}s){sufixo}"
        )
        if estourou:
            break
    if estourou:
        print(
            f"\nInterrompido por --orcamento ({orcamento}s). Os numeros acima valem"
            " so para as tentativas efetivamente feitas."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
