import os
import torch
import torchaudio
from speechbrain.inference.speaker import EncoderClassifier

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Nome/fonte do modelo — salve isso junto com cada embedding no banco.
# Se um dia trocarem de modelo, dá pra saber quais embeddings estão
# desatualizados e precisam ser recalculados, em vez de comparar vetores
# incompatíveis silenciosamente.
VERSAO_MODELO = "speechbrain/spkrec-ecapa-voxceleb"

# ---------------------------------------------------------------------------
# PARÂMETROS DE DECISÃO (calibre estes valores testando com seus próprios
# áudios — são os que mais impactam falsos positivos/negativos)
# ---------------------------------------------------------------------------
LIMIAR_IDENTIFICACAO = 0.30   # score mínimo para aceitar um match
MARGEM_MINIMA = 0.05          # diferença mínima entre 1º e 2º colocado
LIMIAR_OUTLIER = 0.45         # similaridade mínima entre trechos do mesmo speaker

# Cache do modelo — carregado sob demanda, na primeira chamada que precisar
# dele, e reaproveitado depois. Isso importa tanto pro worker (Celery)
# quanto pro gerenciador de cadastro de vozes: cada processo carrega o
# modelo pesado só uma vez, mesmo chamando gerar_embedding() várias vezes
# em sequência (ex: cadastrando vários áudios de uma pessoa).
_classifier = None


def carregar_modelo():
    global _classifier
    if _classifier is None:
        _classifier = EncoderClassifier.from_hparams(
            source=VERSAO_MODELO,
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
            run_opts={"device": DEVICE}
        )
    return _classifier


def _carregar_e_normalizar(sinal, fs):
    if fs != 16000:
        sinal = torchaudio.functional.resample(sinal, fs, 16000)

    if sinal.shape[0] > 1:  # estéreo -> mono
        sinal = sinal.mean(dim=0, keepdim=True)

    return sinal.to(DEVICE)


def _normalizar_embedding(emb):
    """Normaliza L2 — essencial antes de tirar médias de embeddings."""
    return emb / (emb.norm(p=2) + 1e-8)


def comparar_embeddings(emb_a, emb_b):
    """Similaridade de cosseno entre dois embeddings (assume que ambos já
    estão normalizados — quem gera embedding via gerar_embedding() ou
    carregar_banco_vozes() já recebe eles normalizados)."""
    return torch.nn.functional.cosine_similarity(
        emb_a.unsqueeze(0), emb_b.unsqueeze(0)
    ).item()


def extrair_embedding(caminho_wav):
    """Extrai o embedding ECAPA-TDNN de um arquivo .wav inteiro (sem normalizar)."""
    classifier = carregar_modelo()
    sinal, fs = torchaudio.load(caminho_wav)
    sinal = _carregar_e_normalizar(sinal, fs)

    with torch.no_grad():
        emb = classifier.encode_batch(sinal)

    return emb.squeeze().cpu()


def gerar_embedding(caminho_audio):
    """
    Ponto de entrada ÚNICO para gerar o embedding de um áudio de cadastro
    (arquivo inteiro, ex: "maria.wav"). É esta função que o GERENCIADOR de
    vozes deve importar e chamar — assim o cadastro usa exatamente a mesma
    extração + normalização que o reconhecimento usa depois em
    aplicar_biometria(), evitando embeddings incompatíveis por causa de
    pré-processamento diferente entre os dois lados.

        from etapa3_biometria import gerar_embedding, VERSAO_MODELO
        embedding = gerar_embedding("maria.wav")
        # salvar no banco: (nome, embedding, VERSAO_MODELO)
    """
    embedding = extrair_embedding(caminho_audio)
    return _normalizar_embedding(embedding)


def extrair_embedding_segmento(caminho_audio, inicio, fim):
    """Extrai o embedding apenas do trecho [inicio, fim] (em segundos) do áudio."""
    classifier = carregar_modelo()

    info = torchaudio.info(caminho_audio)
    sr = info.sample_rate

    frame_offset = max(0, int(inicio * sr))
    num_frames = max(1, int((fim - inicio) * sr))

    sinal, fs = torchaudio.load(
        caminho_audio,
        frame_offset=frame_offset,
        num_frames=num_frames
    )

    sinal = _carregar_e_normalizar(sinal, fs)

    with torch.no_grad():
        emb = classifier.encode_batch(sinal)

    return emb.squeeze().cpu()


