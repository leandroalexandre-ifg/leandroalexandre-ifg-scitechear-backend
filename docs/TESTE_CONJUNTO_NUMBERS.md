# Teste conjunto com o backend no NumbERS — preparação

**Data:** 07/09/2026
**Substitui:** o passo 5 do roteiro do frontend (`adb reverse` + `127.0.0.1:8000`),
que pressupunha o backend na máquina de desenvolvimento.
**Não substitui:** os passos 3, 4, 6 e 7, que seguem iguais.

A decisão foi rodar o teste conjunto contra o backend **implantado**, não
contra um backend local. Isso vale mais — é o servidor de verdade, com a
allowlist institucional, o worker dedicado, a GPU compartilhada e o journal
onde os erros aparecem — e custa uma etapa a mais na conexão.

**O app não muda.** Ele continua apontando para `http://127.0.0.1:8000`; o
que muda é o que existe do outro lado dessa porta.

---

## 1. A cadeia até o aparelho

    aparelho Android          adb reverse (USB)      máquina de dev
      127.0.0.1:8000  ──────────────────────────▶  127.0.0.1:8000
                                                          │
                                                    ssh -L (VPN do IFG)
                                                          ▼
                                                    NumbERS 127.0.0.1:18080
                                                          (a API)

Na **máquina de desenvolvimento**, nesta ordem:

```bash
# 1. VPN do IFG ligada (sem ela o NumbERS não é alcançável)

# 2. túnel: porta 8000 local -> API do servidor. Deixe rodando.
ssh -N -L 8000:127.0.0.1:18080 leandro@10.4.254.201

# 3. com o aparelho conectado por USB, em outro terminal:
adb reverse tcp:8000 tcp:8000

# 4. confirme antes de abrir o app:
curl -s http://127.0.0.1:8000/health     # {"status":"ok"}
```

`numbersia.ifg.edu.br` **não resolve** — use o IP. O search domain da máquina
é `ifg.br`, não `ifg.edu.br`.

Se o `/health` responder e o app não conectar, o problema está no
`adb reverse`, não no túnel: `adb reverse --list` deve mostrar a linha.

## 2. Por que não é HTTPS nesta rodada

Existe um proxy TLS no ar (`scitechear-proxy`, Caddy em `127.0.0.1:18443`, ver
`docs/TLS.md`), e ele **não** é o caminho aqui. Usá-lo exigiria que o SNI
fosse `10.4.254.201` (único SAN do certificado) e que a CA interna estivesse
na build do app — duas variáveis novas num teste que já tem muitas.

E não há perda de segurança em ficar sem ele: **nada trafega em claro na
rede.** Aparelho→máquina de dev é USB; máquina de dev→NumbERS é o próprio
SSH. O HTTP puro só existe dentro de cada máquina, em loopback. É exatamente
a razão pela qual a API nunca escutou na `10.4.0.0/16`.

HTTPS ponta a ponta entra numa rodada seguinte, quando o que falhar tiver uma
causa provável.

## 3. O que muda por tudo chegar como `127.0.0.1`

Do ponto de vista da API, todas as requisições vêm do loopback — inclusive as
do aparelho. Isso afeta um limite:

| | Escopo | Limite | Consequência no teste |
|---|---|---|---|
| `/auth/register` | por **IP** | 10 falhas / 60 min | **as duas contas e qualquer outro cliente dividem o mesmo balde** |
| `/auth/login` | por **e-mail** | 5 falhas / 15 min | não é compartilhado; cada conta tem o seu |

Um 403 de domínio errado e um 409 de e-mail repetido **contam como falha** no
registro. Dez enganos e o cadastro trava por uma hora para todo mundo.

Estado em 07/09/2026 20:19 UTC: **balde limpo**, as 6 tentativas registradas
são de 05/09 e já saíram da janela. Os 10 estão disponíveis.

## 4. As duas contas

Obrigatoriamente `@ifg.edu.br` — a allowlist está ativa
(`AUTH_ALLOWED_EMAIL_DOMAINS=ifg.edu.br`) e não será desligada para o teste.

Não é preciso ter duas caixas de correio: o backend não verifica e-mail, e a
allowlist olha só o domínio depois do último `@`. **Plus-addressing funciona**
e foi verificado:

    leandro.freitas+a@ifg.edu.br
    leandro.freitas+b@ifg.edu.br

Senha de **no mínimo 8 caracteres**. O cadastro é feito **pelo app**, não por
`curl` — o passo 3 do roteiro é parte do que está sendo testado (o 403, o 409
e o mínimo de 8 são justamente o que a rodada de ajustes mexeu).

## 5. Antes de começar, no servidor

```bash
cd /data/projects/leandro/leandroalexandre-ifg-scitechear-backend

systemctl --user is-active scitechear-api scitechear-worker   # os dois: active
.venv/bin/python -m scripts.smoke_contrato                    # 21 OK, 0 falhas
nvidia-smi --query-gpu=memory.used --format=csv,noheader      # GPU livre?
```

O `smoke_contrato` deixa o lado do servidor verde **antes** de o aparelho
entrar — que é o combinado: qualquer falha do dia vira pista, não
investigação. Ele deixa o banco como encontrou.

A GPU é **compartilhada** com outro pesquisador (ComfyUI) e não há fila.
Estava livre em 07/09 20:19 UTC (2 MiB de 32 GB). Se estiver ocupada no dia, o
job não falha — fica mais lento, ou espera VRAM.

## 6. Quanto tempo esperar

No E2E da Fase 8, neste mesmo servidor, reuniões de 39–80s completaram o
pipeline em **10–15s** no total. A ordem de grandeza para uma reunião de 10
minutos é de **minutos, não segundos** — e o estágio que mais cresce é
`extracting` (Ollama), que já era a maior fatia e escala com o tamanho da
transcrição, não com a duração do áudio.

Não estranhe o `identifying` não aparecer na tela: ele levou 0,07s no E2E,
menos que o intervalo de 1s do WebSocket. É o comportamento documentado, não
um estágio pulado.

## 7. Quando algo falhar

O journal do servidor tem o que o app não consegue ver:

```bash
journalctl --user -u scitechear-api -f      # 401 com motivo, fechamento de WS com código
journalctl --user -u scitechear-worker -f   # estágios do pipeline, erro por código
```

As linhas que foram acrescentadas para este teste:

    401 em POST /upload: cabeçalho Authorization ausente ou sem o prefixo 'Bearer '.
    401 em GET /status/<id>: Token de acesso inválido ou expirado.
    WS /ws/<id> fechado com 4401: token de acesso ausente ou inválido.
    WS /ws/<id> fechado com 4404: job inexistente ou de outro dono (...).

Nenhuma delas contém o token.

**Se o app falhar e o `smoke_contrato` estiver verde, o servidor está certo** —
comece a investigar pelo app. É para isso que ele existe.

## 8. O que este teste prova, e o que não prova

Prova o que nunca foi exercitado: o app falando com o servidor. Sessão,
renovação de token no meio de um upload multipart, WebSocket com `?token=`
através de um túnel, escopo por usuário entre duas contas reais, e o pipeline
ponta a ponta com áudio de reunião de verdade — que também é a primeira vez
que não é áudio sintetizado por TTS.

Não prova nada sobre alcance de rede: continua tudo em loopback, através de um
túnel. A API alcançável pela rede do IFG, com TLS, é outro assunto e depende
do admin (ver `docs/DEPLOY.md` e `docs/TLS.md`).
