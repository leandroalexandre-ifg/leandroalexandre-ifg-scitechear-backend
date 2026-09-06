# TLS — plano e procedimento

Este documento resolve o **item 2** dos pré-requisitos do piloto listados em
[`DEPLOY.md`](DEPLOY.md): *"decidir sobre TLS"*. Ele descreve a decisão, o que
já está pronto e verificado, o que ainda depende de quem administra o NumbERS,
e como o app Android passa a confiar no certificado.

**Estado em 2026-09-06:** o proxy está **no ar como serviço**
(`scitechear-proxy`, unidade de usuário, habilitada), escutando em
`127.0.0.1:18443`. A API continua em `127.0.0.1:18080`. **Nada foi para a
rede** — o `bind` segue em loopback, e a interface `eno1` recusa conexão na
18443. O que isso destrava hoje é o teste via túnel SSH, que não depende do
admin; o piloto continua esperando os dois itens abaixo.

## O problema

O piloto exige que o app alcance o backend pela rede — hoje o único caminho é
túnel SSH sobre a VPN, que não serve para um tablet de professor nem para o
laboratório. Mas expor a API como ela está significa senha de usuário e áudio
de reunião em **HTTP puro** dentro da `10.4.0.0/16`, que é a instituição
inteira, não o laboratório. Foi exatamente por isso que o bind na rede feito em
2026-09-05 foi revertido no mesmo dia.

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
é emitido para um endereço específico; o endereço aqui vem por **DHCP** (a lease
observada em 2026-09-06 durava ~73 minutos). Toda vez que o IP mudasse, seria
preciso emitir outro certificado **e** redistribuir o app, porque o que o app
confia é o próprio certificado. Com uma CA interna, o app confia na **raiz** —
que vale até 2036 — e o certificado do servidor é reemitido sozinho, inclusive
quando o IP mudar. O certificado ainda é "autoassinado" no sentido que importa
(não há CA pública envolvida, nenhuma CA da IFG foi confirmada), mas a parte
que o app carrega para de ser um alvo móvel.

## O que já está pronto e verificado

Tudo abaixo foi medido no NumbERS em 2026-09-06, com o proxy escutando em
`127.0.0.1:18443` e a API de produção como upstream real.

| O quê | Resultado |
|---|---|
| Caddy 2.11.4 em `~/.local/bin/caddy` | instalado; SHA-512 conferido contra o `checksums.txt` do release |
| CA interna gerada | raiz `Caddy Local Authority - 2026 ECC Root`, válida até **2036-07-15** |
| Certificado do servidor | emitido para `IP:10.4.254.201`, folha de 12h renovada sozinha |
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

## O que depende do administrador do NumbERS

Um pedido só, e ele é o **único bloqueio** que sobrou:

> Abrir no firewall a porta TCP **<PORTA>** do host `numbersia`
> (`10.4.254.201`), de preferência restrita à faixa do laboratório em vez da
> `10.4.0.0/16` inteira. É uma porta alta, não privilegiada — não precisa ser
> 443, e o serviço roda como usuário comum, sem root. O tráfego é HTTPS.
> Junto disso, uma **reserva de DHCP** para o host (ou, melhor ainda, um
> registro DNS): o endereço muda a cada renovação de lease e o app precisa de
> um alvo estável.

Contexto que mudou desde o revert de 2026-09-05, e que vale registrar: o estado
do firewall **não é mais desconhecido**. O `ufw` está ativo com
`DEFAULT_INPUT_POLICY="DROP"` (lido de `/etc/default/ufw`; as regras em si estão
em arquivos `0640 root:root`, ilegíveis sem o admin). Ou seja, a postura é
negar-por-padrão e a porta hoje está fechada mesmo que um processo escute nela
— o que é a hipótese boa. Confirmar a regra continua sendo com o admin, mas o
risco de "abrir sem saber" deixou de existir.

Sobre a porta: **18443** é a proposta, livre hoje e no mesmo padrão do 18080 da
API (porta alta, escolhida para não colidir com o default óbvio de outro
projeto). Se o admin preferir outra, muda uma linha do `Caddyfile` — a porta não
faz parte da identidade do certificado.

Não é preciso: root, `apt`, porta privilegiada, entrar em grupo, nem tocar no
truststore do sistema.

## Como colocar no ar (quando os dois itens estiverem confirmados)

    # 1. instalar a unidade (uma vez) — JÁ FEITO em 2026-09-06, a unidade
    #    está instalada e habilitada; fica aqui para quem remontar a máquina
    cp deploy/scitechear-proxy.service ~/.config/systemd/user/
    systemctl --user daemon-reload

    # 2. ajustar a porta, se o admin decidiu outra, e sair do loopback:
    #    no deploy/Caddyfile, trocar `bind 127.0.0.1` por `bind 0.0.0.0`
    #    (0.0.0.0, NUNCA 10.4.254.201 — ver "DHCP" abaixo)

    # 3. subir (ou recarregar, se já estiver no ar — reload não derruba
    #    conexão, o que importa se houver upload de reunião em curso)
    systemctl --user enable --now scitechear-proxy
    systemctl --user reload scitechear-proxy   # depois de editar o Caddyfile
    systemctl --user status scitechear-proxy

    # 4. conferir que quem escuta na rede e o proxy, e so ele
    ss -ltn | grep -E '18080|18443'
    #   esperado: 127.0.0.1:18080 (API)  e  0.0.0.0:18443 (proxy)

    # 5. do lado de fora (outra maquina na VPN)
    curl --cacert scitechear-root-ca.crt https://10.4.254.201:18443/health

Para voltar atrás: `systemctl --user disable --now scitechear-proxy` devolve o
estado exato de hoje. A API não é tocada em nenhum dos passos.

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
        <domain includeSubdomains="false">10.4.254.201</domain>
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

Se o `<domain>` for o IP, ele muda junto com o DHCP — mais um motivo para pedir
reserva ou registro DNS ao admin.

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

**DHCP.** No `Caddyfile`, o endereço do site (`https://10.4.254.201:18443`)
define a **identidade do certificado**; quem decide onde escutar é o `bind`.
Use `bind 0.0.0.0`, nunca o IP: a unidade da API já carrega esse mesmo aviso,
porque bind num endereço que a lease pode trocar quebra o serviço na renovação.

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
- **As regras concretas do `ufw`**, que só o admin lê.
