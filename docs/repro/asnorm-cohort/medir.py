"""Mede o AS-Norm (S-norm adaptativo) de app/services/voice_service.py contra
o fixture de embeddings ECAPA reais (TTS) — nenhum áudio, nenhuma GPU, nenhum
acesso ao storage de produção. Roda em segundos.

Uso (da raiz do repositório):
    .venv/bin/python docs/repro/asnorm-cohort/medir.py > docs/repro/asnorm-cohort/medicao.json

Cenários (a análise está em docs/ASNORM_COHORT_USUARIO.md):

- baseline: threshold fixo de produção (0.75 / margem 0.05).
- reuniao: cohort = os outros participantes da reunião (o desenho da
  primeira tentativa, reimplementado com o S-norm atual).
- usuario: cohort = todos os perfis do usuário. No fixture o usuário só tem
  os 3 cadastrados, então este cenário COINCIDE com `reuniao` — medido mesmo
  assim para que isso fique registrado e não inferido.
- crescido: banco do usuário "crescido" com as 7 identidades de impostor do
  fixture como se estivessem cadastradas (mas fora da reunião). A
  identidade sob teste é SEMPRE retirada do cohort (leave-one-out): é o caso
  difícil, falante que não tem perfil nenhum. Varre todos os subconjuntos
  das identidades extras para medir o efeito do tamanho do cohort.
- crescido_com_proprio_perfil: o impostor sob teste TEM perfil no banco do
  usuário (só não é participante da reunião). No fixture o perfil e o áudio
  de teste de um impostor são o MESMO vetor, então isto é um limite
  otimista, não uma medição realista.

Cada cenário é medido com top-k 3, 5 e "todos".
"""
import itertools
import json
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))

import torch  # noqa: E402

from app.services import voice_service  # noqa: E402

FIXTURE = RAIZ / "tests" / "fixtures" / "voice_identification_real_embeddings.json"

THRESHOLD_FIXO = 0.75
MARGEM_FIXA = 0.05
# Defaults de Settings no momento da medição — ver app/config.py.
ASNORM_THRESHOLD = 3.0
ASNORM_MARGEM = 1.0
ASNORM_PISO_BRUTO = 0.40
TOP_KS = [3, 5, 10_000]


def _t(v):
    return voice_service.normalizar_embedding(torch.tensor(v))


def carregar():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cadastrados = {pid: _t(v) for pid, v in d["enrolled"].items()}
    extras = {pid: _t(v) for pid, v in d["impostores_nao_outlier"].items()}
    extras.update({pid: _t(v) for pid, v in d["impostor_outlier"].items()})
    testes = []
    for pid, amostras in d["genuine_samples"].items():
        for i, v in enumerate(amostras):
            testes.append({"id": f"{pid}#{i}", "identidade": pid, "esperado": pid, "emb": _t(v)})
    for pid, emb in extras.items():
        testes.append({"id": pid, "identidade": pid, "esperado": None, "emb": emb})
    return cadastrados, extras, testes


def avaliar(teste, cadastrados, cohort, top_k):
    """Scores brutos e normalizados de um áudio de teste contra os 3
    candidatos da reunião, e a decisão com os defaults de AS-Norm. Usa só
    funções puras do voice_service — nenhuma leitura de Settings/.env."""
    emb = teste["emb"]
    brutos = {pid: voice_service.comparar_embeddings(emb, ref) for pid, ref in cadastrados.items()}
    norm = {}
    for pid, score in brutos.items():
        coh = [e for cid, e in cohort.items() if cid != pid]
        norm[pid] = voice_service.asnorm_score(score, emb, cadastrados[pid], coh, top_k)
    ranking = sorted(norm.items(), key=lambda kv: kv[1], reverse=True)
    melhor, melhor_n = ranking[0]
    margem = melhor_n - ranking[1][1]
    aceito = (
        brutos[melhor] >= ASNORM_PISO_BRUTO and melhor_n >= ASNORM_THRESHOLD and margem >= ASNORM_MARGEM
    )
    return {
        "teste": teste["id"],
        "esperado": teste["esperado"],
        "melhor": melhor,
        "bruto": round(brutos[melhor], 4),
        "normalizado": round(melhor_n, 3),
        "margem_normalizada": round(margem, 3),
        "normalizado_do_esperado": round(norm[teste["esperado"]], 3) if teste["esperado"] else None,
        "tamanho_cohort": min(len([c for c in cohort if c != pid]) for pid in cadastrados),
        "decisao": melhor if aceito else None,
    }


