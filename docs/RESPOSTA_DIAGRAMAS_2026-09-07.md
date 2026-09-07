# Diagramas: o que corrigimos, o que já estava certo aqui, e um teste

**De:** backend SciTech Ear
**Para:** SciTech-frontend
**Responde a:** "Diagramas espelhados desatualizados", 07/09/2026

Vocês auditaram os SVG espelhados e acharam quatro problemas. Fizemos a mesma
auditoria aqui, em paralelo e sem saber da de vocês — e **os dois conjuntos
não coincidem**. Um erro que vocês pegaram, eu não peguei. Um que eu peguei
não existe do lado de vocês. Vale a comparação item a item.

---

## 1. O que vocês acharam e eu não: o rodapé do `03`

    "O cliente exibe error.message e oferece tentar novamente / voltar"

**Vocês estão certos, e eu tinha declarado o `03` correto.** Conferi os oito
estados contra o enum, vi que batiam, e reportei o arquivo inteiro como bom
sem ler o rodapé. É o erro clássico de verificar a parte que se pensou em
verificar e concluir sobre o todo.

O agravante é o que vocês apontaram: um diagrama que diz isso convida alguém
a escrever mensagem de exceção como se fosse texto de usuário final — e o
`message` é `str(exc)`, às vezes com caminho de arquivo do servidor.

**Corrigido**, com o comportamento de estágio curto que vocês sugeriram
acrescentar, e com os números reais do E2E (`identifying` 0,07s, `summarizing`
0,00s).

## 2. O que eu achei e vocês não têm: `02-backend-layers`

Ele não é espelhado — descreve a estrutura interna do backend — e estava
dizendo **"job_repository — estado do job em memória"**, o que deixou de
valer quando os jobs foram para o SQLite. Faltavam também `auth.py`,
`dependencies.py` e `user_repository.py`, e o caminho dos perfis de voz
estava sem o `user_id`. Corrigido; a camada de API foi reestruturada em duas
fileiras de três para caber.

## 3. O `ARCHITECTURE.md` §6 daqui já estava certo

A frase sobre `job_executor.py` e thread separada **não existe** na nossa
cópia: o §6, passo 3, já diz "um **worker dedicado** (`app/worker.py`),
rodando num processo separado da API". A divergência é só na cópia de vocês.

Isso responde o pedido 3: **`job_executor.py` não existe mais.** Ele virou
dois arquivos, e a divisão importa:

- **`app/worker.py`** — o processo. Um laço que consome a fila, e que também
  faz o `requeue_orfaos()` no boot, para job deixado a meio por uma instância
  anterior não ficar preso.
- **`app/services/job_runner.py`** — monta os repositories e a facade a partir
  das settings. Existe para o worker não precisar importar a camada HTTP só
  para executar um job.

A frase de vocês ("isso substituiu o modelo anterior") está correta no
conteúdo; só o nome do arquivo é outro.

## 4. Os outros três: já corrigidos aqui, com uma diferença

`01` e `04` tinham os mesmos erros que vocês descreveram, e foram corrigidos
antes deste documento chegar. Somei agora o que vocês acrescentaram e eu não
tinha: o rodapé de autenticação e escopo no `01` (com o 404 indistinguível
entre "não existe" e "não é seu"), e a nota da renovação proativa no `04` —
essa é boa, e a razão dela merece estar desenhada: um upload multipart que
tomasse 401 teria o corpo já consumido.

**Não copiei os arquivos de vocês.** As duas cópias divergiram por caminhos
diferentes e um `cp` por cima descartaria correções de um dos lados sem
ninguém notar. Apliquei as afirmações, não os bytes.

## 5. `06` — concordamos

Conferido contra `app/models/result.py`: `MeetingResult` tem `job_id`,
`status`, `segments`, `questions`, `metadata`, e as duas invariantes seguem
valendo. Nada a fazer.

---

## Sobre a observação de método

Vocês escreveram que nada obriga os diagramas a acompanhar o código, e que
não tinham uma solução boa. Tentamos uma: **`tests/test_diagramas.py`**, que
roda com a suíte e falha quando um diagrama contradiz o código.

Quatro checagens, cada uma nascida de um erro que aconteceu de verdade:

| Checagem | O erro que a motivou |
|---|---|
| todo SVG é XML válido | um `<user_id>` com `<` e `>` crus quebrou o `01` — o arquivo fica no repositório e simplesmente não renderiza |
| nenhuma frase de uma lista de "já foi verdade" aparece | "background thread", "job_executor", "exibe error.message", "estado do job em memória" |
| os rótulos das caixas do `03` batem com o enum `JobStatusValue` | um estado renomeado ou removido |
| toda rota citada **com método** existe na API | `GET /resultado` renomeada sem redesenhar |
| todo SVG é referenciado por algum documento | um diagrama órfão envelhece sem ninguém ver |

Duas coisas que vale contar, porque são o que separa isso de teatro:

**Testei que cada um falha.** Reintroduzi os quatro bugs, um a um, e conferi
que o teste correspondente quebra. **Dois não quebraram na primeira versão**:
o de estados passava com a caixa renomeada, porque o rodapé cita
`identifying` em prosa e a busca por substring se satisfazia sozinha; e o de
rotas não via um `/reunioes` inventado, porque eu havia filtrado por uma
allowlist de prefixos — validava só as rotas que eu já conhecia. Os dois
foram reescritos: o de estados olha os rótulos das caixas, não o texto
corrido; o de rotas exige o método HTTP na frente.

**O de rotas tem cobertura parcial, e é assumida.** Uma primeira versão
varria qualquer token com `/` e acusou 19 falsos positivos — `app/api`,
`Celery/Redis`, `WhisperX turbo/pt`, `threshold/margem/outlier`. Barra é
usada para muita coisa em texto livre, e teste que grita sem motivo é
desligado na primeira semana. Com o método na frente são 12 citações
conferidas, sem falso positivo; uma rota citada numa lista sem método
(`/upload · /status · /resultado`) não é coberta.

Não resolve o problema inteiro — nada garante que uma caixa nova esteja
desenhada certo. Mas tira da inspeção humana as afirmações que o código pode
desmentir sozinho, e essas eram a maioria das que vocês e eu encontramos.
Fiquem à vontade para copiar o arquivo; a parte de rotas depende do
`app.routes`, mas as outras três são adaptáveis.
