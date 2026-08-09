"""TranscriptFormatter — adapta os segmentos diarizados/identificados
(app.models.result.Segment) em linhas estáveis para os prompts de LLM,
mantendo um índice REVERSÍVEL linha -> segmento (spec seção 7.5).

Sem isso, recuperar speaker/participant_id/time/source_segment_ids de uma
pergunta dependeria do LLM "adivinhar" ou repetir esses dados corretamente —
aqui eles são sempre resolvidos deterministicamente a partir do número da
linha que o próprio LLM referenciou, nunca por inferência do modelo.

Formato de cada linha (spec 7.5):
    1 -> seg_0001 -> [Leandro]: Bom dia.
    2 -> seg_0002 -> [SPEAKER_01]: Tudo bem?
"""
from dataclasses import dataclass
from typing import List, Optional

from app.models.result import Segment


@dataclass
class FormattedLine:
    line_number: int
    segment_id: str
    label: str  # nome (identificado) ou cluster (não identificado)
    text: str
    participant_id: Optional[str]
    speaker: Optional[str]
    start: float
    end: float


@dataclass
class ResolvedLine:
    participant_id: Optional[str]
    speaker: Optional[str]
    time: Optional[float]
    source_segment_ids: List[str]


class TranscriptFormatter:
    def __init__(self, segments: List[Segment]):
        self._lines: List[FormattedLine] = [
            FormattedLine(
                line_number=i,
                segment_id=segment.id,
                label=segment.speaker if segment.identified and segment.speaker else segment.cluster,
                text=segment.text,
                participant_id=segment.participant_id,
                speaker=segment.speaker,
                start=segment.start,
                end=segment.end,
            )
            for i, segment in enumerate(segments, start=1)
        ]

    @property
    def lines(self) -> List[FormattedLine]:
        return list(self._lines)

    def render(self) -> str:
        """Texto para os prompts: uma linha 'N -> seg_XXXX -> [Label]: texto' por segmento."""
        return "\n".join(
            f"{line.line_number} -> {line.segment_id} -> [{line.label}]: {line.text}"
            for line in self._lines
        )

    def get_line(self, line_number: int) -> Optional[FormattedLine]:
        if 1 <= line_number <= len(self._lines):
            return self._lines[line_number - 1]
        return None

    def resolve(self, line_number: int) -> Optional[ResolvedLine]:
        """Resolve uma referência de linha (ex.: `linha_transcricao` do JSON de
        perguntas explícitas) para speaker/participant_id/time/source_segment_ids
        — sem depender do LLM ter acertado esses campos. None se a linha não
        existir (ex.: LLM referenciou um número fora do range)."""
        line = self.get_line(line_number)
        if line is None:
            return None
        return ResolvedLine(
            participant_id=line.participant_id,
            speaker=line.speaker,
            time=line.start,
            source_segment_ids=[line.segment_id],
        )
