"""QuestionService — extração de perguntas via Ollama/Qwen3 (port de
legacy/notebooks/llm.ipynb), usando os prompts versionados em prompts/.

Preserva o algoritmo original: mesma requisição ao Ollama
(`/api/generate`, `think: true`, `temperature=0, top_p=1, top_k=1,
repeat_penalty=1.0, num_ctx=32768, seed=42`) e os mesmos prompts,
semanticamente intactos. Únicas mudanças de comportamento:

- EXPLÍCITAS: preserva o prompt (prompts/explicit_questions_v4.json) e a
  regra estrita (só sentenças terminadas em '?'); a saída já era JSON — só
  passa a ser validada contra um schema Pydantic. `linha_transcricao` é
  resolvida pelo TranscriptFormatter (nunca por inferência do LLM) para
  obter participant_id/speaker/time/source_segment_ids — o texto da
  pergunta permanece literal, nunca corrigido.
- IMPLÍCITAS: migradas para prompts/implicit_questions_v3.txt, que pede
  saída em JSON em vez do texto numerado do v2 — sem alterar critérios
  semânticos (máx. 15, não inventar fatos, etc.). speaker/time NUNCA são
  inventados: ficam null (type=implicit).
- SUMARIZAÇÃO: artefato interno (prompts/meeting_summary_v1.txt); não é
  contrato do Flutter, continua texto.
- REFINAMENTO (prompts/implicit_refiner_v1.txt): implementado mas em
  standby — só é chamado se ENABLE_IMPLICIT_REFINEMENT=true.
- RAG: não implementado nesta V1 (decisão da spec).
"""
import json
import logging
import re
from pathlib import Path
from typing import List

import requests
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models.result import Question, QuestionType
from app.services.transcript_formatter import TranscriptFormatter

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
EXPLICIT_QUESTIONS_PROMPT = "explicit_questions_v4.json"
MEETING_SUMMARY_PROMPT = "meeting_summary_v1.txt"
IMPLICIT_QUESTIONS_PROMPT = "implicit_questions_v3.txt"
IMPLICIT_REFINER_PROMPT = "implicit_refiner_v1.txt"


class ExplicitQuestionRaw(BaseModel):
    id: str
    pergunta: str
    falante: str
    linha_transcricao: int
    segmentos_anteriores: List[str] = Field(default_factory=list)


class ExplicitQuestionsResponse(BaseModel):
    perguntas: List[ExplicitQuestionRaw]
    total_perguntas: int


class ImplicitQuestionRaw(BaseModel):
    id: str
    pergunta: str


class ImplicitQuestionsResponse(BaseModel):
    perguntas_implicitas: List[ImplicitQuestionRaw]
    total_perguntas: int


def _carregar_prompt(nome_arquivo: str) -> str:
    return (PROMPTS_DIR / nome_arquivo).read_text(encoding="utf-8")


def _chamar_ollama(prompt: str) -> str:
    settings = get_settings()
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "think": True,
        "options": {
            "temperature": 0,
            "top_p": 1,
            "top_k": 1,
            "repeat_penalty": 1.0,
            "num_ctx": 32768,
            "num_predict": -1,
            "seed": 42,
        },
    }
    response = requests.post(f"{settings.ollama_base_url}/api/generate", json=payload, timeout=None)
    response.raise_for_status()
    dados = response.json()
    return dados.get("response", "")


def _extrair_json(texto: str) -> dict:
    """Faz parse do JSON na resposta do LLM, tolerando cercas de código
    markdown (```json ... ```) ao redor — sem alterar o conteúdo semântico,
    só removendo o envelope de formatação."""
    texto = texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)
        texto = texto.strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError as exc:
        inicio = texto.find("{")
        fim = texto.rfind("}")
        if inicio != -1 and fim != -1 and fim > inicio:
            return json.loads(texto[inicio : fim + 1])
        raise ValueError(f"Resposta do LLM não é um JSON válido: {exc}") from exc


