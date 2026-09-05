# Deploy — SciTech Ear · Backend

Como o backend está implantado hoje, e por quê. Até aqui isso não estava em
lugar nenhum do repositório: quem pegasse o projeto do zero não teria como
saber onde ele roda, em que porta, ou o que quebra ao mexer.

O ambiente de referência é o servidor **NumbERS** do IFG. Nada aqui é
específico dele a ponto de não servir para outro servidor Linux com GPU — mas
as decisões abaixo foram tomadas para uma **máquina compartilhada**, e é isso
que explica quase todas elas.

## O ambiente

| | |
|---|---|
| Máquina | `numbersia` — Ubuntu 24.04, RTX 5090 (32 GB), acessível só pela VPN do IFG |
| Compartilhada com | outros pesquisadores (há um ComfyUI de terceiro na mesma GPU) |
| Fila de GPU | **não existe** — sem Slurm, sem árbitro; a convivência é por disciplina |
| Python | 3.12 do sistema (daí o `.python-version` fixado) |
| Torch | 2.8.0+cu128 — o índice cu130 não tem torch 2.8, e o WhisperX pina `torch~=2.8.0`; o driver 590/CUDA 13.1 roda binários cu128 sem ajuste (sm_120 confirmado) |

## Layout no disco

    /data/projects/leandro/
      leandroalexandre-ifg-scitechear-backend/   # o checkout git + .venv/
      scitechear/
        storage/     # STORAGE_ROOT: áudios, resultados, jobs.db, perfis de voz
        hf-cache/    # HF_HOME (~4 GB)
        ollama/      # OLLAMA_MODELS (~9 GB) — blobs dos modelos

**Os dados ficam deliberadamente FORA do checkout.** Um `git clean`, um
`git checkout` agressivo ou um re-clone não podem alcançar dado de usuário —
áudio de reunião, perfil de voz e banco não são recuperáveis a partir do
repositório. `STORAGE_ROOT` no `.env` aponta para lá com caminho absoluto.

A convenção `/data/projects/<usuario>/` é do servidor, criada pelo admin.

## Os três serviços

Tudo roda como **unidade systemd de usuário** (`~/.config/systemd/user/`), não
de sistema. Em máquina compartilhada isso é o que evita ter que coordenar com
quem administra o servidor a cada mudança de configuração.

| Unidade | O que é | Porta |
|---|---|---|
| `scitechear-api` | FastAPI/uvicorn | `0.0.0.0:18080` (ver abaixo) |
| `scitechear-worker` | consumidor da fila de jobs (usa a GPU) | — |
| `ollama` | servidor do LLM (`qwen3:14b`) | `127.0.0.1:11434` |

    systemctl --user status scitechear-api scitechear-worker ollama
    systemctl --user restart scitechear-api
    journalctl --user -u scitechear-worker -f

**Depende de `linger`**: sem `loginctl enable-linger leandro`, as unidades de
usuário morrem quando a sessão SSH termina. Já está habilitado — mas é a
primeira coisa a checar se os serviços "somem" depois de um logout.

**A API responde na rede desde o piloto** (2026-09-05); o Ollama continua em
loopback. A porta `18080` (e não `8000`) é para não colidir com o default que
qualquer outro projeto Python da máquina escolheria.

O bind é `0.0.0.0` e **não** o IP específico, de propósito: o endereço da
`eno1` vem por DHCP (`10.4.254.201` via `10.4.0.1`), e fixar um IP que pode
mudar faria o uvicorn falhar com *cannot assign requested address* e entrar em
loop de restart — a API simplesmente não subiria, no pior momento possível. As
demais interfaces (`docker0`, bridges, `wlp101s0`, `enp103s0`) estão DOWN, então
na prática isso é `eno1` + loopback. **Quem pode chegar à porta é
responsabilidade do firewall**, que é a camada certa para isso; restringir pelo
bind seria frágil e daria uma falsa sensação de controle.

Para reverter ao loopback, há cópias datadas da unidade em
`/data/projects/leandro/scitechear/scitechear-api.service.bak-*`.

