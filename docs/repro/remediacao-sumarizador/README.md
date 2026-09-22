# repro — remediação do sumarizador (22/09/2026)

Artefatos brutos do Movimento 3, lidos em
[`../../COMPARATIVO_REMEDIACAO.md`](../../COMPARATIVO_REMEDIACAO.md).

| Arquivo | O que é |
|---|---|
| `remediacao.py` | O script que rodou. Reaproveita `segments` já gravados — nenhum áudio é reprocessado. Não escreve no storage de produção nem toca no `.env`. |
| `remediacao.json` | Saída completa: por job, as 2 sumarizações e as 4 extrações, com perguntas, durações, tamanho de prompt e resposta bruta do modelo. |
| `<job>_transcricao.txt` | Transcrição renderizada pelo `TranscriptFormatter`, como o LLM a recebeu. |
| `<job>_sumario_v1.txt` | Sumário do prompt v1 (baseline). |
| `<job>_sumario_v2.txt` | Sumário do prompt v2 (corrigido). |

Duas condições por job: **baseline** (sumário v1, filtro desligado) e
**corrigido** (sumário v2, filtro ligado). O baseline reproduz o comparativo
v4 × v6 de 22/09 número a número.

Teto declarado antes de rodar: 35 min. Consumido: 5 min 24 s.

Para reproduzir, com Ollama no ar e os quatro jobs em
`/data/projects/leandro/scitechear/storage/jobs`:

```bash
.venv/bin/python docs/repro/remediacao-sumarizador/remediacao.py
```

Os sumários v1 aqui são byte a byte equivalentes aos de
[`../implicitas-v4-v6/`](../implicitas-v4-v6/) — o determinismo
(`seed=42`, `temperature=0`) se sustenta entre execuções.
