# AS-Norm com cohort por usuário — medição (22/09/2026)

**Resumo:** com o cohort vindo do banco inteiro do usuário e esse banco
crescido para 8 perfis, os falsos positivos grandma/grandpa **somem**, e somem
pelo próprio score normalizado, sem depender do piso bruto. **Reed/Eddy não
se resolve:** para o ECAPA, neste fixture, as duas vozes são praticamente a
mesma. Sem Reed cadastrado, Reed passa como Eddy. Com Reed cadastrado, as
amostras genuínas de Eddy passam a ser rejeitadas. É um indício antecipado
com TTS, não uma calibração. `ENABLE_VOICE_ASNORM` continua `false` em todo
ambiente.

Branch: `feat/voice-asnorm-cohort-usuario`, a partir de `main` em `b43bd90`.
Reimplementada do zero: nada da `feat/voice-asnorm-decision` foi mesclado nem
copiado.

## O que mudou em relação à primeira tentativa

| | 1ª tentativa (`feat/voice-asnorm-decision`) | Esta |
|---|---|---|
| Cohort | os outros participantes da reunião | **todos os perfis do usuário** dono da reunião, menos o candidato |
| Normalização | z-score só do lado do teste | **S-norm simétrico**: média dos z-scores do lado do teste (áudio × cohort) e do lado do cadastro (perfil × cohort) |
| Banco pequeno | fallback só com < 2 impostores; com 2, normalizava | **abaixo de `VOICE_ASNORM_MIN_COHORT` (8), a decisão inteira volta ao threshold fixo** |
| `confidence` | score bruto | score bruto (inalterado: é o que o contrato já expõe) |

Os candidatos continuam sendo só os participantes da reunião com perfil. O
banco do usuário entra **apenas** como cohort, e nunca como candidato.
Ninguém fora da reunião pode ser atribuído a um segmento.

Onde está:

- `app/services/voice_service.py`: `asnorm_score` (fórmula pura),
  `_identificar_asnorm` (decisão: piso bruto, limiar normalizado e margem
  normalizada) e `identificar_speaker(embedding, banco, cohort=None)`.
- `app/services/pipeline_facade.py`: `_carregar_cohort(user_id)` lê todos os
  perfis via `VoiceRepository.list_profiles`. Só é chamado com a flag ligada.
  Com a flag desligada, nada muda no caminho de produção.
- `app/config.py` e `.env.example`: `ENABLE_VOICE_ASNORM=false`,
  `VOICE_ASNORM_MIN_COHORT=8`, `VOICE_ASNORM_TOP_K=10`,
  `VOICE_ASNORM_THRESHOLD=3.0`, `VOICE_ASNORM_MIN_MARGIN=1.0` e
  `VOICE_ASNORM_MIN_RAW_SCORE=0.40`. Os três limiares **não estão
  calibrados**. São os valores usados na medição abaixo.

## Como foi medido

`docs/repro/asnorm-cohort/medir.py` usa só o fixture
`tests/fixtures/voice_identification_real_embeddings.json`: 3 cadastrados
(luciana, joana, eddy) com 5 amostras genuínas cada, 6 impostores
não-outlier e Reed. O script não lê áudio, não usa GPU e não acessa o
storage. Roda em ~4 s. A saída completa está em `medicao.json`.

Os candidatos são sempre os 3 cadastrados, no papel dos participantes da
reunião. O que varia é o cohort:

- **reunião**: os outros participantes (2 pontos por candidato).
- **usuário**: todos os perfis do usuário. **No fixture isso é o mesmo
  conjunto que "reunião"**, porque o usuário só tem os 3. O cenário foi
  medido assim mesmo, para que isso fique registrado e não apenas inferido.
- **crescido**: as 7 identidades de impostor do fixture entram no banco do
  usuário "como se estivessem cadastradas", fora da reunião. A identidade sob
  teste é **sempre retirada** do cohort (leave-one-out), porque o caso
  difícil é o de quem não tem perfil nenhum. O script varre **todos** os
  subconjuntos das 7 identidades (de 0 a 6 extras, com cohort de 2 a 8) e
  top-k 3, 5 e "todos".

## Resultados

Falsos positivos (FP) e falsos negativos (FN), com os limiares da tabela
acima:

| Cenário | Cohort | FP | FN |
|---|---|---|---|
| Threshold fixo 0.75 (produção) | — | Reed | — |
| AS-Norm, cohort da reunião | 2 | **grandma, grandpa, Reed** | — |
| AS-Norm, cohort do usuário (fixture) | 2 | **grandma, grandpa, Reed** (idêntico) | — |
| Idem, com `MIN_COHORT=8` (config. real) | 2 → cai no threshold fixo | Reed | — |
| Crescido, top-todos, 2 extras | 4 | Reed (10 dos 15 subconj. sem Reed) | Eddy |
| Crescido, top-todos, 6 extras | **8** | **Reed** | **Eddy, quando Reed está no banco** |
| Crescido, top-3, de 3 a 5 extras | 5-7 | grandpa + Reed | Eddy |

Scores normalizados com cohort de 8 e top-todos (mínimo e máximo entre os
subconjuntos):

