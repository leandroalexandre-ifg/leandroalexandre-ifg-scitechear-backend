# banco_vozes (legado — não incluído)

O banco de vozes original (pastas por nome com `audios/` + `embedding.pt`) **não
foi versionado** aqui, por conter binários pesados e dados biométricos.

Na V1, o banco de vozes é **recriado por `participant_id`** pelo `VoiceRepository`
(ver Fase 2 do plano de implementação e a especificação). A estrutura antiga por
nome deve ser migrada por um utilitário não destrutivo `nome -> participant_id`.

Estrutura legada de referência (apenas ilustrativa):

    banco_vozes/
      <nome_da_pessoa>/
        audios/
          amostra1.wav
        embedding.pt