def baseline(testes, cadastrados):
    linhas = []
    for t in testes:
        brutos = sorted(
            ((pid, voice_service.comparar_embeddings(t["emb"], ref)) for pid, ref in cadastrados.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )
        (melhor, s1), (_, s2) = brutos[0], brutos[1]
        aceito = s1 >= THRESHOLD_FIXO and (s1 - s2) >= MARGEM_FIXA
        linhas.append({"teste": t["id"], "esperado": t["esperado"], "melhor": melhor, "bruto": round(s1, 4),
                       "decisao": melhor if aceito else None})
    return linhas


def resumir(linhas, chave="normalizado"):
    genuinas = [l for l in linhas if l["esperado"]]
    impostores = [l for l in linhas if not l["esperado"]]
    fp = sorted({l["teste"] for l in impostores if l["decisao"] is not None})
    fn = sorted({l["teste"] for l in genuinas if l["decisao"] != l["esperado"]})
    chave_genuina = "normalizado_do_esperado" if chave == "normalizado" else "bruto"
    piso_genuino = min(l[chave_genuina] for l in genuinas)
    teto_impostor = max(l[chave] for l in impostores)
    return {
        "falsos_positivos": fp,
        "falsos_negativos": fn,
        "n_decisoes_impostor": len(impostores),
        "n_fp_decisoes": sum(1 for l in impostores if l["decisao"] is not None),
        "n_decisoes_genuinas": len(genuinas),
        "n_fn_decisoes": sum(1 for l in genuinas if l["decisao"] != l["esperado"]),
        "piso_genuino": round(piso_genuino, 3),
        "teto_impostor": round(teto_impostor, 3),
        # >0 => existe um limiar que separa TODAS as genuínas de TODOS os impostores
        "folga": round(piso_genuino - teto_impostor, 3),
    }


def main():
    cadastrados, extras, testes = carregar()
    saida = {"defaults": {"threshold": ASNORM_THRESHOLD, "margem": ASNORM_MARGEM, "piso_bruto": ASNORM_PISO_BRUTO}}

    b = baseline(testes, cadastrados)
    saida["baseline"] = {"resumo": resumir(b, chave="bruto"), "linhas": b}

    for nome, cohort in [("reuniao", cadastrados), ("usuario", dict(cadastrados))]:
        saida[nome] = {}
        for k in TOP_KS:
            linhas = [avaliar(t, cadastrados, cohort, k) for t in testes]
            saida[nome][f"top{k if k < 10_000 else 'todos'}"] = {"resumo": resumir(linhas), "linhas": linhas}

    # Banco crescido, leave-one-out, todos os subconjuntos das 7 identidades
    # extras. Agrega por quantidade de extras cadastradas.
    ids_extras = sorted(extras)
    saida["crescido"] = {}
    for k in TOP_KS:
        por_n = {}
        # até 6 extras: com as 7 no banco não sobra impostor sem perfil
        for n in range(len(ids_extras)):
            linhas = []
            for sub in itertools.combinations(ids_extras, n):
                for t in testes:
                    if t["identidade"] in sub:
                        continue  # leave-one-out: quem está sob teste não tem perfil
                    cohort = dict(cadastrados)
                    cohort.update({pid: extras[pid] for pid in sub})
                    l = avaliar(t, cadastrados, cohort, k)
                    l["extras"] = list(sub)
                    linhas.append(l)
            r = resumir(linhas)
            r["subconjuntos"] = len(list(itertools.combinations(ids_extras, n)))
            r["tamanho_cohort_min"] = min(l["tamanho_cohort"] for l in linhas)
            r["tamanho_cohort_max"] = max(l["tamanho_cohort"] for l in linhas)
            # quantas vezes cada impostor virou falso positivo, entre os subconjuntos
            r["fp_por_impostor"] = {
                pid: sum(1 for l in linhas if l["teste"] == pid and l["decisao"] is not None)
                for pid in ids_extras
            }
            if n == len(ids_extras) - 1:
                r["linhas"] = linhas
            por_n[str(n)] = r
        saida["crescido"][f"top{k if k < 10_000 else 'todos'}"] = por_n

    # Impostor sob teste COM perfil no banco (fora da reunião). Limite otimista.
    saida["crescido_com_proprio_perfil"] = {}
    for k in TOP_KS:
        cohort = dict(cadastrados)
        cohort.update(extras)
        linhas = [avaliar(t, cadastrados, cohort, k) for t in testes]
        saida["crescido_com_proprio_perfil"][f"top{k if k < 10_000 else 'todos'}"] = {
            "resumo": resumir(linhas), "linhas": linhas
        }

    json.dump(saida, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
