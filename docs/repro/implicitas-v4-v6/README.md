# Artefatos do comparativo v4 × v6 de perguntas implícitas

Material bruto do comparativo de 22/09/2026. A análise está em
[`../../COMPARATIVO_IMPLICITAS_V4_V6.md`](../../COMPARATIVO_IMPLICITAS_V4_V6.md);
aqui ficam as entradas e saídas exatas, para que qualquer conclusão do
documento possa ser conferida sem rodar nada.

| Arquivo | O quê |
|---|---|
| `comparativo.py` | O script que rodou. Lê `segments` de resultados reais já gravados (nenhum áudio é reprocessado), sumariza uma vez por transcrição e reusa o mesmo sumário nas duas versões — a única variável entre v4 e v6 é o prompt. Não escreve no storage de produção nem toca no `.env`. |
| `comparativo.json` | Resultado completo: perguntas de cada versão, `source_segment_ids`, tempos, tamanho do prompt e a **resposta bruta do modelo**. |
| `<job>_transcricao.txt` | A transcrição exatamente como o `TranscriptFormatter` a entrega ao LLM (`N -> seg_XXXX -> [Falante]: texto`). |
| `<job>_sumario.txt` | O sumário gerado, reusado pelas duas versões. **É aqui que está o achado principal** — ver a pendência do sumarizador em `../../PENDENCIAS.md`. |

Jobs, todos de `/data/projects/leandro/scitechear/storage/jobs`:

- `2e335c5c` — R5, reunião Ana/Bruno (80 s). O caso central: redundância do v4
  e o "30 de outubro" alucinado.
- `00c2ff18` — ata de alinhamento sem nenhuma questão aberta. Controle: o
  esperado era `Não possui`.
- `6150ce54` — conversa trivial real. Controle de confabulação, **substituta em
  forma** da transcrição do carro que expôs o v3 e não existe mais; não é a
  mesma entrada.
- `50098d37` — reunião acadêmica real (RUFAS/fazendas leiteiras), 12 min.

Reproduzir exige Ollama de pé com `qwen3:14b` e os jobs no caminho acima. Com
`temperature=0` e `seed=42` a saída é estável, mas não há garantia entre
versões diferentes do modelo — por isso as respostas brutas estão salvas.
