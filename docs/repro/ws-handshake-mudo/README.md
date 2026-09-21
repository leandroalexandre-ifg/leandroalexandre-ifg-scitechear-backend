# Repro — o handshake mudo do WebSocket sob TLS

Material de uma investigação de 21/09/2026. O sintoma: através do proxy TLS,
um cliente WebSocket ficava **pendurado no handshake** — nem o `101`, nem o
frame de close. O que se suspeitava: um defeito do Caddy.

**Conclusão, medida: o defeito é do cliente `websockets.sync` (Python), não do
Caddy e não da API.** Pelo mesmo proxy, no mesmo instante, um cliente TLS cru
de stdlib entrega 20/20 e o cliente **assíncrono** do mesmo pacote entrega
15/15. O `scripts/smoke_contrato.py` usava o síncrono, e era ele quem
fabricava a falha. Foi corrigido para o assíncrono.

A seção correspondente de `docs/PENDENCIAS.md` tem a história completa, todas
as hipóteses descartadas e as decisões. Aqui ficam os artefatos para quem
quiser refazer a medição.

## A lição de método, que vale mais que o bug

O defeito **é intermitente** — entre ~5% e ~75% de sucesso conforme a rodada.
Duas gerações de diagnóstico erraram porque mediram **uma amostra por célula**
e leram a tabela como se fosse determinística: a primeira concluiu "é o
caminho TLS", a segunda "é TLS **e** `permessage-deflate`". Com n=30 as
colunas de deflate ficam idênticas, e a segunda tese evapora.

**Numa falha intermitente, uma matriz de isolamento com n=1 não isola nada.**
Antes de escrever "é X e não Y" numa tabela, meça quantas vezes X se repete.

## Arquivos

| arquivo | o que é |
|---|---|
| `matriz_clientes.py` | **o artefato principal**: compara os três clientes (sync, async, cru) contra o mesmo alvo, n vezes cada. É o que sustenta a conclusão. |
| `upstream_ws.py` | upstream WebSocket mínimo (stdlib): responde `101` e fecha na hora com 4401. Aceita atraso em ms antes do close, para testar se o close imediato importa (não importa). |
| `Caddyfile.repro` | dois sites descartáveis em loopback — um com `tls internal`, um em HTTP puro — para medir sem tocar na produção. |
| `cliente_ws.py` | cliente cru de stdlib: mostra os bytes do handshake na mão. |
| `matriz.py` | a matriz original de 3 caminhos × 2 modos de compressão, **com n=1 por célula**. Fica como evidência de como o diagnóstico errado foi produzido. |
| `RELATO-CADDY-REFUTADO.md` | o relato que chegou a ser preparado para o projeto Caddy. **NÃO ENVIAR** — o cabeçalho explica por quê. |

## Como refazer a medição principal

Requer o pacote `websockets` (use o venv do projeto, que tem o 17.1). Pode ser
rodado contra o proxy de produção — é só leitura, com token inválido:

```bash
cd docs/repro/ws-handshake-mudo

.venv/bin/python matriz_clientes.py \
    "wss://200.17.57.229/ws/x?token=invalido" 20 \
    --cafile ../../../deploy/scitechear-root-ca.crt
```

**Olhe o teto de tempo que ele imprime antes de começar.** Cada tentativa que
pendura custa até 2× o timeout (handshake + `recv`), então um lote grande
leva dezenas de minutos: n=20 nos três clientes chega a 12 min se tudo
pendurar. O `--orcamento` (default 180 s) interrompe o lote e reporta só o que
foi medido. Isto já custou uma sessão interrompida — não repita.

Esperado: `async` e `cru` em 100%, `sync` instável.

## Medir sem tocar na produção

```bash
python3 upstream_ws.py 18099 fecha &          # upstream que fecha na hora
export REPRO_STORAGE=$(mktemp -d)             # storage próprio: a CA de
caddy run --config Caddyfile.repro &          # produção não pode ser tocada
python3 matriz_clientes.py "wss://localhost:18100/ws/x" 20
```

O site em `18100` termina TLS; o de `18101` é HTTP puro, como controle. Ambos
em loopback com `bind` explícito — sem `bind`, o Caddy sobe em todas as
interfaces, e nesta máquina isso é a internet.

## Armadilhas de medição (cada uma custou uma volta)

- **O cliente cru não pede `permessage-deflate`.** Comparar o cru com o sync
  compara duas coisas ao mesmo tempo; foi assim que a extensão entrou na tese
  como se fosse causa.
- **`with connect(...)` sem `recv()` sempre "conecta".** O close só aparece no
  `recv`: um teste que abre e fecha o contexto passa mesmo com o defeito.
- **O ponto onde morre varia**: às vezes o `101` não chega, às vezes chega e só
  o close some. Não conclua de uma execução.
- **Não é atraso.** Com `open_timeout=25` o cliente síncrono trava os 25 s.
- **`pkill -f upstream_ws` mata o próprio shell**, porque o padrão casa a
  linha de comando do bash que o executa. Use o PID.

## Versões medidas

Caddy 2.11.4 e 2.10.0 (falham igual), Ubuntu 24.04, kernel 6.8, Python 3.12,
`websockets` 17.1, uvicorn como upstream real e o upstream de stdlib acima.
