# Plano de Exposição de Rede — SciTech Ear · Backend

Plano para o app alcançar o backend sem o cabo até o MacBook. Escrito em
2026-09-07 e **reescrito em 2026-09-21**, quando a máquina ganhou IP público e
metade do plano deixou de fazer sentido.

Complementa `DEPLOY.md` (estado atual da rede e dos serviços) e `TLS.md` (o
proxy e o lado Flutter). Onde houver divergência, aqueles dois são a fonte de
verdade sobre o que existe; este documento é sobre o que falta.

---

## O que mudou em 2026-09-21

A versão anterior deste plano tinha duas etapas: a **Etapa 1** punha o backend
na rede interna do IFG, e a **Etapa 2**, bem mais cara, pedia ao CTI um DNAT ou
IP público para chegar à internet.

**A Etapa 2 foi atendida antes de ser pedida.** O admin trocou o endereçamento
da `eno1`: a máquina saiu de `10.4.254.201/16` privada atrás de NAT e passou a
`200.17.57.229/28` **pública e roteável**, estática no netplan. Verificado:
`curl ifconfig.me` devolve `200.17.57.229`, o mesmo endereço da interface — não
mais o `200.17.57.4` de NAT de saída compartilhado. O roteamento agora é direto
nos dois sentidos.

Com isso as duas etapas colapsaram numa só, e o que sobrou é mais curto do que
qualquer uma das duas era.

**O que caiu do plano:**

| Item | Por quê |
|---|---|
| Pedido de DNAT ao CTI | Atendido, e de forma melhor: IP próprio em vez de porta mapeada |
| Reserva de DHCP ao admin | Não há lease para reservar — o endereço é estático |
| Descobrir a faixa do wi-fi do tablet | Não há mais faixa interna entre o aparelho e a máquina |
| Regra de `ufw` restrita à faixa do laboratório | Mesma razão: o escopo agora é decidido por allowlist e rate limit, não por CIDR |

**O que apareceu:**

| Item | Por quê |
|---|---|
| Reemitir o certificado | O SAN era `IP:10.4.254.201`, endereço que a máquina não tem mais |
| Revisar o registro aberto | Abrir a porta agora alcança a internet, não a rede do IFG |
| Registro DNS (opcional) | Deixou de ser pré-requisito e virou melhoria: tira o IP literal do app |

> **A armadilha do endereço morto.** `10.4.254.201` não "mudou de valor": é um
> endereço que a máquina não tem. Qualquer cliente apontado para lá falha com
> *connection timeout* — não com erro de TLS, não com 404. O sintoma não sugere
> a causa, e o alvo aparecia em cinco lugares diferentes (SAN do certificado,
> `default_sni`, endereço do site no `Caddyfile`, `--dart-define` do app,
> exemplos de `curl` na documentação). Medido em 2026-09-21: o smoke de
> contrato contra `https://10.4.254.201:18443` dá `httpx.ConnectTimeout`,
> enquanto o mesmo smoke via `--connect-to` forçando loopback passa 21/21.

---

## Onde o plano está agora

Três dos cinco passos foram feitos em 2026-09-21; os dois que faltam são
justamente os que expõem o serviço, e por isso ficaram para depois.

| # | Passo | Estado |
|---|---|---|
| 1 | Identidade do certificado → `200.17.57.229` | **feito** — `deploy/Caddyfile` |
| 2 | Endurecer o `.env` antes de existir porta | **feito** — CORS e tetos explicitados |
| 3 | Documentação e diagrama acompanhando o endereço novo | **feito** |
| 4 | ~~Regra de `ufw` para a 18443~~ → **porta 443 liberada na borda** | **feito** — e nunca dependeu do admin da máquina |
| 5 | `bind 127.0.0.1` → `bind 0.0.0.0`, na **443** | **feito** — 2026-09-21, com Leandro presente |

**O plano acabou.** As duas linhas abaixo continuam aqui porque o *caminho*
até elas é a parte que vale guardar — sobretudo a do passo 4, que ficou duas
semanas classificado como bloqueado em terceiro sem nunca ter sido.

### 1. Identidade do certificado — feito

No `deploy/Caddyfile`, o endereço do site e o `default_sni` passaram de
`10.4.254.201` para `200.17.57.229`. O `bind` **não** mudou: segue
`127.0.0.1`.

