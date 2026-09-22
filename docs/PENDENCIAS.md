# Pendências — SciTech Ear · Backend

Registro vivo de achados que não bloqueiam a fase corrente, mas precisam de
acompanhamento — calibração de prompt/modelo, comportamento a reverificar
antes de considerar algo definitivamente resolvido, etc. Diferente de
`docs/BASELINE.md` (retrato pontual da Fase 0): este arquivo é atualizado ao
longo do projeto.

## Aberta — Experimento candidato: o formato da transcrição entregue ao LLM

**Onde:** `TranscriptFormatter.render()` (`app/services/transcript_formatter.py`).

**O quê.** O formatter entrega ao LLM linhas no formato
`N -> seg_XXXX -> [Falante]: texto`. Os prompts que **precisam** disso são os
que resolvem linha em segmento: as explícitas (`linha_transcricao`) e o v4 das
implícitas (`linhas_evidencia`). O **v6 não usa número de linha para nada** —
não pede evidência —, então para ele o prefixo `N -> seg_XXXX ->` é ruído. Os
exemplos few-shot do próprio v6 mostram `Nome: texto`, sem prefixo.

**Por que não foi mexido.** Alterar o render durante o comparativo v4 × v6
introduziria uma segunda variável, e o formatter é compartilhado com as
explícitas — o risco de regressão está fora do escopo do trabalho do prompt.
Decidido explicitamente: **experimento separado, depois.**

**Hipótese a testar.** Se o ruído do prefixo atrapalha a leitura da transcrição
pelo modelo, um render sem prefixo (apenas para o caminho v6) melhoraria a
sustentação das perguntas. É plausível, mas **não medido** — e está atrás do
saneamento do sumarizador na fila, porque a contaminação conhecida hoje vem de
lá, não daqui.

**Status:** aberta, não bloqueia nada. Ideia registrada para não se perder.

---

## Resolvida — A sumarização era a fonte real da confabulação, não o prompt de implícitas

**Onde:** `prompts/meeting_summary_v1.txt` / `question_service.summarize_meeting`.

**Descoberto em:** comparativo v4 × v6 de 22/09/2026
([`COMPARATIVO_IMPLICITAS_V4_V6.md`](COMPARATIVO_IMPLICITAS_V4_V6.md)), ao ler
manualmente cada pergunta gerada contra a transcrição original.

**O quê.** Toda premissa sem lastro que apareceu nas perguntas implícitas —
nas **duas** versões de prompt — **já estava afirmada no sumário**. O prompt de
implícitas apenas a leu com fidelidade. Rastreado linha por linha nos sumários
salvos em [`repro/implicitas-v4-v6/`](repro/implicitas-v4-v6/):

- **Inventa fato.** `2e335c5c_sumario.txt:52` afirma "prazo final
  **(30 de outubro)**" — a transcrição diz "o dia 30 **deste mês**" e a palavra
  "outubro" não aparece nela. O mesmo sumário cita a frase correta nas linhas
  73–74: ele **se contradiz internamente**.
- **Afirma dependências que ele mesmo rotula de implícitas.**
  `50098d37_sumario.txt:146`, sob o cabeçalho literal **"Dependências
  implícitas"**: "A interface gráfica depende da geração de datasets
  sintéticos" — dependência que não existe na transcrição (são frentes
  paralelas).
