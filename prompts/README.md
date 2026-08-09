# prompts

Prompts de LLM versionados. **Preserve-os semanticamente**; mudanças de formato
devem ser mínimas e versionadas (ver especificação).

| Arquivo aqui | Origem enviada | Uso |
|---|---|---|
| `explicit_questions_v4.json` | PromptDeExtracaoDePerguntasExplicitasV4.json | Perguntas explícitas (só sentenças terminadas em `?`). |
| `meeting_summary_v1.txt` | PromptSumarizacaoV1.txt | Sumarização (artefato interno). |
| `implicit_questions_v2.txt` | PromptGerador.txt | **Superado por v3** — preservado só para rastreabilidade (saída em texto numerado, não JSON). |
| `implicit_questions_v3.txt` | implicit_questions_v2.txt (Fase 5) | **Ativo.** Perguntas implícitas (sumário + transcrição), mesmos critérios semânticos do v2, saída migrada para JSON (`type=implicit`, sem `falante`/tempo). Usado por `app/services/question_service.py`. |
| `implicit_refiner_v1.txt` | PromptRefinadorPerguntas.txt | Refinamento (desativado por default: `ENABLE_IMPLICIT_REFINEMENT=false`). |

Perguntas implícitas usam a v3 (saída JSON) desde a Fase 5. A v2 fica no
repositório apenas como referência histórica — não é mais chamada pelo
serviço.