O que torna isso barato é a decisão de 2026-09-06 de usar uma **CA interna** em
vez de um autoassinado avulso. O app confia na *raiz*, que não mudou (válida
até 2036-07-15) — então a folha é reemitida sozinha com o SAN novo e
**nenhuma build do app precisa ser refeita**. Se fosse um autoassinado avulso,
toda instalação existente teria parado de confiar no servidor. Ver `TLS.md`.

### 2. Endurecimento do `.env` — feito

Três valores rodavam no default implícito. Enquanto tudo estava em loopback
isso era inofensivo; a partir do momento em que existe uma porta alcançável,
cada um vira decisão que ninguém tomou. Explicitar não mudou comportamento
nenhum — mudou de quem é a responsabilidade pelo valor.

| Variável | Era | Ficou | Porquê |
|---|---|---|---|
| `CORS_ALLOW_ORIGINS` | ausente (default `*`) | vazio | Não há cliente web; o app Android é nativo, não manda `Origin` e não é afetado |
| `MAX_UPLOAD_MB` | ausente (default 300) | `300` | Decisão registrada em vez de omissão |
| `MAX_VOICE_SAMPLE_MB` | ausente (default 25) | `25` | idem |

> **A armadilha que isso dispara, e que foi fechada junto.**
> `tests/test_cors.py::test_default_preserva_o_comportamento_de_desenvolvimento`
> afirmava um *default* chamando `Settings()`, que lê o `.env` do servidor — ou
> seja, media o que a produção configurou, não o default do campo. Passava só
> porque `CORS_ALLOW_ORIGINS` estava **ausente** do arquivo. Ao explicitar a
> variável o teste quebraria sem que comportamento nenhum tivesse mudado. A
> saída é `Settings(_env_file=None)`, já aplicada, junto de um teste novo que
> trava o valor que a produção de fato usa.

### 3. Documentação — feito

`DEPLOY.md`, `TLS.md`, `README.md`, `ROTEIRO_TESTES_PENDENTES.md` e o diagrama
`05-deploy-topologia.svg` acompanharam o endereço novo. A frase
`10.4.254.201` entrou na lista `FRASES_MORTAS` de `tests/test_diagramas.py`:
se algum diagrama voltar a citá-la, o teste falha. Os relatórios datados
(`E2E_APP_2026-09-07.md`, `TESTE_CONJUNTO_NUMBERS.md`) **não** foram mexidos —
são registro do que era verdade naquele dia, não descrição do presente.

### 4. Firewall — o pedido que nunca teve destinatário

**O `ufw` desta máquina está desligado**, e este plano afirmou o contrário por
duas semanas. A leitura errada foi de `/etc/default/ufw`
(`DEFAULT_INPUT_POLICY="DROP"`), arquivo que diz a política que o ufw *usaria
se estivesse ligado*. O estado real está em `/etc/ufw/ufw.conf`
(`ENABLED=no`) e em `ufw status` (`inactive`) — e `systemctl is-active ufw`
responde `active` mesmo assim, porque a unidade *oneshot* rodou.

Prova sem root, do próprio servidor:

    bash -c 'cat </dev/null >/dev/tcp/200.17.57.229/<porta>'

Porta sem ouvinte: `Connection refused` **imediato**. Regra `DROP` travaria até
o timeout — o RST instantâneo prova que não há filtro local.

**Quem descartava era a borda do IFG, que é do CTI.** Medido em 2026-09-21:
ouvinte em `0.0.0.0:18444` na máquina + `curl` de uma rede externa (Linq
Telecom) = `Connection timed out`. Mas a borda filtra **por porta**, não em
bloco: há sessões SSH estabelecidas vindas da internet para a `:22`. Daí a
virada do plano — em vez de pedir a abertura da 18443, **procurar uma porta já
permitida**.

**A 443 foi liberada**, e com isso o passo 4 deixou de existir em vez de ser
cumprido: o proxy se mudou para a porta que já passava. O que restou é local e
do próprio Leandro (grupo `sudo`): um `setcap` para o Caddy abrir porta
privilegiada, mais a remoção do `NoNewPrivileges=yes` da unidade sem o qual o
`setcap` não tem efeito. Ver `TLS.md`, *Porta privilegiada sem root*.

> **A lição, que vale além deste caso.** Duas semanas de espera saíram de uma
> inferência (*o arquivo diz DROP, logo o firewall nega*) tratada como
> medição. O custo não foi o erro técnico — foi ter classificado o item como
> *bloqueado em terceiro*, o que desliga a investigação. Medir o efeito custava
> um comando.

