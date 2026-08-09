"""Executor de jobs — abstração para disparar o processamento de uma
reunião sem bloquear a resposta do POST /upload.

A V1 roda o pipeline in-process (uma thread por job), mas a INTERFACE
(`submit(job_id)`) é a mesma que um executor baseado em fila (Celery/Redis)
usaria depois — trocar a implementação não deve exigir mudanças na API nem
no PipelineFacade. Não implementamos fila real nesta fase (spec: "manter
interface de executor... não bloquear a integração inicial esperando
infraestrutura de fila definitiva").
"""
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class InProcessJobExecutor:
    """Roda `run_job(job_id)` numa thread daemon separada. Sem persistência
    entre reinícios, sem retry, sem múltiplos workers — só o suficiente para
    o E2E da V1 responder rápido ao /upload."""

    def __init__(self, run_job: Callable[[str], None]):
        self._run_job = run_job

    def submit(self, job_id: str) -> None:
        thread = threading.Thread(target=self._executar, args=(job_id,), daemon=True)
        thread.start()

    def _executar(self, job_id: str) -> None:
        try:
            self._run_job(job_id)
        except Exception:
            # Rede de segurança: o PipelineFacade já captura e registra erro
            # de estágio no job; isto só protege contra um bug na própria
            # captura de erro, para não derrubar a thread silenciosamente.
            logger.exception("Falha não tratada ao executar o job %s", job_id)
