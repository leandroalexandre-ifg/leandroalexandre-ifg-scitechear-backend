# SciTech Ear — Arquitetura do Backend

> Complementa o [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) (visão geral do
> sistema, com glossário — leia-o primeiro se ainda não leu). Este documento
> detalha o repositório `scitechear-backend`: cada camada, cada serviço, e
> o raciocínio por trás das decisões que moldaram essa estrutura.

## 1. Visão em camadas

![Arquitetura em camadas do backend](diagrams/02-backend-layers.svg)

O backend segue uma separação estrita de responsabilidades, organizada em
quatro camadas que só conversam em uma direção — de cima para baixo:

```
app/api          (HTTP: recebe requisições, valida entrada, devolve respostas)
     ↓
app/services      (lógica de domínio: o que o sistema realmente faz)
     ↓
app/repositories  (persistência: onde e como os dados são guardados)
     ↓
app/models        (contrato: a forma dos dados que trafegam entre tudo isso)
```

Essa separação existe por um motivo prático, não só estético: cada camada
pode ser testada e entendida isoladamente. Um teste de um serviço não
precisa subir um servidor HTTP; um teste de uma rota pode simular o
serviço sem rodar nenhum modelo de IA de verdade. `legacy/` e `prompts/`
ficam fora dessa cadeia — são material de apoio, não código executado em
produção (no caso de `legacy/`) ou configuração externa versionada (no
caso de `prompts/`).

## 2. `app/api` — a fronteira HTTP

Esta camada é deliberadamente "burra": ela recebe requisições, valida a
forma dos dados de entrada (usando os schemas Pydantic de `app/models`), e
delega todo o trabalho de verdade para `app/services`. Não há lógica de
negócio aqui — só validação e orquestração de chamadas.

| Arquivo | Rotas | O que faz | Por que é assim |
|---|---|---|---|
| `jobs.py` | `POST /upload`<br>`GET /status/{job_id}`<br>`GET /resultado/{job_id}`<br>`WS /ws/{job_id}` | Recebe o áudio e a lista de participantes; cria um job; expõe o estado atual; expõe o resultado final quando pronto. | O upload devolve `202 Accepted` imediatamente (não espera o processamento), porque uma transcrição real pode levar minutos — bloquear a requisição HTTP até terminar seria uma experiência ruim e arriscaria timeout. |
| `participants.py` | `POST /participants/{id}/voice-samples`<br>`GET /participants/{id}/voice-profile`<br>`DELETE /participants/{id}/voice-profile` | Cadastro, consulta e remoção do perfil de voz de um participante. | Separado de `jobs.py` porque o cadastro de voz tem um ciclo de vida independente das reuniões — uma pessoa se cadastra uma vez, participa de muitas reuniões depois. |
| `health.py` | `GET /health`<br>`GET /ready` | `/health` responde imediatamente, sem carregar nenhum modelo — serve para checagens de infraestrutura ("o processo está vivo?"). `/ready` verifica dependências reais: se o `HF_TOKEN` está configurado, se o Ollama está alcançável. | A distinção entre os dois evita um erro comum: um `/health` que "finge" prontidão quando na verdade uma dependência crítica está fora do ar. `/ready` existe justamente para não mentir sobre isso. |
| `main.py` | — | Bootstrap da aplicação FastAPI: registra os routers, configura CORS para desenvolvimento. | Ponto único de montagem da aplicação. |

## 3. `app/services` — onde a inteligência do sistema mora

Esta é a camada mais substancial do backend. Cada serviço tem uma
responsabilidade única e bem delimitada.

### 3.1. `transcription_service.py` — converter áudio em texto

Usa o WhisperX (modelo `turbo`, configurado para português) para
transcrever o áudio, com alinhamento temporal por palavra. É uma
adaptação direta do protótipo original em
`legacy/notebooks/transcricao.ipynb`, com uma diferença crucial: todo
código que dependia de Google Colab ou Google Drive foi removido — o
serviço lê e escreve arquivos locais, de forma portável para qualquer
ambiente Linux com GPU.

O resultado interno inclui informação em nível de palavra (`words`), mas
essa granularidade fica só como artefato interno do pipeline — não faz
parte do contrato canônico exposto ao cliente, que trabalha em nível de
segmento.

### 3.2. `diarization_service.py` — separar as vozes

Usa o pyannote (`pyannote/speaker-diarization-community-1`) para
identificar quantos falantes distintos existem no áudio e quando cada um
fala, produzindo clusters (`SPEAKER_00`, `SPEAKER_01`, …).

Dois detalhes técnicos valem registro porque não são óbvios e já geraram
retrabalho durante o desenvolvimento:

- **O áudio é lido via `soundfile` e passado ao pyannote como um
  dicionário `{"waveform": tensor, "sample_rate": sr}`, não como um
  caminho de arquivo.** A alternativa (passar o caminho como string) faz o
  pyannote tentar decodificar o áudio internamente via `torchcodec`, uma
  dependência frágil que exige uma versão específica de FFmpeg e
  configuração de ambiente que não é portável entre máquinas de
  desenvolvimento e servidores de produção. Carregar o áudio antes,
  seguindo o mesmo padrão já usado em `voice_service.py`, elimina essa
  dependência por completo.
- **Os limites de número de falantes são configuráveis, nunca fixos no
  código.** O protótipo original tinha `MIN_SPEAKERS=4` e `MAX_SPEAKERS=7`
  fixos — o que quebraria silenciosamente para uma reunião de duas
  pessoas. A versão integrada lê `DIARIZATION_MIN_SPEAKERS` e
  `DIARIZATION_MAX_SPEAKERS` do ambiente, e usa
  `expected_speaker_count` (vindo do app, quando informado) apenas como
  uma pista para o algoritmo — nunca como um valor forçado, a menos que
  explicitamente solicitado via `exact_speaker_count`.

### 3.3. `voice_service.py` — extrair e comparar embeddings de voz

Usa o SpeechBrain (modelo ECAPA-TDNN) para duas tarefas relacionadas mas
distintas:

- **Extração**: converter um trecho de áudio em um embedding — um vetor
  numérico que representa o timbre daquela voz.
- **Identificação**: comparar um embedding contra os embeddings
  cadastrados no `VoiceRepository`, decidindo se há uma correspondência
  suficientemente confiável.

O mesmo ponto de entrada de extração é usado tanto no cadastro (seção 3.4)
quanto na identificação durante o processamento de uma reunião — isso é
proposital, para garantir que os embeddings comparados sempre passaram
pelo mesmo pré-processamento, evitando incompatibilidades sutis entre um
embedding gerado no cadastro e outro gerado na hora de identificar.

A decisão sobre se um cluster corresponde a uma pessoa cadastrada depende
de três parâmetros calibráveis:

| Parâmetro | Papel |
|---|---|
| `VOICE_IDENTIFICATION_THRESHOLD` | Score mínimo de similaridade para aceitar uma correspondência. |
| `VOICE_MIN_MARGIN` | Diferença mínima entre o melhor e o segundo melhor candidato — evita aceitar uma identificação ambígua. |
| `VOICE_OUTLIER_THRESHOLD` | Usado para descartar trechos de áudio cujo embedding diverge demais dos demais trechos do mesmo cluster (provável ruído ou erro de diarização). |

Esses três valores são explicitamente tratados como experimentais e
calibráveis — não há garantia de que os valores atuais são os ideais para
todo tipo de áudio; eles existem no `.env` justamente para poderem ser
ajustados sem alterar código, à medida que mais dados reais de uso forem
observados.

### 3.4. `voice_enrollment_service.py` — cadastro de voz

Responsável por criar ou atualizar o perfil de voz de um participante. Um
detalhe importante de comportamento: **a cada nova amostra adicionada, o
embedding consolidado do participante é recalculado a partir de todas as
amostras salvas até então — nunca de forma incremental.** Isso é mais
custoso computacionalmente do que simplesmente atualizar uma média, mas é
mais robusto: evita que o embedding "derive" lentamente ao longo de várias
atualizações incrementais mal calculadas.

### 3.5. `voice_migration.py` — ponte com o banco de vozes legado

Um utilitário isolado, **não destrutivo**, para migrar o banco de vozes
antigo (indexado por nome, em `legacy/banco_vozes/`) para o formato novo
(indexado por `participant_id`, no `VoiceRepository`). Ele nunca apaga os
dados originais — só lê e recadastra.

### 3.6. `transcript_formatter.py` — a ponte entre dados e prompts

Este serviço converte os segmentos diarizados e identificados em linhas de
texto estáveis, formatadas para serem consumidas pelos prompts de LLM
(seção 5), e mantém internamente um mapa de "linha → segmento original".

Esse mapa é o que garante uma propriedade importante do sistema: **quando
uma pergunta é extraída pelo modelo de linguagem, sua identidade (quem
perguntou, em que momento) nunca é inferida a partir do que o próprio
modelo escreveu** — é recuperada de volta, com certeza, a partir do
segmento original, usando o número da linha que o modelo referenciou. Isso
evita um problema sutil e real: modelos de linguagem podem "alucinar" ou
formatar de forma inconsistente o nome de quem falou, então confiar nessa
informação vinda diretamente do texto gerado seria arriscado.