#### Por que a regra é aberta, e não restrita por origem

Decisão de Leandro em 2026-09-21, depois de medir. A alternativa considerada
era restringir a regra à origem dos aparelhos do piloto, o que daria o mesmo
resultado prático sem publicar o serviço na internet. **Foi descartada por
medição, não por preferência**, e vale registrar o caminho para ninguém
refazer a conta:

- A saída do MacBook por IPv6 é `2804:3d90:8288:a0:ac74:5d94:bee3:7cea`. O
  identificador de interface é aleatório (não é EUI-64), ou seja é um
  **endereço temporário de privacidade** (RFC 4941), que o macOS rotaciona
  a cada ~24 h. Não serve de âncora para regra nenhuma.
- A saída por IPv4 é `177.223.36.83`, que resolve para
  `177-223-36-83.linqtelecom.com.br` — **provedor regional, não o IFG**. A
  suposição inicial (de que os aparelhos sairiam pelo NAT institucional
  `200.17.57.4`) estava errada.
- E a decisão de fundo: **os aparelhos do piloto estarão em qualquer lugar** —
  casa, 4G, campus. Origens múltiplas e dinâmicas não cabem numa regra de
  firewall.

Com isso, quem pode usar o serviço deixa de ser decidido pelo firewall. Ver a
seção seguinte para o que passa a segurar essa porta — e o que não segura.

#### Detalhe de pilha que vale saber antes do piloto

**O servidor é IPv4-only.** Medido em 2026-09-21: a `eno1` só tem `fe80::`
(link-local), não há rota IPv6 default e `curl -6` de dentro da máquina falha
com exit 7. O cliente típico é dual-stack e cai em IPv4 sozinho por *happy
eyeballs*, então isso **não** bloqueia nada hoje — custa no máximo alguns
milissegundos no primeiro contato.

O que guardar: um aparelho numa rede **sem IPv4** não alcançaria o backend.
Hoje é situação rara, mas é motivo para pedir IPv6 ao CTI junto do registro
DNS, se ele for mexer no endereçamento de qualquer forma.

### 5. Virar o bind — feito em 2026-09-21

Duas linhas em `deploy/Caddyfile`, não uma, porque a porta mudou junto:

    https://200.17.57.229:18443   →   https://200.17.57.229:443
    bind 127.0.0.1                →   bind 0.0.0.0

**Não houve reemissão de certificado.** Porta não entra em certificado: o SAN
continua `IP:200.17.57.229` e a raiz da CA interna não mudou, então nenhuma
build nova do app — só o `--dart-define`, que perde o `:18443`.

`0.0.0.0`, **nunca** `200.17.57.229` literal. O argumento antigo era o DHCP;
com endereço estático o bind num IP virou tecnicamente possível e continua
errado: amarra o serviço a uma decisão do admin que pode mudar sem aviso, e a
falha é *cannot assign requested address* em loop de restart, no boot, sem
ninguém olhando.

Aplicar com `systemctl --user restart scitechear-proxy`, **não `reload`**: o
`reload` é incompatível com o `admin off` do `Caddyfile` e sempre falha (ver
`TLS.md`, seção Operação). Como restart derruba conexão, escolha o momento —
não com upload de reunião em curso.

**`scitechear-api.service` não muda.** A API continua em `127.0.0.1:18080`;
quem vai para a rede é só o proxy. A regra "a API nunca escuta na rede"
permanece.

---

## A decisão que este passo publica

Este plano existia para tirar o cabo. Vale dizer em voz alta o que o passo 5
publica junto, porque não é óbvio olhando só para o `Caddyfile`:

**`AUTH_ALLOWED_EMAIL_DOMAINS` está vazia — registro aberto a qualquer
e-mail.** Foi desligada em 2026-09-08, quando a única entrada era o túnel SSH e
isso era inofensivo. A decisão foi **reafirmada duas vezes em 2026-09-21**:
primeiro ao saber do IP público, e de novo depois que a regra restrita por
origem se mostrou impraticável — ou seja, sabendo que ela era o último
amortecedor disponível. É escolha consciente, não omissão, e não precisa ser
reaberta a cada revisão.

Registrado para quem pegar isto depois: foram avaliadas duas formas de estreitar
o acesso sem mexer no produto — allowlist de e-mail e regra de firewall por
origem. A segunda caiu por medição (ver §4). A primeira foi recusada. O que
sobra é o rate limit.