- **Enumera ausências.** `50098d37_sumario.txt:58` ("Não há prazo explícito
  mencionado") e `00c2ff18_sumario.txt:135` ("Não há menção à data exata"). Uma
  ausência listada como item vira matéria-prima de pergunta.
- **Se contradiz sobre fato central.** `00c2ff18_sumario.txt:101` diz que a
  atualização do cronograma *depende* da validação da coordenação; as linhas
  109 e 127 do mesmo arquivo dizem que a coordenação *já validou*.

**Por que isso reclassifica o problema.** A pendência de confabulação das
implícitas está registrada neste arquivo como se fosse do prompt de implícitas.
Ela é, em parte, mas a parte que sobrou depois do v4 **não é corrigível ali**:
nenhuma versão do prompt de implícitas e nenhum parser podem recuperar um fato
que chega errado do insumo anterior. O v6 chega a **mandar** não fazer isso
("Não transforme automaticamente as categorias ou elementos da sumarização em
perguntas") e o modelo não obedece, porque o sumário afirma como fato.

**O que isso também mostra.** A validação de evidência do v4 valida
**ancoragem**, não **sustentação**: na ata de alinhamento sem nenhuma questão
aberta, todas as 15 perguntas inventadas pelo v4 passaram pela validação porque
citaram linhas que existem de fato. Ancorar numa linha real não torna a
pergunta sustentada por ela.

**Encaminhamento (não feito).** Sanear o sumarizador antes de decidir entre v4
e v6 — no mínimo: não enumerar ausências como itens, não inferir dependências,
e manter fidelidade literal a datas/números citados. Depois, repetir o
comparativo com o sumário limpo, que é o único jeito de medir quanto da
confabulação residual do v6 é dele mesmo.

**Desfecho (22/09/2026).** Corrigido em duas frentes, medido em
[`COMPARATIVO_REMEDIACAO.md`](COMPARATIVO_REMEDIACAO.md) com os mesmos quatro
jobs, contra o baseline sem nenhuma correção:

- **Filtro estrutural** (`app/services/summary_filter.py`, ligado por padrão):
  descarta as seções "Conhecimento implícito" e "Lacunas" e os elementos de
  ausência. Não toca em prompt algum — muda o **consumo** do sumário. Ataca a
  inferência sancionada e os placeholders de ausência.
- **`prompts/meeting_summary_v2.txt`** (opt-in, default segue `v1`): duas
  edições e nada mais — o campo `Resumo` ganha descrição (era o único campo do
  schema sem nenhuma) e a regra de validação 20 proíbe deduzir, converter ou
  completar dado factual. Ataca o fato inventado, que nenhum filtro alcança.

**Resultado.** Os cinco defeitos listados acima desapareceram. "outubro" passou
de 1 ocorrência para **0** nos quatro sumários, e a correção atravessou até o
texto da pergunta ("o prazo de 30 do mês"). A ata de alinhamento — o controle
que devia dar zero — passou de 2 perguntas implícitas para **0**. Dos oito
defeitos duros do v6, **o insumo respondia por cinco**; os três restantes são
do prompt v6 e não são alcançáveis daqui.

Os sumários **não empobreceram**, que era o risco declarado: 61 → 68 elementos
no total, dois dos quatro cresceram.

**Status:** resolvida como diagnóstico e como correção. Deixa de ser bloqueio
para reativar a etapa de implícitas. Duas coisas seguem em aberto e têm item
próprio neste arquivo: o **default do `meeting_summary_v2`** e a **taxa própria
do v6**. Nada em produção mudou — `ENABLE_IMPLICIT_QUESTIONS` segue `false`.

---

## Aberta — Default do `meeting_summary_v2`: decidir com volume real do piloto

**Onde:** `MEETING_SUMMARY_PROMPT_VERSION` (`app/config.py`) /
`prompts/meeting_summary_v2.txt`.

**Decidido em:** 22/09/2026, ao fechar a remediação do sumarizador.

**O quê.** O v2 fez o que foi desenhado para fazer e não custou o que se temia
(ver [`COMPARATIVO_REMEDIACAO.md`](COMPARATIVO_REMEDIACAO.md)): acabou com o
fato inventado, atravessou até o texto da pergunta, e os sumários ficaram
maiores, não menores. Ainda assim **o default segue `v1`**.

**Por que não foi promovido agora.** Quatro jobs não bastam para promover um
prompt que muda a saída do LLM em **toda** reunião. O corpus é pequeno, três
das quatro transcrições são curtas, e um dos efeitos observados ainda não tem
causa provada: a conversa trivial saiu de 0 para 7 elementos no sumário — todos
fatos fiéis, mas é uma mudança de comportamento que merece mais amostra antes
de virar padrão.

**Encaminhamento.** Revisitar quando houver volume real de reuniões do piloto,
não só este corpus. O que decide: se os sumários v2 mantêm fidelidade factual
em transcrições longas e variadas, e se o aumento de elementos em conversa
trivial se confirma e importa.

**Status:** aberta, não bloqueia nada. Trocar é uma linha de `.env`, e o v1
continua intacto no repositório.

---

## Aberta — Prompt v6 de perguntas implícitas: implementado, ainda não avaliado

**Onde:** `prompts/implicit_questions_v6.txt`,
`question_service._extract_implicit_questions_v6`,
`IMPLICIT_QUESTIONS_PROMPT_VERSION` (`app/config.py`). Branch
`feat/perguntas-implicitas-v6`.

**O quê.** Existe agora um segundo prompt de perguntas implícitas, enviado pelo
usuário e colado **sem nenhuma alteração** de texto. Ele coexiste com o v4: a
variável `IMPLICIT_QUESTIONS_PROMPT_VERSION` escolhe qual roda, e o **default
continua `v4`**. Nenhum default de produção mudou —
`ENABLE_IMPLICIT_QUESTIONS` segue `false`.

**O que o v6 muda, e é o ponto todo.** Ele pede **lista numerada de texto
puro**, não JSON, e **não pede `linhas_evidencia`**. Com isso:

- O parser do v4 não serve (verificado: `_extrair_json` levanta `ValueError`
  com lista numerada), então o caminho v6 tem parser próprio e estrito — só
  linhas `N. ` / `N) `, com `"Não possui"` reconhecido como lista vazia válida.
- **A validação programática anti-confabulação do v4 deixa de existir nesse
  caminho**, porque o sinal que ela consome (evidência rastreável até linhas
  reais da transcrição) não é mais pedido ao modelo. `source_segment_ids` vem
  **vazio** — campo honestamente vazio, não âncora inventada por
  similaridade. Foi decisão explícita: ancorar por similaridade fabricaria
  rastreabilidade que ninguém conferiu.
- O teto de 15 do prompt é **observado e logado, nunca truncado** — truncar
  esconderia o comportamento real do modelo, que é justamente o que precisa
  ser medido.
- Uma resposta sem lista numerada **e** sem o sentinela `"Não possui"` é erro
  real (`ValueError`), não "reunião sem perguntas implícitas" — regra
  inviolável nº 5.

**Montagem do prompt (difere do v4 de propósito).** O texto do v6 termina no
banner `###REUNIÃO ABAIXO###`, então a **transcrição** vem imediatamente depois
dele e o **sumário** vem por último, sob o cabeçalho `##SUMARIZAÇÃO DA
REUNIÃO`. No v4 a ordem é a inversa (sumário primeiro). O cabeçalho de cola
vive no código, não no arquivo de prompt.

**Comparativo com dados reais: feito** (22/09/2026, 4 transcrições reais,
`qwen3:14b`). Ver [`COMPARATIVO_IMPLICITAS_V4_V6.md`](COMPARATIVO_IMPLICITAS_V4_V6.md)
e os artefatos em [`repro/implicitas-v4-v6/`](repro/implicitas-v4-v6/).
Resumo: **45 perguntas no v4 contra 11 no v6**; o v4 bateu exatamente o teto
de 15 em três dos quatro jobs (inclusive numa ata sem uma única questão
aberta), o v6 nunca passou de 5. Os dois controles de confabulação passaram
nas duas versões, e o sentinela `Não possui` funcionou com o modelo real.

Na leitura manual das 11 do v6: 4 genuinamente sustentadas, 1 com o núcleo
sustentado mas detalhe factual alucinado, 2 redundantes entre si, 3 sem
sustentação, 1 limítrofe.

**Decisão: o default continua `v4`.** O v6 é melhor em tudo que se mediu, mas
(a) 45% da saída dele ainda é redundante ou sem lastro, e (b) trocar agora
substituiria uma etapa com rede programática por uma sem nenhuma enquanto a
fonte real da confabulação segue intacta — ver a pendência do sumarizador
abaixo, que é o bloqueio de verdade.

**Status:** aberta, aguardando o saneamento do sumarizador para repetir o
comparativo com insumo limpo. Não bloqueia nada: com o default `v4`, o
comportamento do sistema é idêntico ao de antes desta branch.

---

## Aberta — GPU0 fora de operação desde 19/09/2026; o sistema roda sem redundância

**Onde:** infraestrutura do servidor NumbERS. **Não é defeito deste projeto**,
e não há conserto no software — está aqui porque limita a operação e porque o
dono da solução é outro.

**O que houve.** A GPU0 (PCI `0000:21:00`) sofreu **falha física** em
19/09/2026: **Xid 79**, *GPU has fallen off the bus*. A causa foi confirmada
como física, sem relação com o software. A placa continua listada no
barramento (`lspci` mostra `21:00.0`), mas o driver não a inicializa.

**Estado atual.** Tudo roda na GPU1 (PCI `0000:c1:00`) — o worker do pipeline,
o Ollama com `qwen3:14b` (14 GB de VRAM) e os outros projetos da máquina
compartilhada. **Uma placa, sem redundância.** O `nvidia-smi` abre com
`Unable to determine the device handle for GPU0`, e `torch.cuda.device_count()`
devolve `1`.

**Por que importa mesmo sem impacto de desempenho.** O worker é serial por
decisão (um job por vez, pipeline GPU-bound), então a placa parada não deixa
nenhum job mais lento — ela remove a margem. Qualquer problema na GPU1 agora
para o sistema inteiro em vez de degradá-lo, e não há para onde migrar carga.
No piloto, o teto de capacidade continua sendo a **fila**, não a invasão.

**Uma armadilha silenciosa que a falha criou.** As unidades de systemd fixam
`CUDA_VISIBLE_DEVICES=0`, que é índice de enumeração do CUDA e não endereço
PCI. Com a GPU0 fora, esse `0` passou a apontar para a placa sobrevivente — o
pin funciona hoje por coincidência. **Quando a GPU0 for reparada, ele volta a
apontar para ela sem avisar**, e ela era ~15% mais lenta. Revisar esse
`Environment=` faz parte do reparo. Detalhe em [`DEPLOY.md`](DEPLOY.md)
("Armadilhas conhecidas").

**Dono:** administrador do servidor — **aguardando reparo físico**. Nada a
fazer do nosso lado além de não presumir duas placas em conta de capacidade
nem em diagrama.

**Verificação (sem privilégio):** `nvidia-smi`, `lspci | grep -i nvidia`,
`.venv/bin/python -c "import torch; print(torch.cuda.device_count())"`. O
`kern.log` com o Xid é legível só pelo grupo `adm`, do qual o usuário do
projeto não participa.

## Aberta — Revisar `CUDA_VISIBLE_DEVICES` quando a GPU0 for reparada

**Gatilho:** o administrador do servidor devolver a GPU0 (PCI `0000:21:00`) ao
barramento. **Não é uma tarefa para fazer agora** — é uma que precisa
acontecer *no momento* do reparo, e que não pode depender de alguém lembrar.

**O que fazer:** revisar o `Environment=CUDA_VISIBLE_DEVICES=0` em
`~/.config/systemd/user/scitechear-api.service` e
`~/.config/systemd/user/scitechear-worker.service`.

**Por quê.** Esse `0` é um índice de **enumeração do CUDA**, não um endereço
PCI. Com a GPU0 fora do barramento, o CUDA não a enumera, e o índice `0`
passou a apontar para a **GPU1** (`0000:c1:00`), a placa sobrevivente — o pin
acerta hoje **por coincidência de reenumeração**, não por configuração. Quando
a GPU0 voltar, ela reassume o índice `0` e **o pin volta a apontar para ela**.

**Por que isso é armadilha e não só um ajuste.** A mudança é **silenciosa**:
não há erro, não há aviso, não há nada no journal. O sistema sobe normal,
processa normal, e simplesmente fica mais lento — pelas medições anteriores à
falha, a GPU0 era **~15% mais lenta** que a GPU1. O sintoma (degradação de
desempenho sem causa aparente, logo após uma intervenção de hardware) não
sugere a causa, e o lugar onde a causa mora não é versionado: as unidades
vivem em `~/.config/systemd/user/`, fora do checkout — só o
`scitechear-proxy.service` está em `deploy/`.

**Como conferir, depois do reparo:**

    # qual índice é qual placa, agora que são duas de novo
    nvidia-smi --query-gpu=index,name,pci.bus_id --format=csv

    # em qual placa o worker de fato está
    nvidia-smi   # a seção "Processes": confira o bus-id da linha do app.worker

Decida o índice pelo **bus-id**, não pelo número que estava lá antes. Depois
de editar, `systemctl --user daemon-reload` e reiniciar as duas unidades.

**Relacionado:** [a pendência da falha da GPU0](#aberta--gpu0-fora-de-operação-desde-19092026-o-sistema-roda-sem-redundância)
e a seção "Armadilhas conhecidas" de [`DEPLOY.md`](DEPLOY.md).

## Resolvida — O "4401 que não atravessava o proxy" era o cliente do smoke, não o Caddy nem a API

**Onde:** `scripts/smoke_contrato.py` (corrigido em 21/09/2026). O
`deploy/Caddyfile` e o `app/api/jobs.py` estão **corretos** e não foram
alterados por causa disto.

**O que se acreditava, e por quanto tempo.** Desde 06/09/2026 acreditava-se que
o fechamento `4401` do WebSocket não atravessava o proxy TLS: com token
inválido, o cliente ficava pendurado no handshake. Em 21/09, ao ser
investigado de novo, o diagnóstico foi *refinado* para uma tese de duas
condições (TLS **e** `permessage-deflate`). **As duas versões estavam erradas**,
pelo mesmo motivo de método: cada célula da matriz de isolamento foi medida
**uma única vez**, num defeito que se manifesta de forma intermitente. Com
n=1, a matriz mostra o que o acaso quiser.

**O que foi medido, com n alto, contra o proxy de produção e o mesmo alvo:**

| cliente | entregou o `101` + close |
|---|---|
| TLS cru de stdlib (`socket` + `ssl`) | **20/20** |
| `websockets` **assíncrono** (mesmo pacote, mesma versão 17.1) | **15/15** |
| `websockets.sync` (o que o smoke usava) | 1/15 a 9/12 **conforme a rodada** |

Dois clientes independentes recebem o fechamento pelo mesmo proxy TLS, sem
uma falha. **Logo o servidor entrega corretamente, e sempre entregou.** O que
pendura é um cliente só.

**E não era nada do que se suspeitava.** Cada hipótese foi medida e descartada:

- **Não é o código de fechamento nem o token.** Com token *válido* e job
  inexistente (close 4404 imediato) pendura igual: 15/20. Com um **job real**,
  recebendo progresso, pendura 17/20 — enquanto a mesma conexão **direto na
  API** funciona **20/20**.
- **Não é `permessage-deflate`.** No repro, 24/30 penduram com deflate e 24/30
  sem. Na produção, sem deflate ainda pendura 31/50. A tese das duas condições
  não sobrevive a n=30.
- **Não é o `bind tcp4/`** introduzido em 21/09 (`6cb7eb0`): 19/20 penduram com
  e sem o prefixo.
- **Não é HTTP/2 nem ALPN:** forçando `ALPN=http/1.1` no cliente, 18/20.
- **Não é o close imediato.** Atrasar o close em 5, 50, 500 e 2000 ms não muda
  nada, e um upstream que **fica aberto** também pendura.
- **Não é versão do Caddy:** o 2.10.0 falha igual ao 2.11.4 (18/20 contra
  19/20), lado a lado, mesmo upstream.
- **Não é a rede nem a exposição na 443:** pelo loopback `127.0.0.1:443` é
  ainda pior (0/20).

**O que o proxy registra** fecha o argumento: `status=101`, `duration=0.003s`,
`size=124` — o Caddy responde e contabiliza a resposta. Quem não a processa é
o cliente.

**A correção:** `scripts/smoke_contrato.py` passou a usar
`websockets.asyncio.client` no lugar de `websockets.sync.client` (blocos `[5]`
e `[6]`). Rodado 3× seguidas pelo proxy TLS depois da troca: **21 OK, 0 falhas**
nas três. Antes da troca, três rodadas seguidas davam `21 OK`, `20 OK/1 falha`
e um `TimeoutError` cru no meio do check `[5]` — **com token válido**. A
referência "20 OK/1 falha pelo proxy", repetida em vários documentos, nunca foi
um número estável: era um sorteio.

**Por que passou despercebido por duas semanas.** O caminho direto na API não
usa TLS, e ali o cliente síncrono funciona sempre (30/30) — então toda
verificação local passava. Pelo proxy, cada verificação anterior foi uma
amostra só, e "passou" bastava para seguir adiante.

### Os quatro caminhos, todos descartados

1. ~~Recusar o handshake com HTTP 401/403.~~ **Descartado antes**, e segue
   descartado: cliente nenhum distingue o motivo de um handshake recusado.
2. ~~Segurar o close por alguns milissegundos na API.~~ **Descartado**:
   consertaria um sintoma que não existe no servidor — e a medição do atraso
   (5 a 2000 ms) mostra que nem sintoma resolveria.
3. ~~**Relatar ao Caddy.**~~ **Descartado: não há bug do Caddy para relatar.**
   O rascunho que chegou a ser escrito está versionado em
   `docs/repro/ws-handshake-mudo/RELATO-CADDY-REFUTADO.md`, com o cabeçalho
   dizendo por que **não deve ser enviado**. Enviá-lo custaria o tempo de um
   mantenedor e a credibilidade de um relato futuro.
4. ~~**App tratar handshake mudo como sessão expirada.**~~ **Descartado: o
   Flutter nunca foi afetado.** O app não usa a biblioteca Python com o
   defeito; ele fala pela pilha do Dart (`web_socket_channel` sobre
   `dart:io`). E, se tivesse sido implementado, seria **ativamente errado**:
   traduziria um handshake mudo em "sua sessão expirou" justamente nos casos
   em que o token está válido.

**Nota sobre o cliente Flutter, que motivou a investigação.** Foi verificado
na fonte dos pacotes que o app pede `permessage-deflate` por padrão —
`CompressionOptions.compressionDefault` tem `enabled = true`, e nem
`IOWebSocketChannel.connect` nem o caminho cross-platform
(`package:web_socket` → `io.WebSocket.connect`) repassam `compression`. O dado
está correto e ficou registrado, mas **deixou de ter consequência**: como o
deflate não é a causa, não há nada a mudar no app. Se algum dia for preciso
desligar a compressão lá, note que `IOWebSocketChannel.connect` não expõe o
parâmetro — seria preciso `WebSocket.connect(..., compression:
CompressionOptions.compressionOff)` e embrulhar com `IOWebSocketChannel(ws)`.

**Fica em aberto, fora do escopo deste projeto:** *por que* o cliente
`websockets.sync` 17.1 pendura sob TLS. A causa interna não foi investigada
(descartada a hipótese de `select()`, que no pacote só aparece no servidor), e
nada foi relatado ao projeto — não repita aqui o erro de relatar sem entender.
Para o backend isso não é pendência: o smoke não usa mais esse cliente.

**O que ainda usa o cliente síncrono, e pode continuar usando:**
`tests/test_ws_codigos_de_fechamento_reais.py` sobe um uvicorn real em
`ws://127.0.0.1` — **sem TLS**, condição em que o cliente síncrono entregou
30/30. O teste passa de forma estável e não precisa mudar; se um dia ele
passar a falar TLS, troque o cliente junto.

**Repro e evidências:** `docs/repro/ws-handshake-mudo/`.

## Resolvida — Perguntas explícitas: prefixo `[Nome]: ` vazando no campo `text`

**Onde:** `question_service.extract_explicit_questions` (prompt
`prompts/explicit_questions_v4.json`).

**O quê:** validando o pipeline completo com `qwen3:4b` (modelo local, usado
só para testar o caminho feliz — não é o modelo de produção), o campo
`text` da pergunta explícita às vezes vem com o prefixo `[Nome]: ` colado,
ex.: `"[Leandro]: Qual é o prazo final para entregar a integração
completa?"` em vez de só `"Qual é o prazo final para entregar a integração
completa?"`.

**Causa:** o `TranscriptFormatter` monta cada linha da transcrição como
`"N -> seg_XXXX -> [Nome]: texto"` para os prompts. O prompt
(`explicit_questions_v4.json`) e seu exemplo few-shot deixam claro que o
campo `pergunta` deve conter só o texto após os dois-pontos — o rótulo
`[Nome]:` é parte do formato de linha, não da pergunta. Com `qwen3:4b`, o
modelo às vezes copia o rótulo junto.

**Por que não foi corrigido no código:** o serviço repassa `item.pergunta`
literalmente, por design — a regra é "não corrigir o texto da pergunta"
(nem a resposta do LLM, nem o texto original do segmento). Tratar isso no
código seria decidir, sem saber a real intenção do modelo, o que cortar da
string — o problema é de fidelidade do modelo ao prompt, não do pipeline.
É um ponto de calibração (junto com thresholds de biometria, min/max
speakers etc., que a spec já marca como não bloqueantes para a V1).

**Próximo passo:** reverificar com `qwen3:14b` (modelo de produção,
pinado na spec) antes de decidir se isso precisa de ajuste de prompt. Se o
`qwen3:14b` também vazar o prefixo, considerar reforçar a instrução do
prompt (algo como "não inclua o rótulo `[Nome]:` no campo `pergunta`") —
mudança de prompt, versionada, sem alterar os critérios semânticos
existentes (regra do AGENTS.md).

**Reverificação com `qwen3:14b` (2026-09-05, E2E da Fase 8 — ver
`docs/E2E_FASE8.md`):** o problema **persiste no modelo de produção**, então
não era limitação do `qwen3:4b`. Mas a reverificação trouxe um recorte que o
registro original não tinha: das sete perguntas explícitas extraídas nos cinco
cenários, **as duas que vazaram o prefixo foram exatamente as do único cenário
em que o falante não foi identificado** — nele o rótulo da linha é
`[SPEAKER_00]`, e saiu `"[SPEAKER_00]: Juno, tudo certo?"`. Nos cenários com
falante identificado, em que o rótulo é um nome próprio, nenhuma das cinco
perguntas veio com prefixo.

Hipótese que isso sugere (ainda não testada isoladamente): um nome próprio é
reconhecido pelo modelo como rótulo de formato, enquanto `[SPEAKER_00]` —
sintético e sem semântica de pessoa — é tratado como parte da fala. Se
confirmado, o ajuste de prompt deve mirar especificamente o caso do falante
não identificado, e não a instrução geral.

**Correção (2026-09-05, `prompts/explicit_questions_v5.json`):** feita por
prompt, versionada, com os critérios de extração intactos — o serviço continua
repassando `item.pergunta` literalmente, sem cortar string nenhuma em Python.
Três edições cirúrgicas sobre o v4:

1. uma regra nova dizendo que o rótulo entre colchetes que abre a linha
   (`[Leandro]: `, `[SPEAKER_00]: `) é formato da transcrição e não pertence ao
   campo `pergunta`, explicitamente inclusive quando é identificador genérico;
2. um segundo exemplo few-shot com falante **não identificado** — o v4 só tinha
   exemplo com nome próprio, que era justamente o caso que já funcionava;
3. o exemplo de sentença curta em `instrucoes_importantes` passou a mostrar o
   texto extraído (`extraia 'Verdade?'`) em vez da linha inteira
   (`'SPEAKER_00: Verdade?'`), que reforçava o comportamento errado.

**Validação A/B nos quatro cenários do E2E, com `qwen3:14b` e os mesmos
áudios:**

| Cenário | v4 | v5 |
|---|---|---|
| R4 (falante não identificado) | `[SPEAKER_00]: Juno, tudo certo?` | `Juno, tudo certo?` |
| R1 (2 identificados, 2 perguntas) | correto | idêntico ao v4 |
| R2 (1 pergunta) | correto | idêntico ao v4 |
| R3 (nenhuma pergunta) | lista vazia | lista vazia |

O único caso ruim foi corrigido e os três bons ficaram idênticos ao baseline —
inclusive preservando o erro de ASR ("estação" no lugar de "extração"), o que
confirma que a cópia literal continua valendo.

**Limitação desta validação:** uma execução por cenário, com áudio sintético.
A geração é determinística (`temperature=0`, `seed=42`), mas isso não descarta
que outra transcrição provoque o vazamento por outro caminho. Mesma ressalva
que `docs/PERFORMANCE.md` faz sobre a validação de `think=False`.

`tests/test_question_service.py` trava as duas metades da decisão: que o prompt
ativo tem a regra e o exemplo com rótulo genérico, e que o código **não**
sanitiza o texto devolvido pelo LLM (se alguém "ajudar" cortando o prefixo em
Python, o teste quebra).

**Status:** resolvida.

---

## Aberta — Fronteira de turno: primeira palavra curta de um turno é atribuída ao falante anterior

**Onde:** `app/services/diarization_service._atribuir_clusters` (a rigor, a
fronteira devolvida pelo pipeline do pyannote).

**O quê:** no E2E da Fase 8 (2026-09-05, cenário R3 — `docs/E2E_FASE8.md`),
dois segmentos saíram com o falante errado, ambos com o mesmo padrão: uma
interjeição curta que **abre** um turno foi atribuída a quem falou antes.

    26,79-27,99  SPEAKER_00 → p-ana     "Combinado."    (era da Carla)
    34,63-35,01  SPEAKER_01 → p-carla   "Perfeito."     (era da Ana)

**Causa:** `_atribuir_clusters` escolhe, para cada segmento da transcrição, o
cluster de maior sobreposição temporal — o que está correto. O deslocamento
vem da fronteira de turno do pyannote, que chega ~1s atrasada; o segmento
curto inteiro cai antes dela e herda o cluster anterior.

**Impacto:** 1,6s de 173,8s de fala (0,9%) no E2E, sempre em palavra isolada.
Não afeta o corpo das falas nem nenhuma pergunta extraída. É sistemático (não
aleatório), o que facilita reconhecer o padrão em produção.

**Por que não foi corrigido:** qualquer correção aqui é heurística — mover a
fronteira, ou reatribuir segmentos curtos ao cluster seguinte, exige decidir
sem evidência qual dos dois lados está certo, e pode piorar casos em que a
interjeição realmente pertence ao turno anterior ("Combinado." dito por quem
já estava falando). Precisa de mais dados reais antes de virar regra.

**Status:** aberta, baixo risco, não bloqueia a V1.

---

## Aberta — Falas curtas alternadas colapsam a diarização num cluster só

**Onde:** `app/services/diarization_service.diarizar`.

**O quê:** no E2E da Fase 8 (cenário R4: nove falas de 1 a 3 palavras,
alternando dois falantes, mais um trecho sobreposto), o pyannote **encontrou**
dois clusters — o log registra `SPEAKER_00, SPEAKER_01` com
`Pouca duração de fala para SPEAKER_01: 2,6s` — mas nenhum dos nove segmentos
da transcrição teve o `SPEAKER_01` como cluster de maior sobreposição. O
resultado final saiu com **um cluster só**.

**Desdobramento (o comportamento desejado):** o embedding do cluster misturado
deu 0,609, abaixo do threshold de 0,75, e ninguém foi identificado. O sistema
preferiu não responder a responder errado — é a política que a recalibração do
threshold quis garantir, funcionando num caso que ela não foi projetada para
cobrir.

**Relação com a pendência de áudio distante/ruidoso:** é o mesmo tipo de falha
(o pyannote não separa bem) por outra causa — ali é a captação, aqui é a
duração dos turnos. As duas convergem para a mesma mitigação: a identificação
degrada para "não identificado" em vez de errar a pessoa.

**Achado colateral de custo:** R4 foi o job **mais caro** (24,5s de extração,
3.397 tokens gerados) apesar de ter o áudio mais curto (20,1s) — 4,6× mais
tokens de saída que a reunião estruturada de 80s. Áudio fragmentado custa mais
que áudio longo, não menos. Relevante para o dimensionamento de uma reunião
real com muitas trocas rápidas de turno.

**Status:** aberta, não bloqueia a V1.

---

## Parcialmente resolvida — Perguntas implícitas: redundância e um detalhe factual alucinado

**Onde:** `question_service.extract_implicit_questions` /
`summarize_meeting`, com `ENABLE_IMPLICIT_QUESTIONS=true`.

**O quê:** no E2E da Fase 8 (cenário R5, `qwen3:14b`, reunião de 80s com nove
falas), a extração devolveu 2 perguntas explícitas e **15 implícitas**.

O que funcionou: **todas as 15 apontam para `source_segment_ids` que existem
de fato** no resultado, e nenhuma é pergunta genérica de roteiro sem lastro —
a correção de confabulação (commit `94cebe2`) continua valendo com dados
novos.

Os dois problemas:

1. **Redundância pesada.** Seis das quinze derivam do mesmo `seg_0016`, e
   várias são paráfrases umas das outras — "Quais critérios serão utilizados
   para determinar se a redução do contexto é viável e eficaz?" ao lado de
   "Como a eficácia da redução do contexto será mensurada e validada?".
   Confirma, com número, o achado de redundância do `qwen3:14b` já registrado
   em `805fe4d`.
2. **Um detalhe factual inventado.** Duas perguntas citam "o prazo final de 30
   de outubro"; a transcrição diz apenas "o dia trinta deste mês". A evidência
   aponta para um segmento real, mas o **texto da pergunta** acrescenta um
   fato que não está nele. É uma falha diferente da confabulação já corrigida
   (que inventava a pergunta inteira, sem lastro): aqui o lastro existe e o
   enfeite está no enunciado.

**Custo:** 56,4s contra 15,1s no mesmo áudio (3,7×), quase todo concentrado em
`summarizing` (28,2s).

**Atualização (22/09/2026) — os dois problemas tiveram destinos diferentes.**

1. **O detalhe factual inventado está resolvido, e a causa não era esta.** O
   "30 de outubro" nunca nasceu no prompt de implícitas: ele já vinha afirmado
   no sumário, e o prompt apenas o leu com fidelidade. O item acima ("A
   sumarização era a fonte real da confabulação") tem o rastreamento; a
   correção é `prompts/meeting_summary_v2.txt`. Medido em
   [`COMPARATIVO_REMEDIACAO.md`](COMPARATIVO_REMEDIACAO.md): "outubro" passou
   de 1 ocorrência para 0 nos quatro sumários, e a pergunta gerada passou a
   dizer "o prazo de 30 do mês". **Observação que importa para quem ler esta
   pendência no futuro:** o diagnóstico original localizava o defeito no
   enunciado da pergunta ("o lastro existe e o enfeite está no enunciado"). O
   enfeite estava, mas não foi posto ali — foi herdado.

2. **A redundância continua, e é do prompt.** No v4 (default) ela é pesada e
   independe do insumo: mesmo com sumário saneado, o v4 devolveu 15 perguntas
   no mesmo R5 — o teto tratado como meta. No v6 caiu para 3, com uma única
   redundância restante no corpus inteiro. Não há mais insumo para limpar:
   reduzir isso exige decidir entre v4 e v6, que é o item próprio abaixo.

**Status:** parcialmente resolvida. O detalhe factual, sim; a redundância, não
— e ela é do prompt, não do insumo. Segue reforçando a decisão de manter
`ENABLE_IMPLICIT_QUESTIONS=false` em produção (flag introduzida em `be8dc49`).
Não bloqueia a V1, que não depende de implícitas.

## Resolvida — Perguntas implícitas confabulando roteiro genérico sem lastro na transcrição

**Onde:** `question_service.extract_implicit_questions` (prompt
`prompts/implicit_questions_v3.txt`, substituído por `v4`).

**O quê:** validado com um job real (16 segmentos, conversa curta e trivial
entre Leandro e a mãe sobre um carro novo — só "estou gostando", "muito bom
pra dirigir", "estou adorando até hoje", nada além disso). Resultado: 4
perguntas explícitas corretas + **15 perguntas implícitas** formando um
roteiro genérico de avaliação de compra de carro (eficiência energética,
segurança, valor de revenda, impacto ambiental etc.) — nenhum desses temas
foi mencionado ou sugerido na conversa real. Confabulação, violando as
próprias restrições do prompt v3 ("não invente fatos que não ocorreram").

**Causa raiz — reproduzida e confirmada** com uma transcrição sintética
equivalente (mesmo formato: conversa trivial e curta), rodada localmente
contra `qwen3:4b` e `qwen3:14b` via Ollama, comparando `v3` (baseline) com
`v4` (corrigido):

- `v3` + `qwen3:4b`: 5 perguntas confabuladas, nenhuma relacionada ao
  conteúdo real (giram em torno de "bem-estar"/"equilíbrio trabalho-saúde",
  temas nunca discutidos).
- `v3` + `qwen3:14b`: **exatamente 15 perguntas confabuladas** — bateu no
  teto do prompt, reforçando a hipótese de que "até, no máximo, 15" estava
  sendo tratado como meta, não limite. Contra a intuição, o modelo **maior**
  confabulou mais (em quantidade), não menos: o problema não era capacidade
  do modelo, era ancoragem de prompt.
- Achado adicional (não hipotetizado antes, encontrado ao revisar o v3): o
  esqueleto JSON de "Formato de saída" do v3 mostrava 1 item no array mas
  `"total_perguntas": 15"` — uma inconsistência estrutural que reforçava a
  âncora "15" antes mesmo do few-shot real (que já estava correto).

**Correção aplicada:**
1. `prompts/implicit_questions_v4.txt` (v3 preservado para rastreabilidade,
   ver `prompts/README.md`): teto de 15 reformulado como limite absoluto —
   nunca meta —, lista vazia declarada explicitamente como saída válida e
   esperada para conteúdo trivial; corrigido o esqueleto JSON inconsistente;
   novo campo obrigatório por pergunta, `linhas_evidencia` (linhas reais da
   transcrição, mesma numeração usada nas explícitas, que fundamentam a
   inferência). Critérios semânticos (linguagem formal, não redundância,
   foco em tomada de decisão) preservados.
2. `question_service._resolver_evidencia_implicita`: validação programática
   — não confia só na instrução do prompt. Resolve cada linha citada via
   `TranscriptFormatter.get_line` (mesmo mecanismo já usado para
   `linha_transcricao` das explícitas); descarta a pergunta inteira se a
   maioria das linhas citadas não existir na transcrição (tolera erro de
   contagem pontual do modelo, tipo off-by-one; não tolera pergunta
   majoritariamente inventada que só "ancorou" numa linha real de forma
   oportunista). `source_segment_ids` passa a ser preenchido para perguntas
   implícitas (antes sempre `[]`); `participant_id`/`speaker`/`time`
   continuam `null` — implícita pode cruzar várias linhas/falantes.
3. Testes de contrato em `tests/test_question_service.py` (fixtures,
   `monkeypatch` em `_chamar_ollama`, sem LLM real): evidência válida
   preenche `source_segment_ids`; sem `linhas_evidencia` descarta; maioria
   das linhas inválida descarta a pergunta inteira; maioria válida mantém
   só as linhas reais; teste de regressão espelhando o incidente (2
   perguntas com lastro real + 17 confabuladas → só as 2 sobrevivem).

**Validação empírica pós-correção** (mesma transcrição sintética,
`qwen3:4b` e `qwen3:14b`): **0 perguntas implícitas geradas nos dois
modelos** — o próprio modelo já não confabulou, a validação programática
não precisou descartar nada nesse caso específico. Ressalva: como o modelo
já retornou lista vazia, essa rodada não exercitou a rede de segurança de
código (descarte por evidência majoritariamente inválida) contra uma
alucinação real — isso está coberto pelos testes de fixture, não pela
chamada real ao LLM. Recomenda-se reverificar com jobs reais diversos
(não só cenários triviais) ao longo do tempo.

**Hipóteses secundárias testadas, não implementadas (conforme escopo
pedido):**
- **Refinador** (`prompts/implicit_refiner_v1.txt`,
  `ENABLE_IMPLICIT_REFINEMENT=true`) rodado sozinho sobre a saída
  confabulada do v3 baseline: reduz a quantidade (`qwen3:4b`: 5→3,
  `qwen3:14b`: 15→10) mas **não audita lastro** — as perguntas remanescentes
  continuam sobre temas não discutidos na conversa real. Confirma a
  ressalva original: o refinador reformula/consolida texto, não verifica
  evidência; não é solução para a confabulação, só reduz volume. Achado
  extra fora do escopo desta calibração: com `qwen3:4b`, a saída do
  refinador veio **em inglês** (possível falha de fidelidade de idioma do
  modelo menor com esse prompt específico) — vale investigar depois, não
  bloqueia.
- **Tamanho do modelo**: `qwen3:14b` (modelo de produção, já default em
  `.env`) **não reduziu** a confabulação em relação a `qwen3:4b` — bateu
  exatamente no teto de 15 no baseline v3. Confirma que a causa raiz era a
  ancoragem do prompt na meta de 15, não a capacidade do modelo — hipótese
  principal do usuário, confirmada empiricamente.

**Status:** corrigido (prompt v4 + validação programática + testes de
contrato). Monitoramento de longo prazo recomendado: um modelo adversarial
poderia, em tese, citar 1 linha real e inventar contexto ao redor dela para
burlar a maioria estrita — a validação atual não elimina esse caso
extremo, é uma redução de risco, não uma prova formal. Não bloqueia fases
seguintes.

**Validação adicional — v4 não ficou conservador demais:** rodado contra
uma segunda transcrição sintética, dessa vez substantiva (decisões reais:
ajuste de threshold de biometria, bug de alinhamento do WhisperX em fala
sobreposta, instabilidade da GPU do Colab, decisão WebSocket vs. polling,
responsabilidade por `DEMO_MODE=false` em staging). Resultado: `qwen3:4b`
gerou 3 perguntas implícitas legítimas e ancoradas; `qwen3:14b` gerou 15,
todas com `linhas_evidencia` reais (100% mantidas na validação
programática) e genuinamente relacionadas ao conteúdo discutido — nenhum
roteiro genérico desconectado, ao contrário do caso trivial do carro.
Confirma que a correção suprime confabulação sem suprimir perguntas
legítimas quando o conteúdo sustenta.

**Achado novo, fora do escopo desta calibração — redundância em
`qwen3:14b`:** nas 15 perguntas geradas para a reunião substantiva, há
sobreposição temática real entre itens (ex.: duas perguntas quase
idênticas sobre a decisão de manter polling em vez de WebSocket; duas
sobre o mesmo ponto de monitorar o threshold 0.35; duas sobre plano de
contingência da GPU). O prompt já pede explicitamente "não repetitivas ou
redundantes", mas o modelo maior não filtrou isso quando o volume de
conteúdo se aproxima do teto de 15. Isso é uma questão de qualidade/
deduplicação, distinta da confabulação (as perguntas têm evidência real,
só se repetem) — registrado aqui como pendência separada, não implementado
ainda; possível endereçamento futuro seria pós-processamento de
similaridade textual entre `pergunta`s antes de retornar o resultado, ou
reforço adicional no prompt.

**Atualização (2026-08-12) — etapa inteira temporariamente desativada por
decisão do usuário:** apesar da correção acima (prompt v4 + validação
programática de evidência), a extração de perguntas implícitas foi
desligada por padrão via nova flag `ENABLE_IMPLICIT_QUESTIONS` (default
`false`, `app/config.py`) — não confundir com `ENABLE_IMPLICIT_REFINEMENT`
(já desligado antes, continua desligado). Motivo: isolar o comportamento do
restante do sistema (transcrição, diarização, biometria, perguntas
explícitas) enquanto a qualidade da extração implícita é validada
separadamente — a confabulação original foi corrigida e parcialmente
validada (ver acima, branch `fix/perguntas-implicitas-evidencia`), mas
ainda não em volume/diversidade suficiente de reuniões reais para confiar
nela em produção. Quando `ENABLE_IMPLICIT_QUESTIONS=false`:

- `pipeline_facade._extrair_perguntas` não chama
  `question_service.extract_implicit_questions` nem, por consequência,
  `refine_implicit_questions` (que só faz sentido sobre uma saída implícita
  que não existe).
- `question_service.summarize_meeting` também não é chamado — hoje ela só
  existe como insumo interno para as implícitas, sem outro consumidor no
  pipeline; pular as duas juntas evita uma chamada ao Ollama sem uso.
  Estágios de job continuam passando por `summarizing` e `extracting`
  normalmente (contrato de estados inalterado); só o trabalho real dessas
  etapas é pulado.
- `MeetingResult.questions` passa a conter só perguntas `explicit` — sem
  itens vazios ou placeholder no lugar das implícitas.
- **Nada do trabalho já feito foi removido**: `extract_implicit_questions`,
  o prompt v4 e a validação de evidência continuam intactos em
  `question_service.py`, só não são chamados. Reativar é trocar a flag para
  `true` (`.env` ou `.env.example`).
- Regressão: `tests/test_pipeline_facade.py::test_pipeline_pula_etapa_implicita_quando_flag_desligada`
  trava que, com a flag desligada, nem `summarize_meeting` nem
  `extract_implicit_questions` são chamados e o resultado final só tem
  perguntas explícitas.

## Aberta — Identificação biométrica: falso positivo com `VOICE_IDENTIFICATION_THRESHOLD=0.30`, recalibrado para 0.75; risco residual documentado

**Onde:** `app/services/voice_service.identificar_speaker` /
`VOICE_IDENTIFICATION_THRESHOLD` (`app/config.py`, `.env`, `.env.example`).

**Incidente:** em teste real com 4 participantes (3 cadastraram voz, 1 nunca
cadastrou nenhuma amostra), o participante não-cadastrado apareceu no
resultado identificado como um dos outros três — falso positivo de
identificação, mais grave que um falso negativo (atribuir a fala de uma
pessoa a outra é problema de confiança/privacidade, não só de qualidade).

**Investigação (dados reais, não hipotéticos):** reproduzido com áudio TTS
sintético (macOS `say`, pt-BR/pt-PT) — 3 participantes cadastrados de
verdade no `VoiceRepository` (embeddings ECAPA reais), 1 nunca cadastrado.
Rodando `identificar_speaker`/`aplicar_biometria` de produção:

- O pool de comparação (`banco`) já estava corretamente restrito aos
  participantes daquela reunião com embedding cadastrado
  (`pipeline_facade._carregar_banco_e_nomes`) — **não** compara contra todo
  o `VoiceRepository`. Essa hipótese foi descartada.
- Não é bug de lógica de decisão: threshold e margem funcionam exatamente
  como documentado. O problema é calibração: com `THRESHOLD=0.30`, testei o
  falante não-cadastrado contra o banco de 3 perfis e depois testei mais 6
  falantes não-cadastrados diferentes contra o mesmo banco — **6 de 7**
  deram falso positivo, a maioria com margem folgada (não foram rejeições
  "quase certas" que passaram raspando).
- Coletei o piso real de match GENUÍNO com mais amostras (15 = 3 pessoas
  cadastradas x 5 frases novas cada, comparadas contra o próprio perfil):
  **mínimo 0.9157, máximo 0.9543, média 0.9369.**
- Teto de score de impostor, desconsiderando 1 outlier suspeito (ver
  abaixo): **0.6214.**

**Correção aplicada:** `VOICE_IDENTIFICATION_THRESHOLD` alterado de **0.30**
para **0.75** — comfortavelmente abaixo do piso genuíno observado (folga de
0.166) e acima do teto de impostor não-outlier (folga de 0.129), deliberadamente
mais perto do piso genuíno do que do teto de impostor (risco assimétrico:
falso negativo é preferível a falso positivo). `VOICE_MIN_MARGIN` (0.05)
mantido como defesa secundária, não a única — a decisão real que barra a
maioria dos impostores agora é o threshold, a margem cobre o caso de dois
candidatos cadastrados muito parecidos entre si.

**PROVISÓRIO — pendente de revalidação:** 0.75 foi calibrado inteiramente
com embeddings de voz sintética (TTS), não gravações humanas reais. Antes de
produção, revalidar com um conjunto de vozes humanas reais (idealmente
incluindo pares foneticamente parecidos) para confirmar que o piso genuíno e
o teto de impostor observados aqui se sustentam.

**Risco residual em aberto, NÃO resolvido por este threshold:** um dos 7
impostores testados (voz "Reed" do macOS, nunca cadastrada) obteve score
**0.9555** contra o perfil cadastrado de "Eddy" — margem de 0.899 para o
segundo colocado. Esse score cai **dentro** da própria faixa de match
genuíno observada (piso 0.9157), então nenhum threshold plausível de
similaridade de cosseno bloqueia esse caso sem também rejeitar matches
genuínos legítimos. Suspeita (não confirmada): Eddy/Reed são vozes
"novelty" do macOS que aparentemente compartilham o mesmo motor de síntese
base com efeito de pitch/formante por cima, o que infla artificialmente a
similaridade — mas o risco estrutural (duas vozes humanas naturalmente
parecidas, ou parentes) não é hipotético e não tem solução só de threshold.
Esse teste está travado propositalmente como "falha esperada, não
corrigida" em
`tests/test_voice_identification_real_regression.py::test_outlier_reed_eddy_NAO_e_bloqueado_pelo_threshold_075_limitacao_conhecida`
— não deve ser "consertado" trocando o threshold sem antes discutir uma
mudança estrutural (ex.: normalização de score, verificação adicional,
revisão humana para casos limítrofes).

**Regressão:** `tests/test_voice_identification_real_regression.py` usa
embeddings ECAPA reais (não sintéticos/aleatórios) congelados em
`tests/fixtures/voice_identification_real_embeddings.json` — reprodutíveis
via os scripts usados nesta investigação (áudio TTS + `VoiceRepository` +
`voice_service.gerar_embedding`). Trava: os 6 impostores não-outlier
rejeitados, as 15 amostras genuínas identificadas corretamente, e o outlier
Reed/Eddy **não** rejeitado (limitação conhecida).

**Revalidação com voz humana real — EM ANDAMENTO (2026-08-13):** primeiro
caso real reportado — reunião de 1 falante com voz cadastrada apareceu como
NÃO IDENTIFICADO. Diagnóstico (sem reprocessar pipeline; score lido do
`result.json` já persistido e reproduzido isoladamente via
`voice_service` contra os embeddings salvos):

- Job `873111cc-0ada-413f-8742-3f11b10d74a8` (12/08 20:21): score **0.7304**,
  abaixo do threshold 0.75 → rejeitado corretamente pela lógica atual (não é
  bug de decisão). 5 de 7 segmentos qualificaram para o embedding (≥1.5s,
  ~27s concatenados, nenhum outlier) — não é caso de poucos segmentos.
- Dois outros jobs de 1 falante rodados **depois** do fix do threshold
  (commit `86d6c99`, 12/08 19:37) com a mesma pessoa: job `189e5d28`
  (11/08) = 0.7684 (identificado); job `75d7669d` (12/08 19:44) = 0.7621
  (identificado, por pouco).
- **Os 3 scores genuínos reais pós-fix caem em 0.73–0.77** — bem abaixo do
  piso genuíno medido com TTS (0.9157–0.9543). A folga entre o piso
  genuíno real observado e o teto de impostor sintético (0.6214) caiu de
  0.166 (TTS) para **~0.11**. Ainda não há sobreposição confirmada, mas a
  margem de segurança encolheu, como era de se esperar ao trocar TTS por
  voz humana real.
- **Achado colateral corrigido:** o `VoiceRepository` tinha 4 perfis
  "Leandro"/"leandro" duplicados (`participant_id` = timestamp gerado no
  momento do cadastro — cada teste manual do endpoint de enrollment criou
  um participante novo em vez de reutilizar um existente). Confirmado que
  **não é bug de backend**: este serviço não gera `participant_id`, ele é
  puramente definido por quem chama `POST /participants/{participant_id}
  /voice-samples` (contrato do AGENTS.md, regra 4) — os IDs eram lixo de
  testes manuais do endpoint, anteriores à integração com um cliente
  estável. Um dos duplicados batia como 2º colocado (0.7077, margem 0.0227
  para o 1º) no caso acima, o que teria acionado rejeição por
  `VOICE_MIN_MARGIN` mesmo se o threshold fosse reduzido — duplicatas
  distorcem a margem e não podem entrar em dados de calibração. Os 3
  perfis mais antigos foram removidos via `VoiceRepository.delete_profile`
  em 2026-08-13, mantendo só o mais recente (`1786574452078827`). Os
  outros 4 perfis cadastrados (Mãe, Maria, Pedro, Samuel) são pessoas
  reais distintas, sem duplicação.

**Decisão atual: threshold MANTIDO em 0.75.** Ainda não há dados
suficientes para recalibrar com segurança — só uma pessoa real testada até
agora (3 amostras dela mesma), e falta testar impostor real (pessoa A
contra perfil de pessoa B, via microfone, não TTS). Aceitar o falso
negativo específico documentado acima é consistente com a prioridade
assimétrica já definida (falso negativo é preferível a falso positivo).
Pendente: gravar 2-3 frases de pelo menos mais uma pessoa real distinta
para (a) confirmar o piso genuíno humano com mais de 1 amostra/pessoa e
(b) medir impostor real. Só então decidir um novo número, com o mesmo
rigor da calibração anterior.

**Tentativa de mitigação via AS-Norm — INVESTIGADA E NÃO RESOLVIDA
(2026-08-31), registrada aqui em 07/09/2026:** o experimento inteiro e a
implementação vivem na branch `feat/voice-asnorm-decision`, que **não foi
mesclada de propósito** — mas `main` não tinha nenhuma menção a ele, e um
resultado negativo invisível é um convite a refazer o mesmo trabalho. O
resumo, para que a decisão sobreviva na trunk:

Foi prototipado Adaptive Score Normalization (z-score do candidato contra o
cohort dos impostores mais parecidos do próprio banco) em lugar do corte de
cosseno fixo, atrás da flag `ENABLE_VOICE_ASNORM` (default `false`). Contra o
mesmo cenário real desta investigação:

- o falso positivo que motivou tudo (Reed/Eddy, 0.9555) **continuou** falso
  positivo;
- e apareceram **dois falsos positivos novos** (0.4126 e 0.6214) que o
  threshold fixo de 0.75 rejeitava corretamente;
- as 15 amostras genuínas seguiram corretas — não houve regressão nesse eixo.

**A causa não é a implementação, é uma pré-condição não atendida:** com 3
perfis cadastrados, o "cohort de impostores" de cada candidato são as outras
2 pessoas do banco — não uma população independente. Dois pontos
correlacionados ao mesmo áudio inflam o z-score e mascaram o problema.

**Critério para revisitar, e só então:** o banco ter **8-10 perfis**, de
pessoas diferentes das que serão identificadas. Hoje o servidor tem 4 (3 do
E2E sintético + 1 real). Até lá **não reabrir** — a causa é estrutural e o
resultado tende a se repetir. Código, testes e a análise completa estão na
branch; nada disso está em `main` além deste registro.

**Primeira medição com voz humana real em condição de produção
(07/09/2026):** no E2E com o app (`docs/E2E_APP_2026-09-07.md`), um falante
com **uma única amostra** cadastrada foi identificado com `confidence`
**0,889** — folga confortável sobre o threshold de 0,75. É um falante só, não
fecha nada, mas é o primeiro ponto medido fora de TTS e do dataset de
diagnóstico.


## Aberta — Performance do pipeline: extração de perguntas explícitas é ~42% do tempo total; think=False testado e revertido

**Onde:** `app/services/question_service.py` (`_chamar_ollama`,
`extract_explicit_questions`), `app/repositories/job_repository.py`
(instrumentação de tempo por estágio).

**Ver `docs/PERFORMANCE.md`** para a medição completa (tempo por estágio,
breakdown load/prompt_eval/eval do Ollama) e o teste antes/depois de
`think=False` para `extract_explicit_questions`: reduziu o tempo em 77,3%,
mas mudou o CONTEÚDO extraído (perdeu uma pergunta genuína, ganhou uma
frase que não era pergunta) — revertido, `think=True` mantido. Testado com
uma única transcrição sintética; não repetido com dados diversos.

## Aberta — Diarização mistura falantes em áudio distante/ruidoso/sobreposto; não é problema de threshold nem de min/max speakers

**Onde:** `app/services/diarization_service.diarizar` (pyannote pipeline
`pyannote/speaker-diarization-community-1`, `VBxClustering`).

**Incidente (2026-08-16):** reunião informal de 3 pessoas (Leandro, mãe,
terceiro falante), gravada com tablet longe da boca dos falantes, ambiente
ruidoso e fala frequentemente sobreposta. Job
`30343d67-76d1-47ad-a313-8552fa094b87`. Os 3 clusters (`SPEAKER_00/01/02`)
saíram da identificação biométrica com scores muito baixos e uniformes
(0.14–0.33) — bem abaixo tanto do threshold atual (0.75) quanto da faixa
0.73–0.77 já documentada acima como "genuíno real, mas abaixo do
threshold". A uniformidade e a magnitude dos scores sugeriam outra causa,
não simplesmente calibração de threshold.

**Investigação (áudio real ouvido pelo usuário, não hipotético):**
extraídos e concatenados, por cluster, todos os trechos de áudio daquele
cluster (script ad hoc com `soundfile`, não versionado — cada cluster virou
um WAV próprio). O usuário ouviu os 3 arquivos e confirmou por escuta:
**os 3 clusters têm vozes misturadas** — não é um caso isolado, é
generalizado nesta reunião. Confirma que o problema é de diarização
(agrupamento errado, antes até da comparação de embedding), não de
threshold de identificação.

**Descartada a hipótese de min/max speakers mal configurado:**
reprocessada só a etapa de diarização (sem re-rodar WhisperX) com
`num_speakers=3` explícito (`exact_speaker_count=True`, contornando o
range default `DIARIZATION_MIN_SPEAKERS=1`/`DIARIZATION_MAX_SPEAKERS=10`).
Resultado: clusters **idênticos** aos do job original — mesmas fronteiras,
mesmas durações por cluster (SPEAKER_00: 9 segmentos/8.69s; SPEAKER_01: 7
segmentos/15.27s; SPEAKER_02: 12 segmentos/53.63s). O pyannote já
convergia para 3 falantes sozinho dentro do range default; forçar o número
exato não mudou a atribuição. O problema não é o pipeline errar a
CONTAGEM de falantes, é errar QUEM fala em cada trecho.

**Overlap detection já ativo:** inspecionado o pipeline instanciado —
`embedding_exclude_overlap = True` (default), ou seja, a mitigação padrão
para fala sobreposta na extração de embedding de clustering já estava
ligada. Parâmetros de clustering default: VBx `threshold=0.6`, `Fa=0.07`,
`Fb=0.8`; `segmentation.min_duration_off=0.0` — não ajustados (fora do
escopo aprovado para esta rodada).

**Achado auxiliar:** só 1 dos 3 clusters teve mais de 1 segmento válido
(≥1.5s) disponível para gerar o embedding de identificação biométrica —
`SPEAKER_00` teve exatamente 1 candidato (1.98s), `SPEAKER_01` teve
exatamente 1 candidato (12.21s), `SPEAKER_02` teve 5. Como
`_remover_outliers` só age com ≥3 embeddings, nem `SPEAKER_00` nem
`SPEAKER_01` passaram por filtragem de outlier — mas isso é consequência
da diarização já ter misturado/fragmentado os falantes, não a causa raiz.

**Avaliação:** os dados apontam para uma limitação estrutural do modelo de
diarização diante de áudio de campo distante, ruidoso e com fala rápida
sobreposta — cenário estruturalmente mais adverso que os testes anteriores
(voz próxima, pouca sobreposição, silêncio de fundo), não um bug de
configuração corrigível trocando threshold/min-max. Não foi testado:
calibração fina de `clustering.threshold`/`Fa`/`Fb` do VBx, nem
pré-processamento (redução de ruído, normalização de volume) antes da
diarização — ambos ficaram fora do escopo desta investigação, por decisão
do usuário.

**Status:** aberta, investigação encerrada por ora sem correção aplicada.
Nenhuma mudança de comportamento foi feita — só diagnóstico. Próximo passo
(quando retomado) provavelmente exige mais dados de reuniões reais com
esse perfil de gravação (distante/ruidosa) antes de decidir entre
calibração de clustering, orientação de captura (aproximar o dispositivo)
ou aceitar a limitação como conhecida.

## Resolvida — `expected_speaker_count` do job nunca virava `num_speakers` exato na diarização

**Onde:** `app/services/pipeline_facade.py` (chamada a
`diarization_service.diarizar`).

**O quê:** `diarizar()` suporta `exact_speaker_count: bool = False` —
quando `True` e `expected_speaker_count` está presente, usa
`pipeline(audio_input, num_speakers=expected_speaker_count)` (contagem
exata) em vez do range `min_speakers`/`max_speakers`. Mas
`pipeline_facade.executar` chama `diarization_service.diarizar(audio_path,
transcricao, expected_speaker_count=job.expected_speaker_count)` sem
passar `exact_speaker_count=True` — então mesmo quando o app envia
`expected_speaker_count` no upload, ele hoje só vira **teto**
(`max_speakers`), nunca contagem exata. O parâmetro exato existe no
serviço mas está inacessível pelo caminho real do pipeline.

**Como foi encontrado:** durante a investigação da limitação de
diarização acima (2026-08-16), ao reproduzir manualmente
`diarizar(..., exact_speaker_count=True)` para o experimento com
`num_speakers=3`.

**Risco:** baixo — hoje o app Flutter ainda não coleta
`expected_speaker_count` na UI (fica `null` na prática), então o bug não
afeta nenhum fluxo em produção agora. Passa a importar quando essa coleta
for implementada no app.

**Correção (aplicada em 2026-09-06):** `pipeline_facade.executar` passa
`exact_speaker_count=True` na chamada a `diarization_service.diarizar`. Não
foi preciso condicionar ao valor: `diarizar()` já ignora o pedido de exatidão
quando `expected_speaker_count` é `None` e cai no range `min`/`max` de
`Settings` — que é o caminho de hoje, já que o app ainda não coleta o campo.

**O que faltava não era o código do serviço, e sim um teste no caminho real.**
O nível do serviço já cobria as duas ramificações
(`test_diarizar_usa_num_speakers_exato_so_quando_solicitado` e
`test_diarizar_usa_expected_speaker_count_como_max_speakers_pista`); o que não
existia era um teste do facade verificando o que ele de fato repassa — e é
exatamente aí que o parâmetro se perdia. Foram acrescentados dois em
`tests/test_pipeline_facade.py`, um para cada caso (com contagem e sem).

**Status:** resolvida. Sem efeito observável hoje, pelo motivo de risco acima:
fecha a inconsistência para quando o app passar a coletar o campo.

## Resolvida — Job fica congelado num estado intermediário para sempre se o servidor reiniciar durante o processamento (efeito colateral conhecido da persistência em banco)

**Onde:** `app/repositories/job_repository.py` (persistência em SQLite,
substituiu o dict em memória) + `app/services/job_executor.py` (execução
segue in-process, numa thread por job).

**O quê:** a migração de `job_repository` para SQLite (ver
`docs/BACKEND_ARCHITECTURE.md`) resolve a perda total de estado no
restart — antes, todo job em andamento simplesmente desaparecia. Mas só o
**registro** passou a sobreviver; a **execução** continua não-resiliente.
`InProcessJobExecutor` roda o pipeline numa thread do processo da API, sem
nenhum mecanismo de "quem estava processando o quê" sobrevivendo ao
processo. Se o servidor reiniciar enquanto um job está em qualquer estágio
não-terminal (`transcribing`, `diarizing`, `identifying`, `summarizing`,
`extracting`), a thread morre junto com o processo antigo — e nada no
processo novo sabe que precisa retomar, reenfileirar ou marcar erro nesse
job. O registro fica congelado no último estado alcançado antes do
restart, **indefinidamente**: um cliente fazendo polling em `/status`
nunca vai ver `done` nem `error` para esse job específico, só o mesmo
estado intermediário repetido para sempre.

**Validado empiricamente (teste manual da Fase 2 deste item):** upload
real, `kill -9` do processo com o job em `transcribing`, novo processo
apontando para o mesmo `STORAGE_ROOT`/banco — `GET /status/{job_id}`
devolveu o job intacto, mas congelado no último estado alcançado
(`extracting`, no caso testado), sem qualquer sinal de progresso ou erro
daí em diante.

**Por que não foi corrigido agora:** está fora do escopo deste item
(substituir a persistência em memória por uma real — objetivo cumprido).
Resolver de verdade — detectar jobs "órfãos" após um restart e marcá-los
como erro, ou retomar/reprocessar via workers que sobrevivem
independentemente do processo da API — é o objetivo do próximo item do
roadmap (fila real com Celery/Redis, execução resiliente). Implementar
aqui seria antecipar esse item sem a infraestrutura que o sustenta.

**Risco:** qualquer job em andamento no exato momento de um restart/deploy
em produção fica preso assim — o app cliente ficaria fazendo polling
indefinidamente num job que nunca termina, sem sinalização de erro.
Aceitável como comportamento transitório desta fase (o objetivo aqui era
parar de perder o *registro* do job, não garantir resiliência de
*execução*), mas não deve ser esquecido: todo restart em produção antes do
item 2 do roadmap corre esse risco.

**Status:** aberta, comportamento esperado e documentado — não bloqueia
esta fase, mas fica pendente até a fila real/execução resiliente (item 2
do roadmap) resolver de fato.

**Atualização — resolvida pelo item 2 (fila real com worker dedicado):**
`InProcessJobExecutor` foi removido. `/upload` não dispara mais
processamento nenhum diretamente — só grava o job (`queued`) no banco.
Quem processa é `app/worker.py`, um **processo separado** da API,
consumindo a fila via `JobRepository.next_queued()`. No boot, o worker
chama `JobRepository.requeue_orfaos()`: qualquer job num estágio
não-terminal só pode ter sido deixado por uma instância anterior do
próprio worker que morreu no meio do processamento — é reenfileirado
automaticamente (volta a `queued`), reprocessado do zero (seguro, já que
`pipeline_facade` não faz checkpoint parcial).

Proteção adicional contra "job veneno" (um job que sistematicamente
derruba o worker, ex.: um bug acionado por um áudio específico): coluna
`attempts` em `jobs`, incrementada a cada vez que o job é encontrado
órfão; excede `WORKER_MAX_ATTEMPTS_BEFORE_ERROR` (default 3) → vai direto
para `error` (`WORKER_MAX_TENTATIVAS_EXCEDIDO`) em vez de reenfileirar
para sempre.

**Validado empiricamente (teste manual do item 2):** upload real com
worker rodando; `kill -9` no worker com o job em `extracting`; novo
worker aponta pro mesmo banco, loga `"1 job(s) órfão(s) ... tratado(s)"`,
reenfileira e reprocessa do zero — job chega a `done`, com `attempts=1`
preservado (evidência de que passou pela recuperação). API derrubada no
meio do processamento não afeta o worker (processos independentes).

Tecnologia: fila no próprio SQLite (reaproveita o banco do item 1), não
Celery/Redis — decisão deliberada, ver `docs/BACKEND_ARCHITECTURE.md`
§3.8/§11 para o raciocínio completo (pipeline GPU-bound, um único worker
dedicado por servidor simplifica o problema o suficiente para não
justificar um broker externo). Teto conhecido: não escala entre máquinas
diferentes (SQLite não é seguro em filesystem compartilhado) — migraria
para Postgres ou um broker real se isso um dia for necessário.

**Status final:** resolvida. Job não fica mais congelado indefinidamente
em nenhum cenário testado (restart da API, crash do worker, job veneno).

## Resolvida — `STORAGE_ROOT` relativo dependia do cwd do processo, arriscando divergência silenciosa entre API e worker

**Onde:** `app/config.py` (`Settings.storage_root`, `SettingsConfigDict.env_file`).

**O quê:** `STORAGE_ROOT` (default `./storage`) era lido como string crua,
sem nunca ser resolvido para caminho absoluto — quem consumia
(`Path(get_settings().storage_root)`, em `app/api/participants.py`,
`app/services/voice_service.py`, `app/services/job_runner.py`) construía
um `Path` relativo, que `pathlib`/SQLAlchemy só resolvem contra
`os.getcwd()` no momento real do I/O, não na criação do objeto. Na
prática, cada processo fixava sua resolução no cwd que tinha *quando foi
iniciado*.

**Por que ficou mais urgente depois do item 2 (fila real com worker
dedicado):** antes, só a API tocava o storage — um cwd "errado" era
inofensivo, só existia um processo pra importar. Desde o worker dedicado
(`app/worker.py`, processo separado), API e worker precisam concordar
sobre onde o storage está fisicamente. Se um dos dois iniciasse de um cwd
diferente (erro de configuração no systemd, alguém rodando um dos dois
manualmente de outra pasta), os dois passariam a operar sobre diretórios
físicos diferentes — silenciosamente, sem erro, só arquivos "sumindo" da
perspectiva de um processo e não do outro. O `DATABASE_URL` default
(`sqlite:///<STORAGE_ROOT>/jobs.db`) sofreria o mesmo problema, por
derivar de `STORAGE_ROOT`.

**Correção:** `field_validator` em `storage_root` (`app/config.py`) —
valor relativo é ancorado em `_PROJECT_ROOT`
(`Path(__file__).resolve().parent.parent`, fixo, nunca o cwd do
processo); valor já absoluto passa direto, sem normalizar (não mexe em
symlink de quem já configura caminho absoluto de propósito, ex.:
produção). `database_url_efetivo` herdou a correção de graça, por
derivar de `storage_root` já resolvido.

**Achado durante a verificação manual deste item, incluído na mesma
correção:** `env_file=".env"` do `SettingsConfigDict` tinha exatamente a
mesma fragilidade — testado na prática, rodando a partir de `/tmp`,
`HF_TOKEN` voltava vazio (`''`) em vez do valor real, silenciosamente, sem
erro. Potencialmente pior que o problema original: se API e worker
divergissem de cwd, um deles poderia subir com **todas** as configs em
default, não só o storage — incluindo `JWT_SECRET_KEY` vazio, quebrando
autenticação só na hora de assinar/validar um token. Corrigido com o
mesmo padrão (`env_file=str(_PROJECT_ROOT / ".env")`).

**Defesa em profundidade:** mesmo com a causa raiz corrigida, API
(`app/main.py`, hook `lifespan`) e worker (`app/worker.py`, início de
`main()`) logam `STORAGE_ROOT`/`DATABASE_URL` absolutos resolvidos na
subida, mesmo formato de linha — um operador consegue notar visualmente
se os dois processos alguma vez divergirem, mesmo por uma causa nova,
ainda não prevista aqui.

**Validado:** `tests/test_config.py` (6 casos) — relativo resolve pro
mesmo absoluto trocando o cwd de fato via `monkeypatch.chdir`; absoluto
passa direto sem normalizar (`..` no meio do caminho preservado
literalmente); `env_file` é absoluto e não muda com o cwd. Verificação
manual adicional: `Settings()` instanciado com cwd em `/tmp` resolveu
`storage_root` para a raiz do repo (não `/tmp/storage`) e carregou
`HF_TOKEN` do `.env` real corretamente.

**Status:** resolvida. Ver `docs/BACKEND_ARCHITECTURE.md` §9 e §11 (item
4) para o detalhe completo.