O Ollama foi instalado **sem privilégio de root**, em `~/.local/bin`, mesmo com
o usuário estando no grupo `sudo`: o único ganho do root seria compartilhar o
servidor e os 9 GB do modelo com outros pesquisadores, e ninguém mais pediu
LLM.

## Como o app alcança o backend

A API está em loopback, então **um tablet ou celular não a alcança
diretamente** — é preciso escolher um caminho. Esta decisão ainda está em
aberto.

### Recomendado: túnel SSH sobre a VPN

Nenhum privilégio novo, nada exposto, nada a pedir ao admin. Na máquina de
desenvolvimento, já conectada à VPN:

    ssh -N -L 18080:127.0.0.1:18080 leandro@numbersia

O backend passa a responder em `localhost:18080` na máquina de
desenvolvimento. Com o aparelho Android ligado por USB, o app chega lá com o
mesmo `adb reverse` que o README já descreve:

    adb reverse tcp:18080 tcp:18080

E o app aponta para `http://127.0.0.1:18080` via `--dart-define`
(`SCITECH_API_BASE_URL`, `SCITECH_WS_BASE_URL` — ver Fase 7 do plano).

### Aparelhos na rede do IFG (VPN ou laboratório) — **exige o admin**

Cenário do piloto: o professor testando pela VPN com um tablet, e depois os
alunos usando os próprios aparelhos direto do laboratório, sem VPN.

A máquina tem IP **`10.4.254.201/16`** na interface `eno1` — a rede do IFG.
Hoje só o SSH escuta fora do loopback, então **nem pela VPN a API é
alcançável**: o tablet chega à rede 10.4.x.x, mas a API só atende em
`127.0.0.1`. Vale para os dois cenários — o do professor e o dos alunos é a
mesma mudança, o que é bom: dá para testar na topologia real antes.

O que precisa acontecer:

1. ~~**Bind na interface da rede.**~~ **Feito** (2026-09-05): `0.0.0.0:18080`,
   pelo motivo explicado acima. Verificado respondendo tanto em `127.0.0.1`
   quanto em `10.4.254.201`.
2. **Liberar a porta no firewall** — *este item exige quem administra o
   servidor*, e é o único ainda pendente. Idealmente restrito à faixa do
   laboratório, não à `10.4.0.0/16` inteira. **Enquanto não se sabe o estado do
   firewall, considere a API alcançável por qualquer máquina da instituição** —
   é o que torna os dois tetos abaixo obrigatórios, e não recomendações.
3. ~~**Fechar as portas de entrada abertas.**~~ **Feito** (ver abaixo): teto de
   upload e allowlist de e-mail no registro, esta última já ativa em produção
   com `ifg.edu.br` e confirmada recusando domínio de fora com `403`.
4. **Decidir sobre TLS.** O tráfego é HTTP puro; na rede institucional isso
   significa senha e áudio de reunião em claro para quem estiver na mesma
   rede. Um certificado próprio exige configuração no app Android
   (`network_security_config` ou CA instalada), então é trabalho da Fase 7 —
   não dá para resolver só do lado do servidor.

**`10.4.0.0/16` é a instituição inteira, não só o laboratório.** É a razão de
os dois itens abaixo existirem: enquanto a API respondia só em loopback, quem
chegava à porta já estava dentro da máquina, e nenhum dos dois fazia falta.

#### Teto de upload

`MAX_UPLOAD_MB` (default 300, cobre ~2h de WAV 16 kHz mono) e
`MAX_VOICE_SAMPLE_MB` (default 25). O teto do áudio é aplicado **durante** a
gravação, em pedaços de 1 MB: sem isso, quem envia é que decide quanta RAM e
quanto disco o servidor gasta. Upload recusado não deixa arquivo parcial nem
job órfão na fila — o job só é criado depois da gravação terminar.

#### Allowlist de e-mail no registro

`AUTH_ALLOWED_EMAIL_DOMAINS` (vazio = registro aberto, o default de
desenvolvimento). Preenchida com os domínios institucionais
(`ifg.edu.br,academico.ifg.edu.br`), só quem tem vínculo cria conta — sem
precisar inventar um fluxo de convite. E-mail recusado conta como tentativa
falha no rate limit, para não virar um varredor de domínios.

### Expor à internet

