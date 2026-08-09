import os
import json

from etapa2b_diarizacao import diarizar
from etapa3_biometria import carregar_banco_vozes, aplicar_biometria


# =========================
# CONFIGURAÇÃO
# =========================

ENTRADA       = "./audios_brutos"
TRANSCRICOES  = "./transcricoes"
SAIDA         = "./resultados"
VOZES         = "./banco_vozes"

os.makedirs(SAIDA, exist_ok=True)


# =========================
# BANCO DE VOZES
# =========================

print("Carregando banco de vozes cadastradas...")
banco_vozes = carregar_banco_vozes(VOZES)

if not banco_vozes:
    print(
        "Aviso: nenhuma voz cadastrada encontrada. "
        "Falantes ficarão como SPEAKER_00, SPEAKER_01..."
    )


# =========================
# PROCESSAMENTO
# =========================

for arquivo in sorted(os.listdir(ENTRADA)):

    if not arquivo.endswith(".wav"):
        continue

    nome_base = arquivo.replace(".wav", "")
    caminho_audio = os.path.join(ENTRADA, arquivo)
    caminho_transcricao = os.path.join(TRANSCRICOES, nome_base + ".json")

    print(f"\nProcessando: {arquivo}")

    if not os.path.exists(caminho_transcricao):
        print(f"  Erro: transcrição não encontrada em {caminho_transcricao} — pulando.")
        continue

    try:
        with open(caminho_transcricao, "r", encoding="utf-8") as f:
            resultado_transcricao = json.load(f)

        # =========================
        # DIARIZAÇÃO
        # =========================

        resultado = diarizar(caminho_audio, resultado_transcricao)

        # =========================
        # BIOMETRIA
        # =========================

        resultado = aplicar_biometria(resultado, caminho_audio, banco_vozes)

        # =========================
        # SALVAR JSON
        # =========================

        caminho_saida = os.path.join(SAIDA, nome_base + "_diarizado.json")
        with open(caminho_saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        print(f"  Arquivo salvo: {caminho_saida}")

    except Exception as e:
        print(f"  Erro ao processar {arquivo}: {e}")


print("\n====================")
print("Finalizado")
print("====================")
