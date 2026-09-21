# TLS — plano e procedimento

Este documento resolve o **item 2** dos pré-requisitos do piloto listados em
[`DEPLOY.md`](DEPLOY.md): *"decidir sobre TLS"*. Ele descreve a decisão, o que
já está pronto e verificado, o que ainda depende de quem administra o NumbERS,
e como o app Android passa a confiar no certificado.

**Estado em 2026-09-21:** o proxy está **na rede**, escutando em
`0.0.0.0:443` (`scitechear-proxy`, unidade de usuário, habilitada). A API
continua em `127.0.0.1:18080` e **nunca escutou fora do loopback** — essa parte
não mudou e não muda. Entre 2026-09-06 e 2026-09-21 o proxy também esteve em
loopback (`127.0.0.1:18443`), servindo para testar HTTPS por túnel SSH; foi a
liberação da **443 na borda do IFG** que encerrou esse estágio.

Por que 443 e não a 18443 que este documento propunha: a borda filtra **por
porta**, e a 443 era a porta já permitida. Não houve escolha de estética — a
18443 nunca passaria. O preço é que 443 é privilegiada; ver
[Porta privilegiada sem root](#porta-privilegiada-sem-root).

## O problema

O piloto exige que o app alcance o backend pela rede — hoje o único caminho é
o túnel SSH, que não serve para um tablet de professor nem para o laboratório.
Mas expor a API como ela está significa senha de usuário e áudio de reunião em
**HTTP puro** para quem chegar à porta. Foi exatamente por isso que o bind na
rede feito em 2026-09-05 foi revertido no mesmo dia.

> **Atualizado em 2026-09-21.** Quando este documento foi escrito, "quem chegar
> à porta" era a `10.4.0.0/16` — a instituição inteira. A máquina passou a ter
> IP **público** (`200.17.57.229`), e agora é a internet. O argumento do
> documento não mudou; o que ele protege ficou maior.

TLS é o que desfaz esse impasse: sem ele, nenhuma outra proteção adianta —
teto de upload e allowlist de domínio reduzem superfície, mas não cifram nada.

## A decisão

**Um proxy reverso (Caddy) termina o TLS e repassa em loopback para a API.**

    app Android ──TLS──> Caddy (rede, porta a definir) ──HTTP──> API (127.0.0.1:18080)

Três escolhas embutidas nisso, e o porquê de cada uma:

**Por que um proxy, e não TLS no próprio uvicorn.** O uvicorn aceita
`--ssl-certfile`, então tecnicamente daria. Mas isso põe o processo que carrega
o modelo e fala com a GPU também no papel de terminador TLS na rede — e faz a
renovação do certificado virar restart da API. Com o proxy na frente, a regra
"a API nunca escuta na rede" continua valendo literalmente, e ela permanece o
componente mais simples possível.

**Por que Caddy, e não nginx.** Binário único, sem `apt`, sem root, sem
dependências — o mesmo padrão do Ollama, que já vive em `~/.local/bin` nesta
máquina compartilhada. E gerencia a própria CA interna, incluindo renovação
automática, o que elimina a manutenção manual de certificado.

**Por que uma CA interna, e não um certificado autoassinado avulso.** Esta é a
escolha menos óbvia, e a que mais importa para a Fase 7. Um autoassinado avulso
é emitido para um endereço específico. Toda vez que o IP mudasse, seria preciso
emitir outro certificado **e** redistribuir o app, porque o que o app confia é
o próprio certificado. Com uma CA interna, o app confia na **raiz** — que vale
até 2036 — e o certificado do servidor é reemitido sozinho, inclusive quando o
IP mudar.

> Esta decisão **se pagou em 2026-09-21**, e mais rápido do que o previsto. O
> argumento original era a lease de DHCP (~73 min em 2026-09-06); o que de fato
> aconteceu foi o admin trocar a máquina inteira de faixa, de `10.4.254.201`
> privada para `200.17.57.229` pública. Mudança bem maior do que uma renovação
> de lease — e ainda assim custou só um `restart` do proxy, sem reemitir
> certificado na mão e **sem nova build do app**, porque a raiz não muda junto.
> Se fosse um autoassinado avulso, toda instalação existente teria parado. A
> mudança de porta no mesmo dia (18443 → 443) saiu ainda mais barata: porta não
> faz parte da identidade do certificado, então nem reemissão houve. O certificado ainda é "autoassinado" no sentido que importa
(não há CA pública envolvida, nenhuma CA da IFG foi confirmada), mas a parte
que o app carrega para de ser um alvo móvel.

## O que já está pronto e verificado

Tudo abaixo foi medido no NumbERS em 2026-09-06, com o proxy escutando em
`127.0.0.1:18443` e a API de produção como upstream real.

| O quê | Resultado |
|---|---|
| Caddy 2.11.4 em `~/.local/bin/caddy` | instalado; SHA-512 conferido contra o `checksums.txt` do release |
| CA interna gerada | raiz `Caddy Local Authority - 2026 ECC Root`, válida até **2036-07-15** |
| Certificado do servidor | folha de 12h renovada sozinha. SAN era `IP:10.4.254.201`; **desde 2026-09-21 é `IP:200.17.57.229`** — a raiz é a mesma, então o app não precisa de rebuild |
| `GET /health` sobre TLS | `200`, HTTP/2, `ssl_verify_result=0` com a raiz como âncora |
| Cliente **sem** a raiz | recusado (`unable to get local issuer certificate`) — é o comportamento desejado |
| `POST /auth/login` + `GET /meetings` | funcionam através do proxy com token real |
| **WebSocket** `/ws/{job_id}` sobre `wss` | handshake OK e frame de progresso real recebido |
| Rate limiting por IP | preservado (ver abaixo) |
| JWT no log de acesso | redigido no proxy — e o mesmo vazamento pela API foi corrigido à parte (ver abaixo) |

Duas armadilhas encontradas no caminho, ambas já resolvidas no
[`../deploy/Caddyfile`](../deploy/Caddyfile) — e as duas falhavam de um jeito
que não parece ter a ver com a causa:

**`default_sni` é obrigatório quando o cliente fala com um endereço IP.** A
RFC 6066 proíbe mandar SNI quando o destino é um endereço, então o Caddy não
consegue casar o site pelo nome e o handshake morre com
`tlsv1 alert internal error` — antes de qualquer resposta HTTP, e sem nada
útil no log. Parece problema de certificado; não é.

**O token do WebSocket vazava para o log — e por dois caminhos, não um.** O
handshake de WS não aceita header `Authorization` em todo cliente, então
`/ws/{job_id}` autentica por query string; qualquer coisa que registre a URI
inteira grava um JWT válido junto.

No **proxy**, o `Authorization` já é redigido por padrão pelo Caddy, mas a query
string não. O filtro do `log` neste `Caddyfile` resolve — e o caminho do campo é
`request>uri`, não `uri`; com o caminho errado o filtro é aceito sem erro e
simplesmente não faz nada. Verificado depois da correção: `?token=REDACTED`.

Na **API**, o mesmo vazamento existia por um caminho que não passa pelo proxy: o
uvicorn registra o caminho com a query, e foi por aí que quatro JWTs reais
chegaram ao journald do servidor — o primeiro no E2E de 2026-09-05, quando não
havia Caddy nenhum. Corrigido em `app/main.py` por um filtro de logging preso a
`uvicorn.error` (que é quem emite a linha do WebSocket — **não**
`uvicorn.access`, e prender no logger óbvio instala, passa nos testes e não
protege nada). `JWT_SECRET_KEY` foi rotacionado. Ver o commit `1febf10`.

**Os dois filtros são necessários e não se substituem:** o do Caddy protege o
log do proxy, o da API protege o dela. Desligar qualquer um traz o vazamento de
volta pela metade que sobrou. Se algum dia o proxy sair da frente, o da API
continua sendo o que importa.

### Rate limiting: o que um proxy costuma quebrar em silêncio

`_client_ip` em `app/api/auth.py` usa `request.client.host` para limitar
tentativas de login por IP. Com um proxy na frente, o risco clássico é todo
cliente virar `127.0.0.1` e os limites colapsarem num balde só — o comentário
naquela função já antecipava essa revisão.

Medido: **não é preciso mudar nada.** As duas pontas já fazem a coisa certa.
O Caddy, desde a 2.7, começa com a lista `trusted_proxies` vazia, então um
`X-Forwarded-For` mandado pelo cliente é **descartado**, não anexado (testado
forjando `X-Forwarded-For: 10.4.1.99`: o upstream recebeu só o endereço real).
E o uvicorn 0.39 confia em `127.0.0.1` por default e reescreve
`request.client` a partir do cabeçalho (testado com um cliente vindo de
`127.0.0.2`: a aplicação viu `127.0.0.2`, não `127.0.0.1`).

## O firewall: duas semanas de espera por uma autorização inexistente

Esta seção se chamava *"O que depende do administrador do NumbERS"* e pedia
uma regra de firewall para a porta 18443. **O pedido nunca teve destinatário.**
Vale registrar o erro inteiro, porque ele é barato de repetir.

O que se afirmava: *"o `ufw` está ativo com `DEFAULT_INPUT_POLICY=DROP`"*. A
leitura era de `/etc/default/ufw`, que diz a política que o ufw **usaria se
estivesse ligado** — não se ele está. O estado real:

| Onde olhar | O que diz |
|---|---|
| `/etc/default/ufw` | `DEFAULT_INPUT_POLICY="DROP"` — a política *hipotética* |
| `/etc/ufw/ufw.conf` | **`ENABLED=no`** — o ufw não roda |
| `sudo ufw status` | `inactive` — a resposta que manda |
| `systemctl is-active ufw` | `active` — **e mente**: a unidade *oneshot* rodou |

Prova sem root, do próprio servidor, de que a máquina não filtra:

    bash -c 'cat </dev/null >/dev/tcp/200.17.57.229/<porta>'

Porta sem ouvinte deu `Connection refused` **imediato**. Regra `DROP` travaria
até o timeout; RST instantâneo prova que não há filtro local.

**Quem descartava era a borda do IFG**, que é do CTI. Medido em 2026-09-21:
ouvinte em `0.0.0.0:18444` aqui + `curl` de uma rede externa = `Connection
timed out`. Mas a borda filtra **por porta** — há sessões SSH vindas da
internet para a `:22`. Foi essa observação que mudou o plano: em vez de pedir a
18443, achar uma porta já permitida. A **443** foi liberada, e o proxy se mudou
para ela.

Sobra desta seção, e é pouco: **a borda continua sendo de outro dono.** Abrir
uma porta que o CTI não libere segue fora do nosso alcance. Do lado de cá, nada
depende do admin da máquina.

### Porta privilegiada sem root

443 é porta privilegiada (<1024) e o proxy é unidade de **usuário**. Duas
coisas destravam isso, e são inseparáveis:

    sudo setcap cap_net_bind_service=+ep ~/.local/bin/caddy
    # + remover NoNewPrivileges=yes de scitechear-proxy.service

**O `setcap` sozinho não faz nada.** Com `NoNewPrivileges=yes` o kernel ignora
capability de arquivo; o bind falha com `permission denied` e o erro não
aponta para a unidade. É a combinação que custa a diagnosticar, por isso está
escrita nos dois arquivos e aqui.

A alternativa era `sysctl net.ipv4.ip_unprivileged_port_start=443`, que
dispensaria capability — e foi **descartada por alcance**: é política da
máquina inteira, liberaria 443–1023 para todos os usuários de um servidor
compartilhado. O `setcap` alcança um binário só, que só o leandro escreve.

> **A capability mora no inode do binário.** `caddy upgrade`, ou baixar o
> `.tar.zst` por cima, **apaga** — e o serviço entra em loop de restart no
> próximo boot, sem ninguém olhando. Depois de qualquer atualização do Caddy:
> `getcap ~/.local/bin/caddy` e, se vier vazio, repetir o `setcap`.

O `sudo` é do próprio Leandro (grupo `sudo`, uid 1003). Continua não sendo
preciso: `apt`, serviço de sistema, entrar em grupo, nem tocar no truststore.

## Como colocar no ar — feito em 2026-09-21, na ordem em que foi feito

    # 1. instalar a unidade (uma vez) — a unidade ja esta instalada e
    #    habilitada desde 2026-09-06; fica aqui para quem remontar a maquina
    cp deploy/scitechear-proxy.service ~/.config/systemd/user/
    systemctl --user daemon-reload

    # 2. a porta privilegiada, ANTES de qualquer outra coisa. Sozinho o
    #    setcap nao faz efeito: a unidade tinha NoNewPrivileges=yes, que faz
    #    o kernel ignorar capability de arquivo. Os dois, ou nenhum.
    sudo setcap cap_net_bind_service=+ep ~/.local/bin/caddy
    getcap ~/.local/bin/caddy   # tem que responder cap_net_bind_service=ep

    # 3. no deploy/Caddyfile: porta 443 no endereco do site e `bind 0.0.0.0`
    #    (0.0.0.0, NUNCA 200.17.57.229 — ver "Bind" abaixo)
    caddy validate --config deploy/Caddyfile

    # 4. aplicar. RESTART, nao reload: o `reload` e incompativel com o
    #    `admin off` e falha sempre, DEIXANDO O SERVICO NO AR COM A
    #    CONFIGURACAO ANTIGA. Restart derruba conexao — nao faca isso com
    #    upload de reuniao em curso.
    systemctl --user restart scitechear-proxy
    systemctl --user status scitechear-proxy

    # 5. conferir que quem escuta na rede e o proxy, e so ele
    ss -ltn | grep -E '18080|:443'
    #   esperado: 127.0.0.1:18080 (API)  e  0.0.0.0:443 (proxy)
    #   se aparecer 0.0.0.0:18080, PARE TUDO: a API nao pode estar na rede

    # 6. de fora da maquina, por uma rede que nao seja a do IFG
    curl --cacert deploy/scitechear-root-ca.crt https://200.17.57.229/health

Para voltar atrás: `bind 127.0.0.1` e porta `18443` no `Caddyfile`, mais um
`restart`, devolvem o loopback — a capability no binário pode ficar, ela não
abre nada sozinha. `systemctl --user disable --now scitechear-proxy` desliga o
proxy por inteiro. A API não é tocada em nenhum dos caminhos.

## Android: fazer o app confiar na CA

A raiz está versionada em
[`../deploy/scitechear-root-ca.crt`](../deploy/scitechear-root-ca.crt) (é um
certificado público, não um segredo) e copiada em
`/data/projects/leandro/scitechear/tls/root.crt`.

    SHA-256: E8:04:01:1F:E2:B4:D0:C9:34:6C:0B:7C:C7:91:B4:3B:
             3D:B8:77:4A:15:D5:2C:9D:47:4A:A3:A7:3D:4A:23:98

**Isto é trabalho da Fase 7 e ainda não foi verificado em app real** — o repo
do Flutter não está nesta máquina. O que segue é o plano, com a ressalva de
onde ele costuma dar errado.

### O detalhe que derruba a maioria das tentativas

`network_security_config.xml` é aplicado pelo *framework* do Android. O
`dart:io HttpClient` — que é o que um app Flutter usa por padrão, e o que está
por trás do `WebSocket` — **não passa pelo framework**: ele usa BoringSSL com o
próprio conjunto de âncoras. Ou seja, declarar a CA no
`network_security_config.xml` sozinho tende a **não** bastar, e instalar o
certificado à mão no aparelho (Ajustes → Segurança → Instalar certificado)
tende a não bastar também. Confiar só nisso é o erro clássico aqui.

O caminho que vale para Flutter é carregar a raiz no `SecurityContext`:

```dart
final ca = await rootBundle.load('assets/certs/scitechear_root_ca.crt');
final context = SecurityContext(withTrustedRoots: true)
  ..setTrustedCertificatesBytes(ca.buffer.asUint8List());

final httpClient = HttpClient(context: context);   // REST
// e o MESMO client no WebSocket, senão o wss:// falha sozinho:
// IOWebSocketChannel.connect(uri, customClient: httpClient)
```

O `withTrustedRoots: true` mantém as CAs públicas válidas, então nada mais no
app quebra.

Ainda assim vale declarar o `network_security_config.xml`, porque ele cobre
WebView e qualquer cliente HTTP nativo, e porque é ele que impede o app de
aceitar HTTP puro por engano:

```xml
<network-security-config>
    <domain-config cleartextTrafficPermitted="false">
        <domain includeSubdomains="false">200.17.57.229</domain>
        <trust-anchors>
            <certificates src="@raw/scitechear_root_ca"/>
            <certificates src="system"/>
        </trust-anchors>
    </domain-config>
</network-security-config>
```

O arquivo vai em `android/app/src/main/res/raw/scitechear_root_ca.crt` (nomes
em `res/raw` só aceitam minúsculas, dígitos e `_`; a referência
`@raw/scitechear_root_ca` é sem extensão), e o
`AndroidManifest.xml` ganha
`android:networkSecurityConfig="@xml/network_security_config"` no
`<application>`.

Se o `<domain>` for o IP, ele precisa ser trocado toda vez que o endereço
mudar — como aconteceu em 2026-09-21. É o argumento a favor de um registro
DNS: com nome, esta linha para de ser um alvo móvel.

## Operação

**Renovação: nenhuma.** A folha vale 12h e o Caddy a renova sozinho enquanto o
serviço roda; se ficar parado além disso, emite outra ao subir. A raiz vale até
**2036-07-15** — só ela é que o app carrega, e ela não muda nesse intervalo.

**A chave da CA é o ativo caro.** Fica em
`/data/projects/leandro/scitechear/caddy/pki/authorities/local/root.key`
(`0600`, diretório `0700`), **fora do checkout** — pelo mesmo motivo de
`storage/` e `hf-cache`: um `git clean` ou re-clone não pode levá-la embora. Se
ela sumir, todo app já instalado deixa de confiar no servidor e precisa de nova
build. É o item que mais merece backup nesta máquina.

**Bind.** No `Caddyfile`, o endereço do site (`https://200.17.57.229:443`)
define a **identidade do certificado** e a porta; quem decide em qual interface
escutar é o `bind`. Porta não entra em certificado — sair da 18443 para a 443
não reemitiu nada.
Use `bind 0.0.0.0`, nunca o IP. O argumento era o DHCP; desde 2026-09-21 o
endereço é estático, e mesmo assim a conclusão é a mesma: bind num IP literal
amarra o serviço a uma decisão do admin que pode mudar sem aviso, e a falha
resultante é *cannot assign requested address* em loop de restart, no boot.

**`reload` não funciona aqui — use `restart`.** Descoberto em 2026-09-21, ao
tentar aplicar o endereço novo. A unidade define
`ExecReload=caddy reload`, e o `caddy reload` aplica a configuração **falando
com a admin API** em `127.0.0.1:2019`. Mas o `Caddyfile` tem `admin off` (posto
em 2026-09-06, de propósito: aquele endpoint reconfigura o Caddy sem
autenticação e a máquina é compartilhada). As duas coisas são mutuamente
exclusivas, então `systemctl --user reload scitechear-proxy` **sempre** falhou:

    Error: sending configuration to instance: performing request:
    Post "http://localhost:2019/load": dial tcp 127.0.0.1:2019: connect: connection refused

O serviço **continua no ar** com a configuração antiga quando isso acontece — o
`reload` falha, não derruba. É por isso que passou despercebido: quem editava o
`Caddyfile` e via "Reload failed" podia concluir que o arquivo estava errado,
quando o arquivo estava certo e apenas não foi aplicado.

Consequência prática que importa no piloto: **aplicar mudança de configuração
derruba conexão**, porque só resta o `restart`. Não edite o `Caddyfile` com um
upload de reunião em curso.

> **Se algum dia isso incomodar**, o conserto de menor privilégio é trocar
> `admin off` por uma admin API em **socket unix** (`admin unix//run/user/1003/caddy-admin.sock`),
> protegida por permissão de arquivo em vez de porta TCP — `/run/user/1003` é
> `0700` do próprio usuário. Isso devolve o `reload` sem abrir porta na
> máquina compartilhada. **Não foi feito**: é mudança de postura de segurança,
> e decisão de Leandro, não consequência da troca de endereço.

**Logs.** `journalctl --user -u scitechear-proxy -f`. A query string do WS é
redigida; o `Authorization` também. Vale reconferir isso se alguém mexer no
bloco `log`.

## O que ficou sem verificar

- **Upload grande através do proxy.** O Caddy não impõe limite de corpo por
  padrão e não tem timeout de leitura por padrão, então `MAX_UPLOAD_MB=300`
  deve passar — mas isso é raciocínio sobre os defaults, não medição. Testar um
  upload real de reunião no primeiro ensaio do piloto, junto com o `413` do teto
  voltando através do proxy.
- **O lado Flutter** (seção acima), que é Fase 7.
- ~~**As regras concretas do `ufw`**, que só o admin lê.~~ **Respondido em
  2026-09-21, e a resposta é que não existem:** o `ufw` está desligado. O que
  filtra é a borda do IFG, e dela não se lê a regra — mede-se o efeito, de
  fora, porta a porta.
- **O que mais a borda do IFG permite.** Sabe-se da `22` e da `443`; o resto
  nunca foi varrido, e varrer a borda de uma instituição não é algo a fazer
  sem falar com o CTI.