| Teste | Normalizado | Bruto |
|---|---|---|
| Genuínas de Joana | 4.98 – 5.69 | — |
| Genuínas de Luciana | 5.34 – 6.53 | — |
| Genuínas de Eddy, **sem** Reed no banco | 3.27 – 3.42 | — |
| Genuínas de Eddy, **com** Reed no banco | **1.94 – 2.23** | — |
| Reed → Eddy (sem perfil próprio) | **3.18** | 0.9555 |
| grandpa → Eddy | 1.10 | 0.6214 |
| rocko → Eddy | 0.74 | 0.3950 |
| grandma → Eddy | 0.07 | 0.4126 |
| demais impostores | ≤ 0.07 | ≤ 0.39 |

### O que isso diz

1. **Cohort da reunião e cohort do usuário são a mesma coisa no banco atual.**
   A diferença entre as duas variantes só aparece quando o usuário tem mais
   perfis do que os que estão na reunião. Com o banco do fixture, as duas
   reproduzem os três FPs da primeira tentativa (scores normalizados de 12 a 92 contra
   2 pontos). Portanto o problema original era o **tamanho** do cohort, e
   não a origem.

2. **O mínimo de cohort é o que torna seguro ligar a flag cedo.** Com
   `MIN_COHORT=8`, um banco de 3 perfis cai no threshold fixo e fica
   exatamente como a produção hoje. Isso está travado em teste.

3. **grandma/grandpa somem com o banco crescido.** Com top-todos, somem a
   partir de 2 extras (cohort de 4) e não voltam. Com cohort de 8, o maior
   impostor não-Reed fica em 1.10 normalizado, contra um piso genuíno de
   ~5 para Joana e Luciana. A folga é grande, e o **próprio normalizado**
   rejeita, mesmo com o piso bruto zerado (também travado em teste). Na
   primeira tentativa, quem segurava rocko/sandy/flo/shelley era o piso bruto
   de 0.40, e não o AS-Norm.

4. **Top-3 é instável com cohorts deste tamanho.** grandpa volta a ser FP em
   cohorts de 5 a 7 (em 7 dos 20 subconjuntos de 3 extras sem grandpa).
   Com menos de ~10 impostores, normalizar contra os 3 mais parecidos é quase tão frágil
   quanto o cohort de 2. Por isso o default é `VOICE_ASNORM_TOP_K=10`, que
   nessa escala significa "todos".

5. **Reed/Eddy não é um problema de normalização.** O cosseno bruto
   Reed × perfil de Eddy (0.9555) é **maior** que o de todas as 5 genuínas
   de Eddy (0.917–0.954). Normalizar desloca os dois juntos:
   - sem Reed no banco, Reed (3.18) e as genuínas de Eddy (3.27–3.42)
     ficam a 0.09 de distância. Nenhum limiar honesto separa isso, e ajustar
     o limiar para 3.2 seria fazer overfit num único par de vozes TTS;
   - com Reed no banco, o perfil de Eddy fica "parecido demais com alguém do
     cohort", e todas as genuínas de Eddy caem para ~2. O FP vira FN. Pela
     prioridade assimétrica já definida (falso negativo é preferível a falso
     positivo), essa troca é aceitável, mas não é uma solução: só acontece se
     a pessoa parecida **tiver perfil cadastrado**.

   O cenário `crescido_com_proprio_perfil` do `medicao.json` (impostor sob
   teste com perfil no banco) dá 0 FP. Mas no fixture o perfil e o áudio de
   teste de um impostor são **o mesmo vetor**, então esse número é um limite
   otimista e não entra nas conclusões.

## Ressalvas

- **TTS, não voz humana.** As vozes do fixture vêm do `say` do macOS. Os
  scores genuínos humanos medidos até agora (0.73–0.89) ficam bem abaixo dos
  de TTS (0.92–0.95), e os impostores humanos ainda não foram medidos. As
  distâncias acima **não** se transferem para voz real.
- **O "banco crescido" reusa as identidades do próprio teste.** Não existe
  um cohort realmente independente: as 7 identidades extras são as mesmas
  que servem de impostores, retiradas uma de cada vez. Com 7 identidades,
  isso é o máximo que o fixture permite.
- **1 embedding por impostor.** Não há variação intra-locutor do lado dos
  impostores.
- **Os limiares não foram calibrados.** 3.0 / 1.0 / 0.40 foram fixados antes
  da medição e não foram ajustados depois dela. Calibrar com 22 pontos de TTS
  seria só ajustar ruído.

## Critério para ligar a flag (inalterado na essência)

Continua **desligada em todo ambiente**. Para considerar ligá-la:

1. um banco real com 8-10 perfis de **voz humana** de pessoas distintas;
2. medição de impostor humano real (pessoa A contra o perfil de B), que
   ainda não existe;
3. repetir `medir.py` sobre esses embeddings. Basta trocar a fonte, porque o
   script só usa funções puras do `voice_service`.

O que esta medição adiciona ao critério antigo: o limite de 8-10 perfis é
plausível. Os FPs "fáceis" (grandma/grandpa) desaparecem já com cohort de
4-8. E fica registrado de antemão que **AS-Norm não resolve pares quase
idênticos no espaço do ECAPA**. Esse risco residual é do modelo de
embedding, não do método de decisão.