### 3.7. `question_service.py` — sumarização e extração de perguntas

Orquestra três (ou quatro, se o refinamento estiver ativado) chamadas
sequenciais ao Ollama, cada uma usando um prompt versionado em `prompts/`:

1. **Sumarização** — gera um resumo estruturado da reunião. Esse resumo
   não faz parte do contrato final exposto ao cliente; serve como
   contexto adicional para a etapa seguinte.
2. **Perguntas explícitas** — extrai, literalmente, toda sentença
   terminada em `?` na transcrição. O texto da pergunta nunca é reescrito
   ou corrigido pelo sistema — é copiado exatamente como está na
   transcrição original.
3. **Perguntas implícitas** — usando a transcrição e o resumo como
   entrada, o modelo infere perguntas que não foram literalmente
   formuladas, mas que decorrem logicamente do que foi discutido (por
   exemplo, uma decisão pendente mencionada de passagem).
4. **Refinamento (opcional, desativado por padrão)** — uma passada
   adicional que reformula e remove redundâncias das perguntas
   implícitas. Controlado por `ENABLE_IMPLICIT_REFINEMENT`.

### 3.8. `pipeline_facade.py` e `job_executor.py` — orquestração

`MeetingPipelineFacade` é o ponto único que conhece a ordem completa das 7
etapas e chama cada serviço na sequência correta, atualizando o estado do
job a cada transição. `job_executor.py` é a camada mais fina em torno
disso: hoje, executa o pipeline em uma thread de background por job — uma
solução simples, adequada ao volume da V1, mas desenhada com uma interface
que já comporta a substituição futura por uma fila real (Celery + Redis,
por exemplo) sem exigir mudanças nas rotas HTTP ou no `pipeline_facade.py`
em si.

## 4. `app/repositories` — onde os dados moram

Cada repositório abstrai uma forma de persistência, para que o resto do
sistema não precise saber os detalhes de como e onde os dados ficam
guardados fisicamente:

- **`job_repository.py`** — mantém o estado de todos os jobs em memória,
  no processo atual. Isso significa que reiniciar o servidor limpa esse
  estado (uma limitação conhecida e aceitável para a V1, que roda como
  processo único).
- **`result_repository.py`** — persiste o resultado final de cada job como
  um arquivo JSON, permitindo que `GET /resultado/{job_id}` seja servido
  sem reprocessar nada.
- **`storage_repository.py`** — organiza os artefatos de cada job (o áudio
  recebido, e outros arquivos intermediários) em `storage/jobs/<job_id>/`.
- **`voice_repository.py`** — organiza os perfis de voz em
  `storage/voices/<participant_id>/`, guardando o embedding consolidado e
  metadados (quantas amostras, quando foi atualizado pela última vez, qual
  versão do modelo gerou o embedding — importante para saber quais perfis
  precisam ser recalculados se o modelo de voz for trocado no futuro).

Nenhum desses repositórios depende de um provedor de nuvem — tudo é
armazenamento local em disco, o que mantém o backend portável e simples de
rodar em qualquer servidor Linux com GPU.

## 5. `app/models` — o contrato formal