def extrair_embedding_concatenado(caminho_audio, segmentos, silencio_s=0.2):
    """
    Concatena fisicamente os trechos de áudio (com um pequeno silêncio entre
    eles) e extrai UM único embedding do resultado. Isso costuma ser mais
    robusto do que fazer a média de vários embeddings extraídos separadamente,
    porque dá ao modelo mais contexto temporal contínuo.
    """
    classifier = carregar_modelo()

    info = torchaudio.info(caminho_audio)
    sr = info.sample_rate

    pedacos = []
    for seg in segmentos:
        frame_offset = max(0, int(seg["start"] * sr))
        num_frames = max(1, int((seg["end"] - seg["start"]) * sr))

        sinal, fs = torchaudio.load(
            caminho_audio,
            frame_offset=frame_offset,
            num_frames=num_frames
        )

        if sinal.shape[0] > 1:
            sinal = sinal.mean(dim=0, keepdim=True)

        pedacos.append(sinal)

        # pequeno silêncio entre trechos para não "colar" fonemas
        pedacos.append(torch.zeros(1, int(silencio_s * fs)))

    concatenado = torch.cat(pedacos, dim=1)
    concatenado = _carregar_e_normalizar(concatenado, fs)

    with torch.no_grad():
        emb = classifier.encode_batch(concatenado)

    return emb.squeeze().cpu()


def carregar_banco_vozes(pasta_vozes="./banco_vozes"):
    """
    Carrega o banco de vozes lendo os embeddings já calculados
    (banco_vozes/<pessoa>/embedding.pt), sem recalcular a partir do áudio.
    """

    banco = {}

    if not os.path.isdir(pasta_vozes):
        print("Pasta de vozes não encontrada!")
        return banco

    for pessoa in os.listdir(pasta_vozes):

        caminho_pessoa = os.path.join(pasta_vozes, pessoa)

        if not os.path.isdir(caminho_pessoa):
            continue

        caminho_embedding = os.path.join(caminho_pessoa, "embedding.pt")

        if not os.path.isfile(caminho_embedding):
            print(f"Aviso: {pessoa} não tem embedding.pt — pulando.")
            continue

        embedding = torch.load(caminho_embedding)
        banco[pessoa] = embedding

        print(f"Voz carregada: {pessoa}")

    return banco


def identificar_speaker(embedding, banco):
    """
    Compara um embedding contra o banco via similaridade de cosseno.
    Só aceita um match se:
      1. o score do melhor candidato ultrapassar LIMIAR_IDENTIFICACAO, e
      2. a diferença para o segundo colocado for >= MARGEM_MINIMA.
    Caso contrário, retorna None (evita "chutar" a pessoa errada).
    """

    if not banco:
        return None, 0.0

    embedding = _normalizar_embedding(embedding)

    scores = {
        nome: comparar_embeddings(embedding, emb_ref)
        for nome, emb_ref in banco.items()
    }

    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    print("\n==============================")
    print("Comparando um speaker:")
    for nome, score in ranking:
        print(f"{nome}: {score:.3f}")

    melhor_nome, melhor_score = ranking[0]
    segundo_score = ranking[1][1] if len(ranking) > 1 else -1.0
    margem = melhor_score - segundo_score

    if melhor_score < LIMIAR_IDENTIFICACAO:
        print(
            f"Rejeitado -> {melhor_nome} teve o maior score ({melhor_score:.3f}) "
            f"mas abaixo do limiar ({LIMIAR_IDENTIFICACAO}). Marcando como "
            f"não identificado."
        )
        return None, melhor_score

    if margem < MARGEM_MINIMA:
        print(
            f"Rejeitado -> {melhor_nome} ({melhor_score:.3f}) muito próximo "
            f"de {ranking[1][0]} ({segundo_score:.3f}), margem={margem:.3f} "
            f"< {MARGEM_MINIMA}. Ambíguo demais para decidir."
        )
        return None, melhor_score

    print(f"Escolhido -> {melhor_nome} ({melhor_score:.3f}, margem={margem:.3f})")

    return melhor_nome, melhor_score


