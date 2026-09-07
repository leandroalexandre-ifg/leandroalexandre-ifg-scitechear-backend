# Plano de Exposição de Rede — SciTech Ear · Backend

Plano para (a) o tablet deixar de depender do cabo até o MacBook e (b) o
backend chegar à internet com o app conectado. Escrito em 2026-09-07; **nada
aqui foi executado** — é o roteiro, e cada etapa diz de quem depende.

Complementa `DEPLOY.md` (estado atual da rede e dos serviços) e `TLS.md` (o
proxy e o lado Flutter). Onde houver divergência, aqueles dois são a fonte de
verdade sobre o que existe; este documento é sobre o que falta.

## O problema, com precisão

Hoje o tablet só alcança o backend porque o MacBook faz a ponte: um túnel SSH
(`ssh -N -L 8000:127.0.0.1:18080`) mais `adb reverse tcp:8000 tcp:8000` pelo
USB. O app aponta para `127.0.0.1:8000` sem saber que do outro lado há um
túnel — **quem carrega o tráfego é o cabo**.

O detalhe que muda o plano: o vínculo é de **rede**, não de *bundle*. A build
de desenvolvimento roda sozinha depois de instalada, então **dar ao tablet um
endereço alcançável já corta o cabo** — não é preciso gerar build nova nem
publicar em loja.

E isso separa as duas metas, que costumam ser tratadas como uma só:

- **Tirar o cabo** exige apenas a rede interna do IFG.
- **Chegar à internet** é outro problema, bem mais caro, e não é pré-requisito
  do primeiro.

## Três coisas que se confundem — e só a terceira é "internet"

Medido em 2026-09-07:

| | O que faz | O que **não** faz |
|---|---|---|
| Registro DNS | Dá nome a um endereço; resolve o problema do IP que muda | Não expõe nada |
| Porta liberada no `ufw` | Torna alcançável por quem já roteia até a máquina (a rede do IFG) | Não é internet |
| IP público / DNAT | Coloca de fato na internet | Só o CTI pode criar |

A máquina tem `10.4.254.201/16` — endereço **privado** (RFC 1918), atrás de
NAT. A saída funciona (`example.com` respondeu 200 em 0,13 s) e o endereço
público visto de fora é `200.17.57.4`, **mas esse é o NAT de saída**,
compartilhado: ele deixa o servidor *iniciar* conexões e não deixa ninguém de
fora iniciar uma para cá. **O NAT do IFG é de mão única.**

Por isso "liberar a porta" e "ter IP público" não são a mesma coisa, e pedir a
primeira achando que se está pedindo a segunda leva a um piloto que funciona no
laboratório e falha na demonstração externa.

---

# Etapa 1 — Rede interna do IFG (tira o cabo)

O proxy Caddy já termina TLS e repassa para a API em loopback, verificado ponta
a ponta (`TLS.md`). Ele está escutando em `127.0.0.1:18443`: falta a porta
existir e o `bind` virar.

## 1.1 Antes de falar com o admin: a faixa do tablet

`DEPLOY.md` recomenda restringir a regra "à faixa do laboratório", mas o tablet
estará no **wi-fi**, que provavelmente não é a faixa das máquinas cabeadas.
Pedir a regra errada custa um segundo ciclo com o admin.

Conectar o tablet ao wi-fi que ele usará e anotar o IP (Configurações → Wi-Fi →
rede conectada). É o dado que falta para o pedido sair completo.

## 1.2 Pedido ao admin do NumbERS

Dois itens, ambos exigindo root e portanto dele:

1. **Liberar TCP 18443** no `ufw`, restrito à faixa descoberta em 1.1 — não à
   `10.4.0.0/16` inteira, que é a instituição toda.
2. **Reserva de DHCP** para o MAC da `eno1`, fixando `10.4.254.201`.

A reserva não é conforto: o certificado tem `IP:10.4.254.201` como **único
SAN** e o `default_sni` do `Caddyfile` carrega o mesmo endereço. Uma troca de
lease quebra o handshake *e* faz o app perder o servidor — dois pontos de falha
de uma vez.

## 1.3 Endurecer antes de a porta existir

Três valores ainda rodam no **default implícito**, o que só é inofensivo
enquanto tudo está em loopback. A partir do momento em que existe uma porta,
viram decisão que ninguém tomou. Explicitar no `.env` **antes** da virada:

| Variável | Hoje | Passa a ser | Porquê |
|---|---|---|---|
| `CORS_ALLOW_ORIGINS` | `*` (default) | vazio | Não há cliente web no projeto; o app Android é nativo, não manda `Origin` e não é afetado |
| `MAX_UPLOAD_MB` | 300 (default) | `300` | Vira decisão registrada em vez de omissão |
| `MAX_VOICE_SAMPLE_MB` | 25 (default) | `25` | idem |

`AUTH_ALLOWED_EMAIL_DOMAINS` **já está** em `ifg.edu.br` — item cumprido.

> **Armadilha ao fazer isso.**
> `tests/test_cors.py::test_default_preserva_o_comportamento_de_desenvolvimento`
> afirma um *default* chamando `Settings()`, que lê o `.env` do servidor — ou
> seja, mede o que a produção configurou, não o default do campo. Ele passa
> hoje **só porque `CORS_ALLOW_ORIGINS` está ausente do `.env`**. No momento em
> que a variável for explicitada, o teste quebra sem que nada do comportamento
> tenha mudado. A saída é `Settings(_env_file=None)`.

