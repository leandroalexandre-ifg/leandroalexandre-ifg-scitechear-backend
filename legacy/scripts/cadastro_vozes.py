# cadastro_vozes.py
import os, sys, shutil, torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etapa3_biometria import extrair_embedding,_normalizar_embedding

def cadastrar_ou_atualizar_pessoa(nome,pasta_amostras_novas,banco_vozes="./vozes_cadastradas"):
    pasta_pessoa=os.path.join(banco_vozes,nome)
    pasta_audios=os.path.join(pasta_pessoa,"audios")
    os.makedirs(pasta_audios,exist_ok=True)
    for arq in sorted(os.listdir(pasta_amostras_novas)):
        if arq.endswith(".wav"):
            shutil.copy2(os.path.join(pasta_amostras_novas,arq),os.path.join(pasta_audios,arq))
    wavs=[a for a in sorted(os.listdir(pasta_audios)) if a.endswith(".wav")]
    embeddings=[]
    for arq in wavs:
        emb=_normalizar_embedding(extrair_embedding(os.path.join(pasta_audios,arq)))
        embeddings.append(emb)
    emb=torch.stack(embeddings).mean(dim=0)
    emb=_normalizar_embedding(emb)
    out=os.path.join(pasta_pessoa,"embedding.pt")
    torch.save(emb,out)
    print("Embedding salvo em:",out)

if __name__=="__main__":
    cadastrar_ou_atualizar_pessoa(input("Nome: "),input("Pasta com WAVs: "))
