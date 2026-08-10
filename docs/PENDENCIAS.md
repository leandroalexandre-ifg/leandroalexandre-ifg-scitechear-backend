# Pendências — SciTech Ear · Backend

Registro vivo de achados que não bloqueiam a fase corrente, mas precisam de
acompanhamento — calibração de prompt/modelo, comportamento a reverificar
antes de considerar algo definitivamente resolvido, etc. Diferente de
`docs/BASELINE.md` (retrato pontual da Fase 0): este arquivo é atualizado ao
longo do projeto.

## Aberta — Perguntas explícitas: prefixo `[Nome]: ` vazando no campo `text`

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
existentes (regra do CLAUDE.md).

**Status:** aberta, não bloqueia fases seguintes.