def extract_explicit_questions(formatter: TranscriptFormatter) -> List[Question]:
    """Perguntas explícitas: preserva o prompt/regra de extração literal (só
    sentenças terminadas em '?'). `linha_transcricao` é resolvida pelo
    TranscriptFormatter — nunca pelo que o LLM disser sobre falante/tempo."""
    prompt = _carregar_prompt(EXPLICIT_QUESTIONS_PROMPT)
    prompt_final = f"{prompt}\n\n{formatter.render()}"

    resposta_bruta = _chamar_ollama(prompt_final)
    dados = _extrair_json(resposta_bruta)
    validado = ExplicitQuestionsResponse.model_validate(dados)

    perguntas: List[Question] = []
    for item in validado.perguntas:
        linha = formatter.resolve(item.linha_transcricao)
        if linha is None:
            logger.warning(
                "Pergunta explícita %s referenciou linha_transcricao=%d fora do range.",
                item.id,
                item.linha_transcricao,
            )
        perguntas.append(
            Question(
                id=item.id,
                type=QuestionType.EXPLICIT,
                text=item.pergunta,  # literal — nunca corrigido
                participant_id=linha.participant_id if linha else None,
                speaker=linha.speaker if linha else None,
                time=linha.time if linha else None,
                source_segment_ids=linha.source_segment_ids if linha else [],
            )
        )
    return perguntas


def summarize_meeting(formatter: TranscriptFormatter) -> str:
    """Sumarização: artefato interno (não é contrato do Flutter). Preserva
    PromptSumarizacaoV1 semanticamente; saída continua texto."""
    prompt = _carregar_prompt(MEETING_SUMMARY_PROMPT)
    prompt_final = f"{prompt}\n\n{formatter.render()}"
    return _chamar_ollama(prompt_final)


def extract_implicit_questions(formatter: TranscriptFormatter, summary: str) -> List[Question]:
    """Perguntas implícitas (prompts/implicit_questions_v3.txt — sumário +
    transcrição, saída JSON). speaker/time NUNCA são inventados: ficam null."""
    prompt = _carregar_prompt(IMPLICIT_QUESTIONS_PROMPT)
    prompt_final = f"{prompt}\n\n{summary}\n\n{formatter.render()}"

    resposta_bruta = _chamar_ollama(prompt_final)
    dados = _extrair_json(resposta_bruta)
    validado = ImplicitQuestionsResponse.model_validate(dados)

    return [
        Question(
            id=item.id,
            type=QuestionType.IMPLICIT,
            text=item.pergunta,
            participant_id=None,
            speaker=None,
            time=None,
            source_segment_ids=[],
        )
        for item in validado.perguntas_implicitas
    ]


def _parse_lista_numerada(texto: str) -> List[str]:
    """Parser do formato de saída do refinador (texto numerado '1. ...'),
    que não foi migrado para JSON — só as perguntas implícitas foram."""
    linhas = []
    for linha in texto.strip().splitlines():
        linha = linha.strip()
        sem_numero = re.sub(r"^\d+[.)]\s*", "", linha)
        if sem_numero:
            linhas.append(sem_numero)
    return linhas


def refine_implicit_questions(perguntas: List[Question], formatter: TranscriptFormatter) -> List[Question]:
    """Refinamento (prompts/implicit_refiner_v1.txt) — reescreve/consolida
    perguntas já extraídas, sem criar novas. EM STANDBY: só deve ser chamado
    quando settings.enable_implicit_refinement for True (spec: testado e
    considerado de baixo ganho; desativado por padrão)."""
    prompt = _carregar_prompt(IMPLICIT_REFINER_PROMPT)
    perguntas_numeradas = "\n".join(f"{i + 1}. {q.text}" for i, q in enumerate(perguntas))
    prompt_final = f"{prompt}\n\n{perguntas_numeradas}\n\n{formatter.render()}"

    resposta_bruta = _chamar_ollama(prompt_final)
    textos_refinados = _parse_lista_numerada(resposta_bruta)

    return [
        Question(
            id=f"I{i + 1}",
            type=QuestionType.IMPLICIT,
            text=texto,
            participant_id=None,
            speaker=None,
            time=None,
            source_segment_ids=[],
        )
        for i, texto in enumerate(textos_refinados)
    ]


def gerar_perguntas(formatter: TranscriptFormatter) -> List[Question]:
    """Orquestra a extração completa: explícitas -> sumarização -> implícitas
    -> (refinamento, só se habilitado por flag). Devolve a lista combinada,
    pronta para o resultado canônico."""
    settings = get_settings()

    explicitas = extract_explicit_questions(formatter)
    sumario = summarize_meeting(formatter)
    implicitas = extract_implicit_questions(formatter, sumario)

    if settings.enable_implicit_refinement:
        implicitas = refine_implicit_questions(implicitas, formatter)

    return explicitas + implicitas
