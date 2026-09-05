# prompts

Prompts de LLM versionados. **Preserve-os semanticamente**; mudanças de formato
devem ser mínimas e versionadas (ver especificação).

| Arquivo aqui | Origem enviada | Uso |
|---|---|---|
| `explicit_questions_v4.json` | PromptDeExtracaoDePerguntasExplicitasV4.json | **Superado por v5** — preservado só para rastreabilidade. |
| `explicit_questions_v5.json` | explicit_questions_v4.json (Fase 8) | **Ativo.** Perguntas explícitas (só sentenças terminadas em `?`). Critérios de extração idênticos aos do v4 — a mudança é de fidelidade de formato, não semântica: (1) uma regra dizendo que o rótulo entre colchetes que abre a linha (`[Leandro]: `, `[SPEAKER_00]: `) é formato da transcrição e não pertence ao campo `pergunta`; (2) um segundo exemplo few-shot com falante NÃO identificado, que era o caso ausente no v4; (3) o exemplo de sentença curta passou a mostrar o texto extraído, não a linha inteira. Motivo em `docs/PENDENCIAS.md` e `docs/E2E_FASE8.md`. |
| `meeting_summary_v1.txt` | PromptSumarizacaoV1.txt | Sumarização (artefato interno). |
| `implicit_questions_v2.txt` | PromptGerador.txt | **Superado por v3** — preservado só para rastreabilidade (saída em texto numerado, não JSON). |
| `implicit_questions_v3.txt` | implicit_questions_v2.txt (Fase 5) | **Superado por v4** — preservado só para rastreabilidade. Saída JSON sem campo de evidência; causou confabulação de perguntas implícitas sem lastro na transcrição (ver `docs/PENDENCIAS.md`). |
| `implicit_questions_v4.txt` | implicit_questions_v3.txt | **Ativo.** Mesmos critérios semânticos do v3 (linguagem formal, não redundância, foco em tomada de decisão). Duas mudanças: (1) exige campo `linhas_evidencia` por pergunta, rastreando a inferência até linhas reais da transcrição — validado programaticamente em `question_service.py`, que descarta perguntas sem evidência majoritariamente real; (2) reformula o teto de 15 perguntas como limite absoluto, não meta — lista vazia é saída válida. Usado por `app/services/question_service.py`. |
| `implicit_refiner_v1.txt` | PromptRefinadorPerguntas.txt | Refinamento (desativado por default: `ENABLE_IMPLICIT_REFINEMENT=false`). Reescreve/consolida perguntas já extraídas; não audita evidência e hoje descarta `source_segment_ids` ao reconstruir as perguntas — limitação conhecida, sem impacto enquanto a flag estiver desligada (ver `docs/PENDENCIAS.md`). |

Perguntas implícitas usam a v4 (saída JSON + evidência) desde a calibração
de confabulação (2026-08-11). A v2 e a v3 ficam no repositório apenas como
referência histórica — não são mais chamadas pelo serviço.
