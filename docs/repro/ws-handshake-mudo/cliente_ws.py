#!/usr/bin/env python3
"""Cliente WebSocket minimo (stdlib): diz se o 101 e o close chegaram, e quando.

    python3 cliente_ws.py 18099          # HTTP puro
    python3 cliente_ws.py 18100 --tls    # atraves do proxy
"""
import base64
import os
import socket
import ssl
import sys
import time

def main() -> int:
    porta = int(sys.argv[1])
    usar_tls = "--tls" in sys.argv
    sni = "localhost"
    if "--sni" in sys.argv:
        sni = sys.argv[sys.argv.index("--sni") + 1]
    espera = 8.0

    t0 = time.monotonic()
    sock = socket.create_connection(("127.0.0.1", porta), timeout=espera)
    if usar_tls:
        ctx = ssl._create_unverified_context()
        sock = ctx.wrap_socket(sock, server_hostname=sni)
    sock.settimeout(espera)

    chave = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        (
            "GET /ws/teste?token=invalido HTTP/1.1\r\n"
            f"Host: {sni}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {chave}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode()
    )

    dados = b""
    try:
        while True:
            pedaco = sock.recv(4096)
            if not pedaco:
                break
            dados += pedaco
            if b"\r\n\r\n" in dados and len(dados.split(b"\r\n\r\n", 1)[1]) >= 4:
                break
    except socket.timeout:
        print(f"[{time.monotonic() - t0:5.2f}s] TIMEOUT sem resposta completa. Recebido ate aqui: {dados[:120]!r}")
        return 2

    decorrido = time.monotonic() - t0
    cabecalho, _, corpo = dados.partition(b"\r\n\r\n")
    primeira = cabecalho.split(b"\r\n")[0].decode("latin-1")
    print(f"[{decorrido:5.2f}s] status: {primeira}")
    if len(corpo) >= 4 and corpo[0] == 0x88:
        codigo = int.from_bytes(corpo[2:4], "big")
        motivo = corpo[4 : 2 + corpo[1]].decode("utf-8", "replace")
        print(f"[{decorrido:5.2f}s] close recebido: codigo={codigo} motivo={motivo!r}")
        return 0
    print(f"[{decorrido:5.2f}s] nenhum frame de close no corpo: {corpo[:64]!r}")
    return 3


if __name__ == "__main__":
    sys.exit(main())
