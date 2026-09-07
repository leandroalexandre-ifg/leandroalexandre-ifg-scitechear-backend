from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.participant import Participant


class JobStatusValue(str, Enum):
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    IDENTIFYING = "identifying"
    SUMMARIZING = "summarizing"
    EXTRACTING = "extracting"
    DONE = "done"
    ERROR = "error"


class JobError(BaseModel):
    code: str
    message: str


class UploadResponse(BaseModel):
    job_id: str
    status: JobStatusValue = JobStatusValue.QUEUED


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatusValue
    # Nunca preenchido hoje — nenhum estágio do pipeline reporta fração
    # concluída, e inventar um número seria pior que não ter. Mantido no
    # contrato porque o app já o lê como opcional; a granularidade real é o
    # `status`. Confirmado ao frontend em 07/09/2026: não construir UI de
    # percentual em cima disso sem antes combinar quem preenche.
    progress: Optional[float] = None
    error: Optional[JobError] = None
    updated_at: datetime


class MeetingSummary(BaseModel):
    """Item de GET /meetings — resumo de uma reunião do usuário autenticado,
    sem o payload completo do resultado (ver MeetingResult para isso).

    `participants` e `error` entraram a pedido do app (07/09/2026), para o
    histórico do servidor poder substituir o histórico local: o cartão da
    reunião mostra os NOMES dos participantes (contagem não serve), e um job
    em `error` precisa do `error.code` para o app traduzir a falha — o
    `error.message` é `str(exc)` da exceção Python, não texto de usuário.
    Os dois já viviam na linha do job; o que faltava era exportá-los.
    """

    job_id: str
    title: Optional[str] = None
    status: JobStatusValue
    participants: List[Participant] = Field(default_factory=list)
    error: Optional[JobError] = None
    created_at: datetime
    updated_at: datetime


class MeetingTitleUpdate(BaseModel):
    """Corpo de PATCH /meetings/{job_id}. Só o título é editável — todo o
    resto do registro é produzido pelo pipeline, não pelo usuário. `null`
    limpa o título (a reunião volta a ser identificada pela data)."""

    title: Optional[str] = None
