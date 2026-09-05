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
| `scitechear-api` | FastAPI/uvicorn | `127.0.0.1:18080` (ver abaixo) |
| `scitechear-worker` | consumidor da fila de jobs (usa a GPU) | — |
| `ollama` | servidor do LLM (`qwen3:14b`) | `127.0.0.1:11434` |

    systemctl --user status scitechear-api scitechear-worker ollama
    systemctl --user restart scitechear-api
    journalctl --user -u scitechear-worker -f

**Depende de `linger`**: sem `loginctl enable-linger leandro`, as unidades de
usuário morrem quando a sessão SSH termina. Já está habilitado — mas é a
primeira coisa a checar se os serviços "somem" depois de um logout.

**A API está em loopback, e os três serviços também.** A porta `18080` (e não
`8000`) é para não colidir com o default que qualquer outro projeto Python da
máquina escolheria.

Houve um bind em `0.0.0.0` em 2026-09-05, **revertido no mesmo dia** por
decisão de Leandro. O motivo da reversão é o item 4 abaixo: enquanto o estado
do firewall for desconhecido, escutar na `eno1` significa senha e áudio de
reunião em **HTTP puro** ao alcance de qualquer máquina da `10.4.0.0/16` — a
instituição inteira. O teto de upload e a allowlist de domínio reduzem a
superfície, mas nenhum dos dois cifra nada.

**Não reabra o bind sem as duas condições**, ambas confirmadas por Leandro:

1. o administrador do NumbERS confirmou a regra de firewall da `18080`;
2. existe plano concreto de TLS — mesmo provisório (certificado autoassinado,
   já que o acesso é por VPN interna).

Até lá o caminho é o túnel SSH abaixo, que não depende de ninguém.

Quando reabrir, use `0.0.0.0` e **não** o IP específico: o endereço da `eno1`
vem por DHCP (`10.4.254.201` via `10.4.0.1`), e fixar um IP que pode mudar
faria o uvicorn falhar com *cannot assign requested address* e entrar em loop
de restart — a API simplesmente não subiria, no pior momento possível. As
demais interfaces (`docker0`, bridges, `wlp101s0`, `enp103s0`) estão DOWN,
então na prática isso seria `eno1` + loopback. **Quem pode chegar à porta é
responsabilidade do firewall**, que é a camada certa para isso; restringir pelo
bind seria frágil e daria uma falsa sensação de controle — mas essa camada
certa só vale depois que se souber que ela existe.

Há cópias datadas da unidade em
`/data/projects/leandro/scitechear/scitechear-api.service.bak-*`.

O Ollama foi instalado **sem privilégio de root**, em `~/.local/bin`, mesmo com
o usuário estando no grupo `sudo`: o único ganho do root seria compartilhar o
servidor e os 9 GB do modelo com outros pesquisadores, e ninguém mais pediu
LLM.

## Como o app alcança o backend

A API responde só em `127.0.0.1:18080`, então **nenhum aparelho na rede a
alcança diretamente** — nem pela VPN. O túnel SSH abaixo é o caminho, e não
depende de ninguém.

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

A máquina tem IP **`10.4.254.201/16`** na interface `eno1` — a rede do IFG,
por DHCP (a lease renova; **para o piloto, peça reserva de DHCP ao admin**, ou
o app aponta para um alvo que pode mudar). Vale para os dois cenários — o do
professor e o dos alunos é a mesma mudança, o que é bom: dá para testar na
topologia real antes.

Os quatro itens abaixo são **pré-requisitos do bind na rede**, não
consequências dele. A ordem importa: 1 e 2 são o que autoriza o 4.

1. **Liberar a porta no firewall** — *exige quem administra o servidor*.
   Idealmente restrito à faixa do laboratório, não à `10.4.0.0/16` inteira.
   Enquanto o estado do firewall for desconhecido, o bind na rede tem que ser
   tratado como "alcançável por qualquer máquina da instituição".
2. **Decidir sobre TLS.** O tráfego é HTTP puro; na rede institucional isso
   significa senha e áudio de reunião em claro para quem estiver na mesma
   rede. Um certificado próprio exige configuração no app Android
   (`network_security_config` ou CA instalada), então tem uma perna na Fase 7 —
   não dá para resolver só do lado do servidor. Para o piloto, um certificado
   autoassinado basta (o acesso já é por VPN interna).
3. ~~**Fechar as portas de entrada abertas.**~~ **Feito** (ver abaixo): teto de
   upload e allowlist de e-mail no registro, esta última já ativa em produção
   com `ifg.edu.br` e confirmada recusando domínio de fora com `403`. Reduzem a
   superfície, mas **não cifram nada** — não substituem o item 2.
4. **Bind na interface da rede.** Feito e revertido em 2026-09-05 (ver "Os três
   serviços"). Só reabrir depois de 1 e 2, com confirmação de Leandro.

**`10.4.0.0/16` é a instituição inteira, não só o laboratório.** É a razão de
os dois tetos abaixo existirem: com a API em loopback, quem chega à porta já
está dentro da máquina, e nenhum dos dois faz falta — eles existem para o dia
em que o bind reabrir.

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