def _remover_outliers(embeddings, segmentos):
    """
    Remove trechos cujo embedding diverge muito dos demais — sinal provável
    de erro de diarização (o trecho pegou fala de outra pessoa, ruído, etc).
    Só atua quando há 3+ trechos, para não descartar dados demais.
    """
    if len(embeddings) < 3:
        return embeddings, segmentos

    embs_norm = [_normalizar_embedding(e) for e in embeddings]
    n = len(embs_norm)

    media_similaridade = []
    for i in range(n):
        sims = [
            comparar_embeddings(embs_norm[i], embs_norm[j])
            for j in range(n) if j != i
        ]
        media_similaridade.append(sum(sims) / len(sims))

    embeddings_ok, segmentos_ok = [], []
    for i, sim_media in enumerate(media_similaridade):
        if sim_media >= LIMIAR_OUTLIER:
            embeddings_ok.append(embeddings[i])
            segmentos_ok.append(segmentos[i])
        else:
            print(
                f"  Trecho {i+1} descartado por outlier "
                f"(similaridade média com os demais = {sim_media:.3f})"
            )

    # nunca descarta tudo — se sobrar vazio, mantém o original
    return (embeddings_ok, segmentos_ok) if embeddings_ok else (embeddings, segmentos)


def aplicar_biometria(resultado_whisper, caminho_audio, banco, duracao_min=1.5,
                       max_segmentos=5, usar_concatenacao=True):
    """
    Para cada SPEAKER encontrado pela diarização:
    - pega os N maiores segmentos válidos (duração >= duracao_min);
    - remove outliers (trechos que provavelmente vazaram de outro speaker);
    - extrai UM embedding representativo (concatenando os trechos, por
      padrão — mais robusto do que fazer média de embeddings separados);
    - identifica a pessoa com threshold + margem de confiança.
    """

    segmentos = resultado_whisper["segments"]

    segmentos_por_speaker = {}
    for seg in segmentos:
        speaker = seg.get("speaker", "Desconhecido")
        segmentos_por_speaker.setdefault(speaker, []).append(seg)

    mapeamento = {}

    for speaker, lista_segmentos in segmentos_por_speaker.items():

        lista_segmentos.sort(key=lambda s: s["end"] - s["start"], reverse=True)

        candidatos = [
            s for s in lista_segmentos
            if (s["end"] - s["start"]) >= duracao_min
        ][:max_segmentos]

        print("\n==========================================")
        print(f"Speaker original: {speaker}")
        print(f"Quantidade de segmentos totais: {len(lista_segmentos)}")
        print(f"Segmentos válidos (>= {duracao_min}s): {len(candidatos)}")
        print("==========================================")

        if not candidatos:
            print("Nenhum trecho com duração suficiente.")
            mapeamento[speaker] = speaker
            continue

        for i, seg in enumerate(candidatos):
            dur = seg["end"] - seg["start"]
            print(f"Trecho {i+1}: {seg['start']:.2f}s - {seg['end']:.2f}s ({dur:.2f}s)")

        if usar_concatenacao:
            # extrai embeddings individuais só para detectar outliers,
            # depois gera o embedding final via concatenação de áudio
            embeddings_individuais = [
                extrair_embedding_segmento(caminho_audio, s["start"], s["end"])
                for s in candidatos
            ]
            _, candidatos_ok = _remover_outliers(embeddings_individuais, candidatos)

            embedding_final = extrair_embedding_concatenado(caminho_audio, candidatos_ok)
        else:
            embeddings = [
                extrair_embedding_segmento(caminho_audio, s["start"], s["end"])
                for s in candidatos
            ]
            embeddings, _ = _remover_outliers(embeddings, candidatos)
            embeddings_norm = [_normalizar_embedding(e) for e in embeddings]
            embedding_final = _normalizar_embedding(
                torch.stack(embeddings_norm).mean(dim=0)
            )

        nome, score = identificar_speaker(embedding_final, banco)

        if nome:
            print(f"Identificado como: {nome} ({score:.3f})")
            mapeamento[speaker] = f"{nome} ({score:.2f})"
        else:
            print(f"Não identificado com confiança (melhor score={score:.3f}).")
            mapeamento[speaker] = speaker

    for seg in segmentos:
        original = seg.get("speaker", "Desconhecido")
        seg["speaker"] = mapeamento.get(original, original)

    return resultado_whisper