O que muda com a porta aberta é só o alcance: qualquer pessoa **da internet**
cria conta e enfileira áudio na GPU. O amortecedor que resta é o rate limit de
registro (`AUTH_REGISTER_MAX_ATTEMPTS=10` por hora, por IP), e ele foi
dimensionado para um universo pequeno de clientes institucionais — na internet
um IP deixa de identificar alguém.

Para religar, se a decisão mudar: a comparação é **exata, não por sufixo**
(`auth_service.py:141`), então os três domínios precisam estar listados.

    AUTH_ALLOWED_EMAIL_DOMAINS=ifg.edu.br,academico.ifg.edu.br,estudantes.ifg.edu.br

Para conferir qual estado está no ar sem efeito colateral: `POST /auth/register`
com `e2e-teste@example.com` — domínio não institucional **e** já cadastrado. Dá
`403` com allowlist ligada e `409` com ela desligada, e não cria conta em
nenhum dos dois casos. Custa uma das 10 vagas do balde daquele IP.

### O teto que não é de segurança

O worker é **um processo, serial** (`while True` em `app/worker.py`), preso em
`CUDA_VISIBLE_DEVICES=0` — quando isto foi escrito, justamente a GPU ~15% mais
lenta das duas, com a GPU1 ociosa. Uma reunião de 10 min leva ~3,6 min; uma
turma enviando junto enfileira.

> **A conta mudou em 19/09/2026, e não para melhor.** Não há mais "GPU1
> ociosa": a **GPU0 caiu do barramento** (Xid 79, falha física) e a máquina
> opera com **uma placa só**, dividida com o Ollama e com os outros projetos.
> O `CUDA_VISIBLE_DEVICES=0` hoje aponta para a placa sobrevivente, porque o
> CUDA não enumera a morta — o pin acerta por coincidência. Ver `PENDENCIAS.md`
> e `DEPLOY.md`. Abrir o cadastro para a internet não muda o risco de invasão tanto
quanto muda o risco de **fila**: é o teto real de capacidade do piloto.

---

## Lado do app (repositório SciTech-frontend)

O procedimento completo está em `TLS.md`; o essencial, com o endereço novo:

1. Apontar via `--dart-define`:
   `SCITECH_API_BASE_URL=https://200.17.57.229` e
   `SCITECH_WS_BASE_URL=wss://200.17.57.229`.
   **Sem porta**: o backend está na 443, que é o default de `https`/`wss`. Se
   algum artefato do app ainda disser `:18443`, está apontando para uma porta
   que não escuta mais — e o sintoma é *connection refused*, não erro de TLS.
2. **Carregar a raiz da CA no `SecurityContext`** — o passo que a maioria das
   tentativas erra. `network_security_config.xml` é aplicado pelo *framework*
   do Android, mas o `dart:io HttpClient` (e o `WebSocket` por trás dele) usa
   BoringSSL e não passa por ali. Usar **o mesmo `HttpClient` no WebSocket**
   (`IOWebSocketChannel.connect(uri, customClient: httpClient)`), senão o
   `wss://` falha sozinho enquanto o REST funciona — sintoma que confunde.
3. Copiar `deploy/scitechear-root-ca.crt` para o app (assets + `res/raw`). **O
   arquivo não mudou** com a troca de endereço: a raiz é a mesma. Se o app já
   embute a versão de 2026-09-06, está correto.
4. Atualizar o `<domain>` do `network_security_config.xml` para
   `200.17.57.229`, e mantê-lo: cobre WebView e impede o app de aceitar HTTP
   puro por engano.

APK release é desejável para o piloto, mas **não** é pré-requisito para cortar
o cabo: a build de desenvolvimento roda sozinha depois de instalada, e o
vínculo com o MacBook é de **rede**, não de bundle.

---

## Verificação, em ordem

Parar no primeiro que falhar.

Antes de reiniciar o proxy:

1. `getcap ~/.local/bin/caddy` responde `cap_net_bind_service=ep`, e a unidade
   **não** tem mais `NoNewPrivileges=yes`. Faltando qualquer um dos dois, o
   bind na 443 falha com `permission denied`.
2. `caddy validate --config deploy/Caddyfile` diz `Valid configuration`.
3. Certificado com o SAN certo (porta não aparece nele — é para conferir o IP):
   `openssl x509 -in /data/projects/leandro/scitechear/caddy/certificates/local/200.17.57.229/200.17.57.229.crt -noout -ext subjectAltName`

Depois do restart:

