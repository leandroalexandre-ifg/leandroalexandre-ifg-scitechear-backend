import os
import statistics
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
LIMIAR_MINIMO_ABSOLUTO = 0.40  # piso de sanidade sobre o score de cosseno bruto
LIMIAR_ZSCORE = 2.0             # quantos desvios-padrão acima do cohort de impostores
MARGEM_ZSCORE = 0.5             # margem mínima em z-score entre 1º e 2º colocado
TOP_N_COHORT = 3                # nº de impostores mais parecidos usados no cohort
                                 # (banco pequeno, 4-10 pessoas — 3 funciona bem
                                 # tanto no piso quanto no teto dessa faixa)

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


def _asnorm_scores(scores_brutos):
    """
    Recebe {nome: score_cosseno_bruto} e retorna {nome: score_normalizado}.

    Para cada candidato, o cohort de impostores é formado pelas OUTRAS vozes
    do banco (todo mundo menos o próprio candidato), usando só os
    TOP_N_COHORT mais parecidos (por isso "adaptive"). O resultado é um
    z-score: o quanto o candidato se destaca do que um impostor típico
    teria — em vez de um valor de cosseno absoluto, que não separa bem
    vozes parecidas (ex: dois homens com timbre próximo).
    """
    nomes = list(scores_brutos.keys())
    scores_norm = {}

    for candidato in nomes:
        impostores = [scores_brutos[n] for n in nomes if n != candidato]

        if len(impostores) < 2:
            # cohort pequeno demais pra normalizar com confiança —
            # cai de volta pro score bruto
            scores_norm[candidato] = scores_brutos[candidato]
            continue

        cohort = sorted(impostores, reverse=True)[:TOP_N_COHORT]
        media = statistics.mean(cohort)
        desvio = statistics.pstdev(cohort) or 1e-6

        scores_norm[candidato] = (scores_brutos[candidato] - media) / desvio

    return scores_norm


def identificar_speaker(embedding, banco):
    """
    Compara um embedding contra o banco usando AS-Norm (Adaptive Score
    Normalization) em vez de um limiar de cosseno fixo.

    Só aceita um match se:
      1. o z-score do melhor candidato ultrapassar LIMIAR_ZSCORE (ele se
         destaca claramente dos impostores mais parecidos), e
      2. a diferença de z-score para o segundo colocado for >= MARGEM_ZSCORE
         (não está ambíguo entre dois candidatos), e
      3. o score de cosseno BRUTO do melhor candidato ainda ultrapassa
         LIMIAR_MINIMO_ABSOLUTO — um piso de sanidade para não aceitar um
         match "só porque é o menos ruim" quando ninguém no banco realmente
         se parece com o trecho.
    Caso contrário, retorna None (evita "chutar" a pessoa errada).
    """

    if not banco:
        return None, 0.0

    embedding = _normalizar_embedding(embedding)

    scores_brutos = {
        nome: comparar_embeddings(embedding, emb_ref)
        for nome, emb_ref in banco.items()
    }

    scores_z = _asnorm_scores(scores_brutos)
    ranking = sorted(scores_z.items(), key=lambda x: x[1], reverse=True)

    print("\n==============================")
    print("Comparando um speaker (AS-Norm):")
    for nome, z in ranking:
        print(f"{nome}: z={z:.3f} (bruto={scores_brutos[nome]:.3f})")

    melhor_nome, melhor_z = ranking[0]
    melhor_bruto = scores_brutos[melhor_nome]
    segundo_z = ranking[1][1] if len(ranking) > 1 else -99.0
    margem = melhor_z - segundo_z

    if melhor_bruto < LIMIAR_MINIMO_ABSOLUTO:
        print(
            f"Rejeitado -> {melhor_nome} tem z-score alto mas score bruto "
            f"({melhor_bruto:.3f}) abaixo do piso de sanidade "
            f"({LIMIAR_MINIMO_ABSOLUTO}). Provavelmente ninguém do banco "
            f"bate com esse trecho."
        )
        return None, melhor_bruto

    if melhor_z < LIMIAR_ZSCORE:
        print(
            f"Rejeitado -> {melhor_nome} teve z={melhor_z:.3f}, abaixo do "
            f"limiar ({LIMIAR_ZSCORE}). Marcando como não identificado."
        )
        return None, melhor_bruto

    if margem < MARGEM_ZSCORE:
        print(
            f"Rejeitado -> {melhor_nome} (z={melhor_z:.3f}) muito próximo "
            f"de {ranking[1][0]} (z={segundo_z:.3f}), margem={margem:.3f} "
            f"< {MARGEM_ZSCORE}. Ambíguo demais para decidir."
        )
        return None, melhor_bruto

    print(f"Escolhido -> {melhor_nome} (z={melhor_z:.3f}, margem={margem:.3f})")

    return melhor_nome, melhor_bruto


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
