import os
import torch
from pyannote.audio import Pipeline

# ============================================================
# TOKEN DO HUGGING FACE
# ============================================================
# O token deve ser definido como variável de ambiente antes da
# execução do programa. Nunca deixe o token escrito diretamente
# no código.
#
# Linux/Mac:
#   export HF_TOKEN="seu_token"
#
# Windows (PowerShell):
#   $env:HF_TOKEN="seu_token"
#
# Notebook:
#   os.environ["HF_TOKEN"] = "seu_token"
# ============================================================

HF_TOKEN = os.environ.get("HF_TOKEN")

if not HF_TOKEN:
    raise RuntimeError(
        "A variável de ambiente HF_TOKEN não foi encontrada."
    )

# ============================================================
# CONFIGURAÇÃO DA DIARIZAÇÃO
# ============================================================
# Em vez de fixar exatamente quantos participantes existem,
# utilizamos uma faixa mínima e máxima. Assim, o Pyannote pode
# estimar automaticamente a quantidade de falantes.
#
# Caso seja necessário informar um número exato de participantes,
# basta passar o parâmetro num_speakers na função diarizar().
# ============================================================

MIN_SPEAKERS = 4
MAX_SPEAKERS = 7

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1",
    token=HF_TOKEN
)

if torch.cuda.is_available():
    pipeline.to(torch.device("cuda"))


def diarizar(caminho_audio, resultado_whisper,
             num_speakers=None,
             min_speakers=MIN_SPEAKERS,
             max_speakers=MAX_SPEAKERS):
    """
    Executa a diarização e associa um speaker a cada segmento
    gerado pelo Whisper utilizando a maior sobreposição temporal.
    """

    if num_speakers is not None:
        diarization_output = pipeline(
            caminho_audio,
            num_speakers=num_speakers
        )
    else:
        diarization_output = pipeline(
            caminho_audio,
            min_speakers=min_speakers,
            max_speakers=max_speakers
        )

    # ============================================================
    # DIAGNÓSTICO DA DIARIZAÇÃO
    # ============================================================
    # Exibe os speakers encontrados e o tempo total de fala de
    # cada um. Clusters muito pequenos podem indicar ruído ou
    # trechos curtos de fala.
    # ============================================================

    diarization = diarization_output.speaker_diarization

    segmentos_diarizados = []
    duracao_por_speaker = {}

    for segment, _, speaker in diarization.itertracks(yield_label=True):
        segmentos_diarizados.append({
            "start": segment.start,
            "end": segment.end,
            "speaker": speaker
        })

        duracao = segment.end - segment.start
        duracao_por_speaker[speaker] = (
            duracao_por_speaker.get(speaker, 0) + duracao
        )

    print("\nSpeakers encontrados pelo Pyannote:")
    print(set(duracao_por_speaker.keys()))
    print("Quantidade:", len(duracao_por_speaker))

    print("\nTempo total de fala por speaker:")

    for speaker, tempo in sorted(
        duracao_por_speaker.items(),
        key=lambda item: -item[1]
    ):
        print(f"  {speaker}: {tempo:.1f}s")

        if tempo < 15:
            print("    Aviso: pouca duração de fala para este speaker.")

    # ============================================================
    # ASSOCIA O SPEAKER AOS SEGMENTOS DO WHISPER
    # ============================================================
    # Para cada segmento transcrito, é escolhido o speaker que
    # possui a maior sobreposição de tempo.
    # ============================================================

    for segmento in resultado_whisper["segments"]:
        inicio = segmento["start"]
        fim = segmento["end"]

        melhor_speaker = "Desconhecido"
        maior_overlap = 0

        for diarizado in segmentos_diarizados:
            overlap = min(diarizado["end"], fim) - max(
                diarizado["start"], inicio
            )

            if overlap > maior_overlap:
                maior_overlap = overlap
                melhor_speaker = diarizado["speaker"]

        segmento["speaker"] = melhor_speaker

    return resultado_whisper
