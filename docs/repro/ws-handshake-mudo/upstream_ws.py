#!/usr/bin/env python3
"""Upstream WebSocket minimo, so stdlib: aceita o handshake e fecha na hora.

Reproduz o que a API do SciTech Ear faz com um token invalido: responde 101 e
emite imediatamente um frame de close com codigo 4401. Sem FastAPI, sem
uvicorn, sem dependencia nenhuma - de proposito, para o relato ser reproduzivel
por quem nao conhece o projeto.

    python3 upstream_ws.py 18099 fecha      # 101 + close(4401) imediato
    python3 upstream_ws.py 18099 fecha 50   # idem, mas 50 ms depois do 101
    python3 upstream_ws.py 18099 mantem     # 101 e deixa aberto (controle)

O terceiro argumento e o atraso em milissegundos entre o 101 e o frame de
close. Ele existe para provar o mecanismo: com 0 ms o close se perde sob TLS
na maioria das tentativas; bastam algumas dezenas de ms para ele passar
sempre. E a diferenca entre as duas colunas da matriz de atraso.
"""
import base64
import hashlib
import socket
import sys
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def frame_close(codigo: int, motivo: bytes = b"") -> bytes:
    carga = codigo.to_bytes(2, "big") + motivo
    return bytes([0x88, len(carga)]) + carga


def atender(conn: socket.socket, modo: str, atraso_ms: int = 0) -> None:
    with conn:
        pedido = b""
        conn.settimeout(5)
        try:
            while b"\r\n\r\n" not in pedido:
                pedaco = conn.recv(4096)
                if not pedaco:
                    return
                pedido += pedaco
        except socket.timeout:
            return

        chave = ""
        pediu_deflate = False
        for linha in pedido.decode("latin-1").split("\r\n"):
            if linha.lower().startswith("sec-websocket-key:"):
                chave = linha.split(":", 1)[1].strip()
            if linha.lower().startswith("sec-websocket-extensions:") and "permessage-deflate" in linha.lower():
                pediu_deflate = True
        aceite = base64.b64encode(hashlib.sha1((chave + GUID).encode()).digest()).decode()

        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {aceite}\r\n"
                + ("Sec-WebSocket-Extensions: permessage-deflate\r\n" if pediu_deflate else "")
                + "\r\n"
            ).encode()
        )
        if modo == "fecha":
            # com atraso_ms=0 nao ha pausa nenhuma: e exatamente o close
            # instantaneo que se perde atraves do TLS
            if atraso_ms:
                time.sleep(atraso_ms / 1000)
            conn.sendall(frame_close(4401, b"token invalido"))
            conn.shutdown(socket.SHUT_WR)
            time.sleep(0.2)
        else:
            time.sleep(10)
            conn.sendall(frame_close(1000, b"fim"))


def main() -> int:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 18099
    modo = sys.argv[2] if len(sys.argv) > 2 else "fecha"
    atraso_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", porta))
    srv.listen(8)
    print(f"upstream em 127.0.0.1:{porta} modo={modo} atraso={atraso_ms}ms", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(
            target=atender, args=(conn, modo, atraso_ms), daemon=True
        ).start()


if __name__ == "__main__":
    sys.exit(main())
