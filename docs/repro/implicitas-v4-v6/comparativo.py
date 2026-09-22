"""Fase 3 — comparativo v4 x v6 de perguntas implícitas com dados reais.

Reaproveita os `segments` já gravados em resultados reais (nenhum áudio é
reprocessado): só as chamadas ao LLM rodam. Uma sumarização por transcrição,
reusada pelos dois prompts, para que a única variável entre v4 e v6 seja o
prompt. Não escreve nada no storage de produção nem toca no .env.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/data/projects/leandro/leandroalexandre-ifg-scitechear-backend")

from app.config import get_settings  # noqa: E402
from app.models.result import Segment  # noqa: E402
from app.services import question_service as qs  # noqa: E402
from app.services.transcript_formatter import TranscriptFormatter  # noqa: E402

JOBS = Path("/data/projects/leandro/scitechear/storage/jobs")
SAIDA = Path(__file__).resolve().parent / "fase3"
SAIDA.mkdir(exist_ok=True)

CORPUS = [
    ("2e335c5c", "2e335c5c-7715-4e8f-b703-37f5f8d328ae", "R5 — reunião Ana/Bruno (caso central: redundância + '30 de outubro')"),
    ("00c2ff18", "00c2ff18-eedd-470a-94a8-2e4a16092425", "Controle — ata de alinhamento, sem questão aberta"),
    ("6150ce54", "6150ce54-cde7-46de-bd1a-84dbecc938ef", "Controle de confabulação — conversa trivial real (substituta da transcrição do carro)"),
    ("50098d37", "50098d37-b468-4434-ab3a-c0cfb4f23839", "Reunião acadêmica real (RUFAS/fazendas leiteiras), 12 min"),
]

TETO_SEGUNDOS = 30 * 60
inicio_lote = time.monotonic()

_respostas_brutas = []
_original = qs._chamar_ollama


def _chamar_com_captura(prompt, contexto="chamada_ollama", think=True):
    resposta = _original(prompt, contexto=contexto, think=think)
    _respostas_brutas.append({"contexto": contexto, "prompt_chars": len(prompt), "resposta": resposta})
    return resposta


qs._chamar_ollama = _chamar_com_captura


def _formatter_do_job(job_dir):
    dados = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    segmentos = [Segment(**s) for s in dados["segments"]]
    return TranscriptFormatter(segmentos), dados


def _com_versao(versao):
    os.environ["IMPLICIT_QUESTIONS_PROMPT_VERSION"] = versao
    get_settings.cache_clear()


def _rodar(rotulo, formatter, sumario, versao):
    _com_versao(versao)
    del _respostas_brutas[:]
    t0 = time.monotonic()
    erro = None
    perguntas = []
    try:
        perguntas = qs.extract_implicit_questions(formatter, sumario)
    except Exception as exc:  # noqa: BLE001 — o erro real é o dado, não um fallback
        erro = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    duracao = time.monotonic() - t0
    print(f"  [{rotulo}] {versao}: {len(perguntas)} perguntas em {duracao:.1f}s"
          + (f" ERRO={erro}" if erro else ""), flush=True)
    return {
        "versao": versao,
        "duracao_s": round(duracao, 1),
        "erro": erro,
        "total": len(perguntas),
        "perguntas": [
            {"id": q.id, "text": q.text, "source_segment_ids": q.source_segment_ids}
            for q in perguntas
        ],
        "resposta_bruta": _respostas_brutas[-1]["resposta"] if _respostas_brutas else None,
        "prompt_chars": _respostas_brutas[-1]["prompt_chars"] if _respostas_brutas else None,
    }


relatorio = {"corpus": [], "teto_segundos": TETO_SEGUNDOS}

for curto, job_id, descricao in CORPUS:
    decorrido = time.monotonic() - inicio_lote
    if decorrido > TETO_SEGUNDOS:
        print(f"TETO DE {TETO_SEGUNDOS}s ESTOURADO ({decorrido:.0f}s) — parando antes de {curto}", flush=True)
        relatorio["interrompido_em"] = curto
        break

    print(f"== {curto} — {descricao}", flush=True)
    formatter, dados = _formatter_do_job(JOBS / job_id)
    transcricao = formatter.render()
    (SAIDA / f"{curto}_transcricao.txt").write_text(transcricao, encoding="utf-8")

    del _respostas_brutas[:]
    t0 = time.monotonic()
    sumario = qs.summarize_meeting(formatter)
    dur_sumario = time.monotonic() - t0
    print(f"  sumarização: {dur_sumario:.1f}s ({len(sumario)} chars)", flush=True)
    (SAIDA / f"{curto}_sumario.txt").write_text(sumario, encoding="utf-8")

    item = {
        "job_curto": curto,
        "job_id": job_id,
        "descricao": descricao,
        "n_segmentos": len(dados["segments"]),
        "duracao_audio_s": round(dados["segments"][-1]["end"], 1) if dados["segments"] else 0,
        "transcricao_chars": len(transcricao),
        "sumarizacao_s": round(dur_sumario, 1),
        "v4": _rodar(curto, formatter, sumario, "v4"),
        "v6": _rodar(curto, formatter, sumario, "v6"),
    }
    relatorio["corpus"].append(item)
    (SAIDA / "comparativo.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

relatorio["duracao_total_s"] = round(time.monotonic() - inicio_lote, 1)
(SAIDA / "comparativo.json").write_text(
    json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"FIM — {relatorio['duracao_total_s']:.0f}s de {TETO_SEGUNDOS}s de teto", flush=True)
