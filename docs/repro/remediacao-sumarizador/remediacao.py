"""Movimento 3 — remediação: filtro estrutural + meeting_summary_v2 juntos,
contra o baseline sem nenhuma correção.

Mesmos quatro jobs do comparativo v4 × v6, mesmos `segments` já gravados
(nenhum áudio é reprocessado). Duas condições por job:

  baseline  = sumário v1 + filtro DESLIGADO  (reproduz 22/09)
  corrigido = sumário v2 + filtro LIGADO

Por transcrição rodam 2 sumarizações (v1 e v2 — o prompt mudou, não dá para
reusar) e 4 extrações de implícitas (v4 e v6 × baseline e corrigido).

Não escreve no storage de produção nem toca no .env: as versões entram por
os.environ + cache_clear, como no harness anterior.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

RAIZ = "/data/projects/leandro/leandroalexandre-ifg-scitechear-backend"
sys.path.insert(0, RAIZ)

from app.config import get_settings  # noqa: E402
from app.models.result import Segment  # noqa: E402
from app.services import question_service as qs  # noqa: E402
from app.services.transcript_formatter import TranscriptFormatter  # noqa: E402

JOBS = Path("/data/projects/leandro/scitechear/storage/jobs")
SAIDA = Path(__file__).resolve().parent
CORPUS = [
    ("2e335c5c", "2e335c5c-7715-4e8f-b703-37f5f8d328ae", "R5 — reunião Ana/Bruno (o '30 de outubro')"),
    ("00c2ff18", "00c2ff18-eedd-470a-94a8-2e4a16092425", "Controle — ata de alinhamento, sem questão aberta"),
    ("6150ce54", "6150ce54-cde7-46de-bd1a-84dbecc938ef", "Controle de confabulação — conversa trivial real"),
    ("50098d37", "50098d37-b468-4434-ab3a-c0cfb4f23839", "Reunião acadêmica real (RUFAS), 12 min"),
]

TETO_SEGUNDOS = 35 * 60  # declarado antes de rodar
inicio_lote = time.monotonic()

_brutas = []
_original = qs._chamar_ollama


def _captura(prompt, contexto="chamada_ollama", think=True):
    resposta = _original(prompt, contexto=contexto, think=think)
    _brutas.append({"contexto": contexto, "prompt_chars": len(prompt), "resposta": resposta})
    return resposta


qs._chamar_ollama = _captura


def _config(*, sumario_versao=None, implicitas_versao=None, filtro=None):
    if sumario_versao is not None:
        os.environ["MEETING_SUMMARY_PROMPT_VERSION"] = sumario_versao
    if implicitas_versao is not None:
        os.environ["IMPLICIT_QUESTIONS_PROMPT_VERSION"] = implicitas_versao
    if filtro is not None:
        os.environ["ENABLE_SUMMARY_FILTER"] = "true" if filtro else "false"
    get_settings.cache_clear()


def _sumarizar(curto, formatter, versao):
    _config(sumario_versao=versao)
    del _brutas[:]
    t0 = time.monotonic()
    texto = qs.summarize_meeting(formatter)
    dur = time.monotonic() - t0
    print(f"  sumário {versao}: {dur:.1f}s ({len(texto)} chars)", flush=True)
    (SAIDA / f"{curto}_sumario_{versao}.txt").write_text(texto, encoding="utf-8")
    return texto, round(dur, 1)


def _extrair(curto, formatter, sumario, condicao, impl_versao, filtro):
    _config(implicitas_versao=impl_versao, filtro=filtro)
    del _brutas[:]
    t0 = time.monotonic()
    erro, perguntas = None, []
    try:
        perguntas = qs.extract_implicit_questions(formatter, sumario)
    except Exception as exc:  # noqa: BLE001 — o erro real é o dado
        erro = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    dur = time.monotonic() - t0
    print(f"    [{condicao}/{impl_versao}] {len(perguntas)} perguntas em {dur:.1f}s"
          + (f" ERRO={erro}" if erro else ""), flush=True)
    return {
        "condicao": condicao,
        "versao_implicitas": impl_versao,
        "filtro": filtro,
        "duracao_s": round(dur, 1),
        "erro": erro,
        "total": len(perguntas),
        "perguntas": [{"id": q.id, "text": q.text, "source_segment_ids": q.source_segment_ids}
                      for q in perguntas],
        "resposta_bruta": _brutas[-1]["resposta"] if _brutas else None,
        "prompt_chars": _brutas[-1]["prompt_chars"] if _brutas else None,
    }


relatorio = {"teto_segundos": TETO_SEGUNDOS, "corpus": []}

for curto, job_id, descricao in CORPUS:
    decorrido = time.monotonic() - inicio_lote
    if decorrido > TETO_SEGUNDOS:
        print(f"TETO ESTOURADO ({decorrido:.0f}s) — parando antes de {curto}", flush=True)
        relatorio["interrompido_em"] = curto
        break

    print(f"== {curto} — {descricao}  [t+{decorrido:.0f}s]", flush=True)
    dados = json.loads((JOBS / job_id / "result.json").read_text(encoding="utf-8"))
    segmentos = [Segment(**s) for s in dados["segments"]]
    formatter = TranscriptFormatter(segmentos)
    (SAIDA / f"{curto}_transcricao.txt").write_text(formatter.render(), encoding="utf-8")

    sum_v1, dur_v1 = _sumarizar(curto, formatter, "v1")
    sum_v2, dur_v2 = _sumarizar(curto, formatter, "v2")

    item = {
        "job_curto": curto, "job_id": job_id, "descricao": descricao,
        "n_segmentos": len(dados["segments"]),
        "duracao_audio_s": round(dados["segments"][-1]["end"], 1) if dados["segments"] else 0,
        "sumario_v1_chars": len(sum_v1), "sumario_v2_chars": len(sum_v2),
        "sumarizacao_v1_s": dur_v1, "sumarizacao_v2_s": dur_v2,
        "execucoes": [
            _extrair(curto, formatter, sum_v1, "baseline", "v4", filtro=False),
            _extrair(curto, formatter, sum_v1, "baseline", "v6", filtro=False),
            _extrair(curto, formatter, sum_v2, "corrigido", "v4", filtro=True),
            _extrair(curto, formatter, sum_v2, "corrigido", "v6", filtro=True),
        ],
    }
    relatorio["corpus"].append(item)
    (SAIDA / "remediacao.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")

relatorio["duracao_total_s"] = round(time.monotonic() - inicio_lote, 1)
(SAIDA / "remediacao.json").write_text(
    json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"FIM — {relatorio['duracao_total_s']:.0f}s de {TETO_SEGUNDOS}s de teto", flush=True)
