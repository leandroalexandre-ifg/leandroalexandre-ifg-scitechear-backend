# repro — AS-Norm com cohort por usuário (22/09/2026)

Artefatos da medição analisada em
[`../../ASNORM_COHORT_USUARIO.md`](../../ASNORM_COHORT_USUARIO.md).

| Arquivo | O que é |
|---|---|
| `medir.py` | O script que rodou. Só lê `tests/fixtures/voice_identification_real_embeddings.json` e usa funções puras de `app/services/voice_service.py` (nenhum áudio, GPU, `.env` ou storage). ~4 s em CPU. |
| `medicao.json` | Saída completa: baseline (threshold fixo), cohort da reunião, cohort do usuário, banco crescido por nº de identidades extras (todos os subconjuntos, top-k 3/5/todos; linhas completas só para 6 extras) e o limite otimista com o próprio perfil do impostor no banco. |

Reproduzir, da raiz do repositório:

    .venv/bin/python docs/repro/asnorm-cohort/medir.py > docs/repro/asnorm-cohort/medicao.json

Para repetir com voz humana real, troque a fonte de `carregar()` por
embeddings do `VoiceRepository` — o resto do script não depende do fixture.