Define, via schemas Pydantic, exatamente a forma dos dados que trafegam
entre as camadas e, principalmente, entre o backend e o cliente:
`participant.py`, `job.py` (com os 8 estados possíveis), e `result.py`
(`TranscriptSegment`, `Question`, `MeetingResult`, `ResultMetadata`). O
contrato completo, com exemplos, está documentado em
[`docs/ARCHITECTURE.md`](./ARCHITECTURE.md#9-contrato-de-dados-canônico).

## 6. `legacy/` — de onde este sistema veio

Antes de existir como um backend integrado, cada etapa do pipeline foi
prototipada e validada de forma independente, em notebooks e scripts
Python soltos. Esse material está preservado em `legacy/`, **nunca
executado como parte do sistema em produção** — serve como referência
histórica e como prova de que os algoritmos centrais (diarização,
biometria) foram validados antes da integração.

- **`notebooks/`** — `transcricao.ipynb`, `diarizacao.ipynb`, `llm.ipynb`.
  Escritos originalmente para rodar no Google Colab, com dependência de
  Google Drive para entrada e saída de arquivos — por isso não podem
  (nem devem) ser executados como parte do backend real.
- **`scripts/`** — `etapa2b_diarizacao.py`, `etapa3_biometria.py`,
  `cadastro_vozes.py`, `pipeline.py`: versões em script dos mesmos
  algoritmos, mais próximas da forma final, mas ainda usando o banco de
  vozes indexado por nome (em vez de `participant_id`) e caminhos de
  arquivo fixos.
- **`banco_vozes/`** — a estrutura do banco de vozes legado. Não contém
  dados reais neste repositório (áudios e embeddings não são versionados,
  por serem dados biométricos e por peso); existe só a estrutura de
  referência e a documentação de como o `voice_migration.py` pode
  trazer dados legados reais para o formato novo, se algum dia existirem.

## 7. `prompts/` — as instruções dadas ao modelo de linguagem

Prompts são tratados como um artefato de engenharia versionado, não como
texto solto embutido no código. Mudanças neles são revisadas com o mesmo
cuidado que mudanças em código — alterar um prompt pode mudar
silenciosamente o comportamento do sistema.

| Arquivo | Função | Nota |
|---|---|---|
| `explicit_questions_v4.json` | Extrai literalmente toda sentença terminada em `?`. | O prompt é deliberadamente rígido: não pede interpretação, só varredura textual. |
| `meeting_summary_v1.txt` | Gera o resumo estruturado usado como contexto interno. | Não é exposto ao cliente diretamente. |
| `implicit_questions_v3.txt` | Extrai perguntas implícitas, em formato JSON. | É a evolução do `v2` (preservado só como referência histórica), cuja única mudança foi o formato de saída — de texto livre para JSON — sem alterar os critérios semânticos de extração. |
| `implicit_refiner_v1.txt` | Refina e consolida as perguntas implícitas. | Desativado por padrão (`ENABLE_IMPLICIT_REFINEMENT=false`); existe para uso futuro. |

## 8. Pendências de calibração conhecidas

Nem todo comportamento observado durante o desenvolvimento é um bug de
código — alguns são resultado de limitações do modelo de linguagem usado,
e ficam registrados separadamente para acompanhamento, em vez de
misturados com decisões de arquitetura já fechadas. Ver
[`docs/PENDENCIAS.md`](./PENDENCIAS.md) para o registro vivo desses
achados — por exemplo, modelos menores do Ollama nem sempre respeitam à
risca o formato de saída pedido no prompt de perguntas explícitas,
comportamento que precisa ser reverificado com o modelo de produção antes
de ser considerado resolvido ou não.

## 9. Configuração e como rodar localmente

Todas as variáveis de ambiente relevantes estão documentadas em
`.env.example`, na raiz do repositório. As mais importantes do ponto de
vista arquitetural:

```env
HF_TOKEN=                          # obrigatório — o modelo do pyannote é "gated" no Hugging Face
STORAGE_ROOT=./storage
WHISPERX_MODEL=turbo
WHISPERX_LANGUAGE=pt
DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
DIARIZATION_MIN_SPEAKERS=1
DIARIZATION_MAX_SPEAKERS=10
VOICE_MODEL=speechbrain/spkrec-ecapa-voxceleb
VOICE_IDENTIFICATION_THRESHOLD=0.30
VOICE_MIN_MARGIN=0.05
VOICE_OUTLIER_THRESHOLD=0.45
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:14b
ENABLE_IMPLICIT_REFINEMENT=false
DEMO_MODE=false
```

Para desenvolvimento local:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencher HF_TOKEN
uvicorn app.main:app --reload
```

O servidor sobe em `http://0.0.0.0:8000` por padrão, o que é necessário
para ser alcançável por um emulador Android ou dispositivo físico na mesma
rede (não apenas por `localhost`).

## 10. Abordagem de testes

Os testes automatizados privilegiam **testes de contrato com fixtures**
sobre execução real de modelos pesados — rodar WhisperX, pyannote ou
SpeechBrain de verdade em cada execução da suíte de testes seria lento e
exigiria GPU. Em vez disso, os testes mockam essas etapas e verificam: a
forma dos dados trocados entre camadas, as transições de estado do job, o
comportamento correto diante de erros em cada etapa, e a fidelidade dos
schemas Pydantic ao contrato canônico. Validações com modelos reais são
feitas manualmente durante o desenvolvimento de cada funcionalidade, e
seus resultados ficam registrados nas notas de cada etapa de
implementação, mas não fazem parte da suíte automatizada de CI.

## 11. Escopo da V1 e próximos passos conhecidos

A V1 assume: um único processo backend (sem fila distribuída), execução em
um servidor Python convencional com GPU, sem autenticação real de usuários
ainda, e WebSocket de status como um recurso complementar ao polling
(não uma dependência crítica). Esses pontos são decisões conscientes de
escopo, não lacunas esquecidas — a interface de cada componente já foi
desenhada considerando essas evoluções futuras, para que não exijam
reescrever contratos já estabelecidos.