Lembrar que `EnvironmentFile=` é lido no **start**: depois de mexer no `.env`,
reiniciar `scitechear-api`, `scitechear-worker` e `ollama`.

## 1.4 Virar o bind

Uma linha em `deploy/Caddyfile`, no bloco `https://10.4.254.201:18443`:

    bind 127.0.0.1   →   bind 0.0.0.0

`0.0.0.0`, **nunca** o IP da `eno1`: o endereço vem por DHCP, e bind num IP que
muda faz o serviço falhar com *cannot assign requested address* e entrar em
loop de restart. Aplicar com `systemctl --user reload scitechear-proxy` —
*reload*, não restart, para não derrubar conexão.

**`scitechear-api.service` não muda.** A API continua em `127.0.0.1:18080`;
quem vai para a rede é só o proxy. A regra "a API nunca escuta na rede"
permanece.

## 1.5 Lado do app (repositório SciTech-frontend)

O procedimento completo está em `TLS.md`; o essencial:

1. Apontar via `--dart-define`: `SCITECH_API_BASE_URL=https://10.4.254.201:18443`
   e `SCITECH_WS_BASE_URL=wss://10.4.254.201:18443`.
2. **Carregar a raiz da CA no `SecurityContext`** — o passo que a maioria das
   tentativas erra. `network_security_config.xml` é aplicado pelo *framework*
   do Android, mas o `dart:io HttpClient` (e o `WebSocket` por trás dele) usa
   BoringSSL e não passa por ali. Usar **o mesmo `HttpClient` no WebSocket**
   (`IOWebSocketChannel.connect(uri, customClient: httpClient)`), senão o
   `wss://` falha sozinho enquanto o REST funciona — sintoma que confunde.
3. Copiar `deploy/scitechear-root-ca.crt` para o app (assets + `res/raw`).
4. Manter o `network_security_config.xml` mesmo assim: cobre WebView e impede o
   app de aceitar HTTP puro por engano.

APK release é desejável para o piloto, mas **não** é pré-requisito para cortar
o cabo.

## 1.6 Verificação, em ordem

Parar no primeiro que falhar:

1. `ss -ltn` mostra `0.0.0.0:18443` e `127.0.0.1:18080`. Se aparecer
   `0.0.0.0:18080`, parar tudo — a API não pode estar na rede.
2. De outra máquina: `curl --cacert deploy/scitechear-root-ca.crt https://10.4.254.201:18443/health`
3. `.venv/bin/python -m scripts.smoke_contrato https://10.4.254.201:18443` —
   referência: 21 OK, 0 falhas.
4. **Upload grande através do proxy** — pendência aberta em `TLS.md`, nunca
   testada. Um WAV perto do teto de 300 MB.
5. Do tablet **sem cabo**: login, upload, WebSocket até `done`, resultado.
6. Sem vazamento: após uma conexão WS real, nem
   `journalctl --user -u scitechear-proxy` nem `-u scitechear-api` podem conter
   JWT. Os dois filtros de redação são independentes e ambos necessários.

---

# Etapa 2 — Internet

Corre em paralelo, sem bloquear a Etapa 1.

## 2.1 Pedido ao CTI

Para `10.4.254.201`:

- **Registro DNS público** (ex.: `scitechear.ifg.edu.br`). Note que
  `numbersia.ifg.edu.br` não resolve hoje, e o *search domain* da máquina é
  `ifg.br`, não `ifg.edu.br`.
- **DNAT de entrada** de uma porta pública para `10.4.254.201:18443`, ou IP
  público dedicado.

**Basta a 443**, e isso simplifica o pedido: o Caddy emite certificado ACME
pelo desafio **TLS-ALPN-01, que roda na própria 443** — não é preciso abrir a
80.

## 2.2 Trocar a CA interna por certificado público

Com nome DNS resolvendo, o site no `Caddyfile` passa a ser o nome público e
`tls internal` sai em favor de ACME. Dois efeitos colaterais bons: o
`default_sni` deixa de ser necessário (ele só existe porque cliente que fala
com IP não manda SNI), e o app deixa de precisar da raiz embutida — manter
`withTrustedRoots: true` faz a transição sem quebrar nada.

## 2.3 O que a internet exige e a rede interna não

- **Rate limiting de `/auth`**: dimensionado para um universo pequeno de
  clientes institucionais. O registro conta por IP, e na internet um IP deixa
  de identificar alguém.
- **Token do WebSocket na query string**: os filtros de redação cobrem o Caddy
  e a API, mas qualquer proxy ou CDN que entre na frente reabre o vazamento. Se
  a topologia ganhar camadas, mover o token para subprotocolo deixa de ser
  opcional.
- **Revisão de segurança** do diff antes de expor.

---

## De quem depende cada coisa

| Bloqueio | Quem resolve | O que trava |
|---|---|---|
| Regra de `ufw` na 18443 + reserva de DHCP | Admin do NumbERS | Etapa 1 inteira |
| DNS público + DNAT | CTI do IFG | Etapa 2 inteira |
| Mudanças no app Flutter | Leandro (outro repositório) | Passo 1.5 |

Nada no lado do servidor exige root: as mudanças são no checkout e em unidades
de usuário, no mesmo padrão do resto do projeto.
