# prompts

Prompts de LLM versionados. **Preserve-os semanticamente**; mudanças de formato
devem ser mínimas e versionadas (ver especificação).

| Arquivo aqui | Origem enviada | Uso |
|---|---|---|
| `explicit_questions_v4.json` | PromptDeExtracaoDePerguntasExplicitasV4.json | Perguntas explícitas (só sentenças terminadas em `?`). |
| `meeting_summary_v1.txt` | PromptSumarizacaoV1.txt | Sumarização (artefato interno). |
| `implicit_questions_v2.txt` | PromptGerador.txt | Perguntas implícitas (baseadas em sumário + transcrição). |
| `implicit_refiner_v1.txt` | PromptRefinadorPerguntas.txt | Refinamento (desativado por default: `ENABLE_IMPLICIT_REFINEMENT=false`). |

Observação: na V1 integrada, o prompt de perguntas implícitas deve ganhar **saída
JSON** (sem alterar seus critérios semânticos), conforme a especificação.
