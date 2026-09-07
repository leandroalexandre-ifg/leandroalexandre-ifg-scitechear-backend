# Roteiro dos testes que faltam

**Contexto:** o roteiro combinado (passos 1 a 7) passou em 07/09/2026 — ver
`docs/E2E_APP_2026-09-07.md`. Restaram três itens, todos **fora** daquele
roteiro. Nenhum é bloqueante; estão em ordem de valor.

**Antes de qualquer um deles**, leia `docs/TESTE_CONJUNTO_NUMBERS.md`, em
especial a **§1b**: estar na rede do IFG não torna o servidor alcançável, o
túnel SSH continua necessário. O que muda lá é só a VPN deixar de ser precisa.

---

## Pré-voo (sempre)

No servidor:

```bash
cd /data/projects/leandro/leandroalexandre-ifg-scitechear-backend
systemctl --user is-active scitechear-api scitechear-worker ollama   # active x3
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
.venv/bin/python -m scripts.smoke_contrato                           # 21 OK, 0 falhas
```

Na máquina de dev: túnel, `adb reverse`, e `curl http://127.0.0.1:8000/health`
respondendo **antes** de abrir o app.

Deixe `journalctl --user -u scitechear-api -u scitechear-worker -f` aberto numa
sessão SSH separada. É onde está o que a tela não mostra.

---

## Teste A — reunião longa

**O que se quer saber:** como o pipeline se comporta com uma transcrição
grande. O `extracting` (Ollama) foi 48% do tempo numa reunião de 45s e escala
com o tamanho da transcrição, não com a duração do áudio — é a fatia que
menos conhecemos.

**Como fazer:** gravar uma reunião de **mais de 10 minutos** pelo app, de
preferência com duas pessoas (para a diarização ter trabalho real), e enviar.

**O que anotar:**

- o `job_id`;
- o tempo total, e o tempo por estágio. Não precisa cronometrar — depois do
  `done`, no servidor:

```bash
.venv/bin/python -c "
from app.repositories.job_repository import get_job_repository
r = get_job_repository(); jid = 'COLE_O_JOB_ID_AQUI'
print(r.stage_durations(jid))
for s, t in r.get(jid).status_history: print(t.isoformat(), s.value)"
```

- se o WebSocket sobreviveu ao processamento inteiro ou se o app caiu no
  polling (aparece no journal: `GET /status/...` durante o processamento);
- se a identificação continuou boa com mais fala. Na reunião de 45s deu
  `confidence` 0,889 com uma amostra só.

**Referência:** 45,3s de áudio → 16,2s de processamento (0,36× o tempo real).
Se a proporção se mantiver, 10 min dariam ~3,6 min. **Se destoar muito disso,
é o achado** — provavelmente no `extracting`.

**Cuidado:** a GPU é compartilhada e não há fila. Confira `nvidia-smi` antes
de gravar 10 minutos, não depois.

---

## Teste B — reinstalar o app (o passo 8)

**O que se quer saber:** se `GET /participants` faz o que foi escrito para
fazer. É o código mais novo dos dois lados e o único que ainda não foi visto
funcionando no cenário para o qual existe.

**Por que importa:** o `participant_id` é gerado pelo app e vive só no
armazenamento local dele. Sem esta rota, desinstalar o app órfã o conjunto
inteiro de perfis de voz da conta — gravações de voz de pessoas reais que
ficam no servidor invisíveis e inapagáveis, porque não há como listá-las.

**Como fazer:**

1. Com a conta A logada e ao menos um participante com voz cadastrada,
   **desinstale o app** (não só limpe os dados — desinstale).
2. Reinstale e entre com a **mesma conta A**.
3. Abra a tela de participantes.

**O que tem que acontecer:** os participantes reaparecem sozinhos, **com a voz
já cadastrada**, sem nada para regravar.

**O que confirma no servidor:** uma chamada a `GET /participants` logo após o
login, e **nenhum** `POST /participants/.../voice-samples` depois — se
aparecer um upload de amostra, o app recadastrou em vez de recuperar, e o
perfil antigo virou órfão.

**Custo se falhar:** o cadastro volta vazio e basta recadastrar. Não perde
nada.

---

## Teste C — migração do histórico para `/meetings`

**Este é trabalho do app, não um teste.** O backend está pronto desde
07/09/2026: `GET /meetings` com `participants` e `error`, `PATCH` para
renomear e `DELETE` para remover. Contrato na seção "Histórico editável" de
`docs/BACKEND_ARCHITECTURE.md`.

Quando o app migrar, três coisas mudam de comportamento na tela e valem teste
manual:

| O quê | O que observar |
|---|---|
| **Remoção** | Agora apaga o áudio e o resultado **no servidor**, irreversível e sem lixeira. O diálogo de confirmação precisa dizer isso — hoje ele diz "removida do seu histórico local". |
| **409 no `DELETE`** | Só aparece com o job em processamento. A reunião deve continuar na lista, com aviso de que precisa terminar antes. |
| **Paginação** | `GET /meetings` devolve 50 por padrão (máximo 200) e **trunca em silêncio**. Com mais de 50 reuniões, sem paginação de verdade, as antigas somem sem erro. |

Para checar no servidor o que a remoção fez:

```bash
ls /data/projects/leandro/scitechear/storage/jobs/ | wc -l   # deve cair de 1
```

---

## Depois dos três

O que sobra são os itens que dependem de decisão, não de teste:

- **TLS ponta a ponta** — a tela nunca viu HTTPS. Exige a CA interna na build
  do app (`deploy/scitechear-root-ca.crt`) e o SNI `10.4.254.201`. Ver
  `docs/TLS.md`.
- **API alcançável na rede do IFG** — depende do admin (regra de `ufw`,
  reserva de DHCP ou registro DNS) e não deveria acontecer sem o TLS acima.
- **Revalidar o threshold de biometria com mais vozes humanas.** A medição de
  07/09 (0,889 com uma amostra) é de um falante só; a calibração de 0,75
  continua baseada em TTS. Ver `docs/PENDENCIAS.md`.