Fora do escopo do piloto, e bem mais caro que a rede interna: IP público ou
DNS, TLS obrigatório, e revisão do rate limiting (que hoje protege `/auth`
assumindo um universo pequeno de clientes). Não faça sem TLS.

## CORS

`CORS_ALLOW_ORIGINS` (`.env`) aceita uma lista separada por vírgula. O default
é `*`, que preserva o comportamento de desenvolvimento.

**O app Android é cliente nativo: não manda `Origin` e não é afetado por
CORS.** Ou seja, restringir as origens não quebra o app — só reduz a superfície
para clientes de navegador. Se nenhum cliente web precisar do backend, o valor
correto em produção é uma lista explícita (ou nenhuma origem).

`allow_credentials` acompanha a origem automaticamente: com `*` ele é
desligado, porque `Access-Control-Allow-Origin: *` junto de
`Allow-Credentials: true` é a combinação que a especificação de CORS proíbe — e
que o Starlette contorna ecoando a origem de quem pediu, liberando credenciais
para qualquer site. Nada no projeto depende disso: a autenticação é
`Authorization: Bearer`, não cookie.

## Atualizar o que está rodando

    git pull                       # ou checkout da branch desejada
    systemctl --user restart scitechear-api scitechear-worker

**O checkout É a produção.** Não há build nem cópia: as unidades apontam para o
diretório do repositório e para o `.venv/` de dentro dele. A branch que estiver
com checkout é o código que sobe no próximo restart — inclusive num restart
automático por reboot ou falha, não só num manual. Confira antes:

    git branch --show-current

Voltar para outra branch sem ter mesclado **remove a funcionalidade do ar** na
próxima reinicialização, silenciosamente.

## Armadilhas conhecidas

**`EnvironmentFile=` é lido no START do serviço.** Editar o `.env` não alcança
processos que já estão rodando. Em 2026-09-04 isso produziu um diagnóstico
falso: a API subiu antes da edição e ficou com `HF_TOKEN` vazio enquanto o
worker tinha o token, e `/ready` reportava `hf_token_configurado: false` sem
haver problema nenhum de token. **Depois de mexer no `.env`, reinicie as três
unidades** — o `ollama.service` também lê o mesmo arquivo (vale por
`OLLAMA_KEEP_ALIVE`).

**Cuidado com `pkill -f "python -m app.worker"`.** O padrão casa com a própria
linha de comando do shell que o executa e mata o comando antes da linha
seguinte. Use `pgrep -af "app[.]worker"` e mate por PID.

**GPU compartilhada.** O `qwen3:14b` ocupa **14 GB de VRAM** com o contexto
default de 32k — não os ~10 GB que uma estimativa antiga sugeria.
`OLLAMA_MAX_LOADED_MODELS=1` e `OLLAMA_KEEP_ALIVE=5m` limitam a janela em que
essa VRAM fica presa. Antes de rodar algo pesado, vale um `nvidia-smi` para ver
o que os outros projetos estão usando.

**Instalação do Ollama:** o redirect de
`ollama.com/download/ollama-linux-amd64.tgz` está quebrado (404) — o asset
virou `.tar.zst`. Baixe do release do GitHub, descobrindo o nome real do asset
via `api.github.com/repos/ollama/ollama/releases/latest`.

## Verificação de saúde

    curl -s http://127.0.0.1:18080/health   # não carrega modelo nenhum
    curl -s http://127.0.0.1:18080/ready    # checa HF_TOKEN, Ollama e GPU

`/ready` respondendo `{"ready": true, ...}` significa que as dependências
externas estão de pé — os modelos de ML continuam sendo carregados sob demanda,
por job.

Para uma verificação de ponta a ponta de verdade (com áudio, biometria e
perguntas), ver `docs/E2E_FASE8.md`.

## O que exige o administrador do servidor

Separado de propósito — é o que não dá para resolver sozinho:

- `loginctl enable-linger` (já feito);
- abrir qualquer porta no firewall, ou expor um serviço fora do loopback;
- instalar pacote via `apt`, ou qualquer coisa que precise de root;
- entrar em grupos (ex.: `docker`);
- criar diretórios fora de `/data/projects/<usuario>/`.
