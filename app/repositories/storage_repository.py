"""Artefatos de um job (áudio enviado, resultado canônico) em storage local
do runtime — nada de Google Drive ou barramento externo no caminho de
execução (regra invólavel do AGENTS.md).

Layout:
    storage/jobs/<job_id>/
        audio.<ext>     # WAV enviado no /upload
        result.json     # resultado canônico (gerenciado por ResultRepository)
"""
from pathlib import Path
from typing import BinaryIO, Optional

# Lê o upload em pedaços em vez de tudo de uma vez: uma reunião de duas horas
# em WAV 16 kHz mono passa de 200 MB, e o limite precisa ser aplicado DURANTE
# a gravação — checar depois de carregar já teria pago o custo.
_CHUNK_BYTES = 1024 * 1024


class ArquivoGrandeDemaisError(Exception):
    """Upload passou do teto configurado. Levantada com a gravação já
    interrompida e o arquivo parcial removido."""


class StorageRepository:
    def __init__(self, root: Path):
        self._root = Path(root)

    def job_dir(self, job_id: str) -> Path:
        return self._root / "jobs" / job_id

    def save_audio(self, job_id: str, content: bytes, filename_hint: str) -> Path:
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename_hint).suffix or ".wav"
        path = job_dir / f"audio{suffix}"
        path.write_bytes(content)
        return path

    def save_audio_stream(
        self, job_id: str, origem: BinaryIO, filename_hint: str, max_bytes: int
    ) -> Path:
        """Grava o áudio direto no disco, em pedaços, abortando assim que
        passar de `max_bytes`.

        Existe porque a alternativa — ler o upload inteiro para a memória e só
        então decidir — dá a quem envia o poder de escolher quanta RAM o
        servidor gasta. Aqui o teto é aplicado durante a escrita, e o arquivo
        parcial é removido antes de propagar o erro: nada de lixo ocupando
        disco por causa de um upload recusado."""
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename_hint).suffix or ".wav"
        path = job_dir / f"audio{suffix}"

        total = 0
        try:
            with path.open("wb") as destino:
                while True:
                    chunk = origem.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ArquivoGrandeDemaisError(
                            f"Áudio excede o limite de {max_bytes} bytes."
                        )
                    destino.write(chunk)
        except ArquivoGrandeDemaisError:
            path.unlink(missing_ok=True)
            raise
        return path

    def audio_path(self, job_id: str) -> Optional[Path]:
        job_dir = self.job_dir(job_id)
        if not job_dir.is_dir():
            return None
        candidatos = sorted(job_dir.glob("audio.*"))
        return candidatos[0] if candidatos else None
