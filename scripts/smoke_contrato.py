"""Exercita contra uma API REAL o contrato que os testes com TestClient não
alcançam: roteamento de verdade, handshake HTTP do WebSocket, close codes
como um cliente os observa.

Existe porque um bug passou pela suíte inteira: `close(4401)` antes do
`accept()` faz o servidor ASGI recusar o handshake com HTTP 403, e o cliente
nunca vê o 4401 — mas o TestClient entrega a mensagem de close direto pelo
ASGI e não distingue as duas ordens. Encontrado ao exercitar o servidor
implantado em 07/09/2026, com as 5 rotas novas do dia.

Rodar antes de um teste com o app, para separar "o app está errado" de "o
servidor está errado":

    .venv/bin/python -m scripts.smoke_contrato [http://127.0.0.1:18080]

Precisa de uma conta existente. Por padrão lê a do E2E em
tmp-e2e/credenciais.json (ver docs/DEPLOY.md); passe SMOKE_EMAIL/SMOKE_SENHA
no ambiente para usar outra.

DEIXA O BANCO COMO ENCONTROU: renomeia uma reunião e restaura o título, e o
job que sobe é removido no próprio teste do DELETE. Sobe um WAV de 0,1s de
silêncio — com o worker rodando, ele será processado antes que o DELETE
chegue, então prefira rodar com o worker parado se não quiser gastar GPU.
"""
import io
import json
import os
import sys
import wave
import httpx
from websockets.sync.client import connect as ws_connect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18080"
cred = {"email": os.environ.get("SMOKE_EMAIL"), "password": os.environ.get("SMOKE_SENHA")}
if not cred["email"]:
    cred = json.load(open(os.path.expanduser(
        os.environ.get("SMOKE_CREDENCIAIS", "/data/projects/leandro/scitechear/tmp-e2e/credenciais.json"))))
ok, fail = [], []

def check(nome, cond, detalhe=""):
    (ok if cond else fail).append(nome)
    print(f"  {'OK ' if cond else 'FALHA'} {nome}{(' — ' + str(detalhe)) if detalhe else ''}")

with httpx.Client(base_url=BASE, timeout=30) as c:
    r = c.post("/auth/login", json={"email": cred["email"], "password": cred["password"]})
    check("POST /auth/login", r.status_code == 200, r.status_code)
    tok = r.json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"

    print("\n[1] GET /participants — rota nova")
    r = c.get("/participants")
    check("200", r.status_code == 200, r.text[:120])
    perfis = r.json()
    check("lista os 3 perfis do E2E", len(perfis) == 3, [p["participant_id"] for p in perfis])
    check("devolve o nome junto do id", all(p["name"] for p in perfis), [p["name"] for p in perfis])
    check("ordenado por nome", [p["name"] for p in perfis] == sorted(p["name"] for p in perfis))

    print("\n[2] GET /meetings — campos novos")
    r = c.get("/meetings")
    check("200", r.status_code == 200)
    reunioes = r.json()
    check("tem reunioes", len(reunioes) > 0, len(reunioes))
    m = reunioes[0]
    check("campo participants presente", "participants" in m, list(m))
    check("participants tem id e name", all({"id","name"} <= set(p) for p in m["participants"]), m["participants"])
    check("campo error presente", "error" in m)

    print("\n[3] PATCH /meetings/{id} — renomear")
    jid, titulo_antigo = m["job_id"], m["title"]
    r = c.patch(f"/meetings/{jid}", json={"title": "renomeada-pelo-smoke"})
    check("200", r.status_code == 200, r.text[:120])
    check("titulo trocado", r.json()["title"] == "renomeada-pelo-smoke")
    check("persistiu", next(x for x in c.get("/meetings").json() if x["job_id"] == jid)["title"] == "renomeada-pelo-smoke")
    c.patch(f"/meetings/{jid}", json={"title": titulo_antigo})
    check("restaurado", next(x for x in c.get("/meetings").json() if x["job_id"] == jid)["title"] == titulo_antigo)

    print("\n[4] POST /upload + DELETE /meetings/{id}")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00\x00" * 1600)
    r = c.post("/upload",
               files={"file": ("smoke.wav", buf.getvalue(), "audio/wav")},
               data={"title": "smoke-test", "participants": json.dumps([{"id": "p-ana", "name": "Ana Ribeiro"}])})
    check("202 no upload", r.status_code == 202, r.text[:120])
    novo = r.json()["job_id"]

    print("\n[5] WS /ws/{id} — token na query e fechamento 4404")
    with ws_connect(f"{BASE.replace("http", "ws", 1)}/ws/{novo}?token={tok}") as ws:
        primeira = json.loads(ws.recv(timeout=10))
        check("WS empurra o estado atual", primeira["status"] == "queued", primeira["status"])
        r = c.delete(f"/meetings/{novo}")
        check("204 no DELETE", r.status_code == 204, r.status_code)
        try:
            ws.recv(timeout=10)
            check("WS fecha ao remover a reuniao", False, "nao fechou")
        except Exception as exc:
            code = getattr(exc, "code", None) or getattr(getattr(exc, "rcvd", None), "code", None)
            check("WS fecha com 4404 (correcao de hoje)", code == 4404, f"code={code}")

    check("sumiu do /meetings", all(x["job_id"] != novo for x in c.get("/meetings").json()))
    check("status responde 404", c.get(f"/status/{novo}").status_code == 404)

    print("\n[6] WS com token invalido — 4401")
    try:
        with ws_connect(f"{BASE.replace("http", "ws", 1)}/ws/{jid}?token=nao.e.um.jwt") as ws:
            ws.recv(timeout=5)
        check("4401", False, "conectou")
    except Exception as exc:
        code = getattr(exc, "code", None) or getattr(getattr(exc, "rcvd", None), "code", None)
        check("fecha com 4401", code == 4401, f"code={code}")

print(f"\n=== {len(ok)} OK, {len(fail)} falhas ===")
if fail: print("FALHARAM:", fail); sys.exit(1)