4. `ss -ltn` mostra `0.0.0.0:443` e **`127.0.0.1:18080`**. Se aparecer
   `0.0.0.0:18080`, parar tudo — a API não pode estar na rede.
5. Health pelo IP público, da própria máquina:
   `curl --cacert deploy/scitechear-root-ca.crt https://200.17.57.229/health`
6. **De outra máquina, e numa rede que não seja a do IFG** — é o único teste
   que exercita a borda, e é o que estava bloqueado até hoje:
   `curl --cacert deploy/scitechear-root-ca.crt https://200.17.57.229/health`
7. `SSL_CERT_FILE=$PWD/deploy/scitechear-root-ca.crt .venv/bin/python -m
   scripts.smoke_contrato https://200.17.57.229` — o script não recebe CA por
   argumento; sem a variável ele falha em `CERTIFICATE_VERIFY_FAILED`, que
   parece problema de certificado e é só o bundle default do `httpx`.
   Referência **através do proxy**: **20 OK, 1 falha**, e a falha parecia
   conhecida (o `4401` do WS não atravessando o TLS).

   > **Corrigido em 21/09/2026, depois que isto foi escrito.** Aquela causa
   > era **falsa**: o `4401` sempre atravessou o proxy. Quem pendurava era o
   > cliente `websockets.sync` usado pelo próprio smoke — dois clientes
   > independentes recebem o fechamento pelo mesmo proxy sem falhar. Com o
   > smoke corrigido para o cliente assíncrono, a referência através do proxy
   > é **21 OK, 0 falhas**, igual à direta. Ver `PENDENCIAS.md`.
8. **Upload grande através do proxy** — pendência aberta em `TLS.md`, nunca
   testada. Um WAV perto do teto de 300 MB.
9. Do tablet **sem cabo**: login, upload, WebSocket até `done`, resultado.
10. Sem vazamento: após uma conexão WS real, nem
    `journalctl --user -u scitechear-proxy` nem `-u scitechear-api` podem
    conter JWT. Os dois filtros de redação são independentes e ambos
    necessários.

---

## De quem depende cada coisa

| Bloqueio | Quem resolve | O que trava |
|---|---|---|
| ~~Regra de `ufw` na 18443~~ | ~~Admin do NumbERS~~ | **não existia** — o ufw está desligado |
| Porta permitida na borda | CTI do IFG | **resolvido**: a 443 foi liberada |
| `setcap` para a porta privilegiada | **Leandro** (grupo `sudo`) | **feito** — não passa pelo admin |
| Confirmar o registro aberto na internet | **Leandro** | nada — confirmado em 2026-09-21 |
| Registro DNS público | CTI do IFG | nada; é melhoria, não bloqueio |
| `--dart-define` e `network_security_config` | Leandro (outro repositório) | **o app conectar** — é o que sobrou |

O lado do servidor precisou de **um** `sudo`, uma vez, e ele é do próprio
Leandro: a capability do Caddy. Fora isso tudo segue no checkout e em unidades
de usuário, no mesmo padrão do resto do projeto — nenhum serviço de sistema,
nenhum pacote via `apt`, nada rodando como root.

## Melhoria que deixou de ser bloqueio: nome DNS

Com IP público, um registro como `scitechear.ifg.edu.br` não é mais
pré-requisito de nada — vira conforto, e um conforto real: tira o IP literal do
`--dart-define`, do `network_security_config` e do `Caddyfile`, e abre a porta
para certificado **público** via ACME, dispensando a raiz embutida no app.
O `default_sni` também sairia sozinho, já que ele só existe porque cliente que
fala com um IP não manda SNI (RFC 6066).

Basta a 443 para o ACME: o Caddy resolve o desafio **TLS-ALPN-01** na própria
443, sem precisar da 80. **E desde 2026-09-21 é exatamente nela que o proxy
escuta** — ou seja, o pré-requisito de porta para um certificado público já
está satisfeito; falta só o nome.

**Por que não fazer isso com o IP puro, já que ele é público.** A Let's Encrypt
passou a emitir certificado para IP nu, mas só no perfil `shortlived`
(validade de ~6 dias), e o Caddy **ainda não suporta esse perfil nativamente** —
a alternativa hoje é contornar com `acme.sh` e alimentar o certificado ao Caddy.
Não vale a complexidade para o piloto: a CA interna já resolve, e o caminho
limpo é o nome DNS. Reavaliar quando o Caddy ganhar suporte.
