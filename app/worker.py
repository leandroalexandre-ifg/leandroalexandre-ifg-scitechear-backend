"""Worker dedicado — consome a fila de jobs (job_repository.py, tabela
`jobs`) num processo separado da API. Reiniciar a API não afeta o
processamento em andamento, e vice-versa: cada um é um processo próprio
(dois serviços systemd em produção; dois processos em dev). Ver
docs/BACKEND_ARCHITECTURE.md.

V1: um único worker por vez. O pipeline é GPU-bound (WhisperX, pyannote,
SpeechBrain — uma GPU por servidor) — não há paralelismo real a ganhar
processando mais de um job simultaneamente na mesma GPU, então a fila é
consumida sequencialmente por um único processo dedicado.

No boot, reenfileira jobs órfãos: deixados por uma instância anterior deste
mesmo worker que morreu no meio do processamento (ver
JobRepository.requeue_orfaos — inclui proteção contra "job veneno", que
para de reenfileirar e vai para error após WORKER_MAX_ATTEMPTS_BEFORE_ERROR
tentativas).

Rodar: `python -m app.worker`.
"""
import logging
import time

from app.config import get_settings
from app.repositories.job_repository import get_job_repository
from app.services.job_runner import executar_job

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    jobs = get_job_repository()

    orfaos = jobs.requeue_orfaos(max_attempts=settings.worker_max_attempts_before_error)
    if orfaos:
        logger.warning(
            "Worker iniciado: %d job(s) órfão(s) de uma instância anterior tratado(s): %s",
            len(orfaos),
            orfaos,
        )

    logger.info(
        "Worker pronto, consumindo a fila (intervalo de polling: %ss).",
        settings.worker_poll_interval_seconds,
    )
    while True:
        job_id = jobs.next_queued()
        if job_id is None:
            time.sleep(settings.worker_poll_interval_seconds)
            continue

        logger.info("Processando job %s.", job_id)
        try:
            executar_job(job_id)
        except Exception:  # noqa: BLE001 — rede de segurança; pipeline_facade já
            # captura e registra erro de estágio no job. Isto só protege contra
            # um bug fora desse caminho (ex.: na própria construção da facade),
            # para não derrubar o loop do worker — o job fica no estágio em
            # que travou e é tratado por requeue_orfaos() no próximo boot.
            logger.exception("Falha não tratada ao executar o job %s.", job_id)


if __name__ == "__main__":
    main()
