# Histórico real e janelas de Bitcoin

## Coleta concluída em 27/10/2026

Cobertura efetiva: de 17/08/2017 04:00 UTC até 27/10/2026 00:00 UTC (fim exclusivo; último candle aberto em 26/10 às 23:59 UTC). Foram verificados 136 ZIPs: 110 mensais e 26 diários, totalizando 236.734.172 bytes brutos compactados.

Dos 4.826.719 registros originais, 4.805.101 passaram pelo contrato e 21.618 ficaram em quarentena (0,4479%). Desses descartes, 21.602 têm abertura desalinhada da grade UTC de minuto e 16 têm fechamento fora do intervalo exato esperado. Uma divergência de contrato não prova que os preços originais sejam falsos; optamos por não reinterpretar os horários. A maior concentração está em dezembro de 2017 e fevereiro de 2018.

Foram geradas **160.156 janelas completas**, com 128.124 para treino, 16.016 para validação e 16.016 para teste. A série limpa tem 34 descontinuidades que totalizam 30.179 minutos ausentes na grade, incluindo registros excluídos pela quarentena. Não interpretar esse número como minutos necessariamente ausentes nos arquivos originais. Há 22 blocos parcialmente preenchidos excluídos e 421 candles válidos que não entram em janela completa; blocos inteiramente ausentes não entram nessa contagem de blocos parciais.

Fronteiras temporais UTC:

| Divisão | Primeiro início | Último fim exclusivo |
| --- | --- | --- |
| Treino | 17/08/2017 04:00 | 28/12/2024 16:00 |
| Validação | 28/12/2024 16:00 | 27/11/2025 08:00 |
| Teste | 27/11/2025 08:00 | 27/10/2026 00:00 |

Auditoria concluída: hashes dos quatro CSVs derivados verificados, contagem e ordenação dos 4.805.101 candles e contrato das 160.156 janelas conferidos. Nove janelas (270 minutos) comparadas campo a campo com o histórico normalizado. Os 20 testes automatizados passaram. Isso verifica procedência e transformação; não substitui comparação de preços com outra bolsa ou validação de uma estratégia.

## O que uma janela contém

Cada snapshot cobre 30 minutos e guarda 30 candles de um minuto. Para cada minuto, preserva abertura, máxima, mínima, fechamento e volume. Uma linha do CSV contém 150 valores OHLCV e quatro campos de identificação. Não é uma imagem, nem um único candle de 30 minutos.

Os mesmos dados permitem desenhar uma linha com os fechamentos, mostrar 30 candles de um minuto ou agrupar em seis candles de cinco minutos. Não permitem reconstruir a ordem das negociações dentro do minuto, candles de segundos ou o spread. Para esses experimentos, será necessário obter negociações individuais ou dados de maior resolução.

## Fonte e integridade

Fonte primária: [Binance Public Data](https://github.com/binance/binance-public-data). Par BTCUSDT, mercado à vista. Preços em USDT, volume em BTC. É o histórico deste par nesta bolsa desde sua listagem; não é o histórico global de Bitcoin desde 2009. Arquivos podem ser corrigidos posteriormente pelo publicador, por isso os ZIPs originais e hashes são preservados.

O coletor consulta o catálogo oficial, baixa ZIPs mensais completos e complementa com arquivos diários disponíveis antes da data de corte. Verifica SHA-256 contra cada `.CHECKSUM` publicado. Converte a mudança de timestamps de milissegundos para microssegundos em 2025. Não preenche lacunas, não corrige preços e não cria janelas incompletas.

## Arquivos em App/data/bitcoin

- `btc_usdt_1m.csv`: histórico numérico normalizado, UTC, cabeçalho timestamp/open/high/low/close/volume. Timestamp é a abertura.
- `snapshots_30m.csv`: uma linha por janela completa e sem sobreposição. `open_00` até `volume_29` seguem ordem cronológica. Minuto 00 é o primeiro, não o mais recente.
- `splits.csv`: associa window_id a train/validation/test em ordem temporal, nas proporções aproximadas 80/10/10.
- `preview_snapshots.csv`: nove janelas distribuídas uniformemente pelo histórico, geradas pela auditoria para inspeção rápida.
- `preview.svg`: as mesmas nove janelas em candles de um minuto e linha de fechamentos, com escala local explícita por painel.
- `manifest.json`: fontes, hashes, unidades, contagens, cobertura efetiva, lacunas e fronteiras das divisões.
- `sources.json`: proveniência da coleta; `raw/`: ZIPs e checksums originais.
- `audit.json`: resultado da auditoria dos arquivos derivados e correspondência de amostras com o histórico.
- `quarantine.csv`: registros que falharam no contrato OHLCV/tempo, com fonte, linha, motivo e conteúdo original. São excluídos dos dados normalizados e das janelas; ZIPs originais são preservados. Duplicatas e inversões temporais interrompem a geração para investigação.

Exemplo: janela `[12:00, 12:30)` contém candles abertos de 12:00 a 12:29. Todos os valores só podem ser usados após 12:30 UTC. O campo `available_at_utc` representa esse fim exclusivo idealizado; latência real da publicação não foi medida.

## Treinamento e seleção

Janelas começam na grade UTC a cada meia hora. Assim, há amostras de altas, quedas e lateralizações sem selecionar retrospectivamente picos/fundos. A distribuição real do mercado é preservada; não houve balanceamento por regime.

Ainda não há rótulos de comprar/vender nem retorno futuro anexado. Antes de treinar, definir horizonte e alvo, separar seus dados das entradas e excluir exemplos cujos rótulos ultrapassem a fronteira de cada divisão. Normalização deve ser ajustada só no treino ou usar uma regra causal por janela. Os preços originais foram preservados para permitir comparações de representações e pesos. Evitar consultar o teste durante experimentos.

## Reproduzir

Na raiz do projeto:

```powershell
python App/bitcoin_data.py --as-of 2026-10-27
python App/audit_bitcoin_data.py App/data/bitcoin
python -m unittest discover -s App -p "test_*.py" -v
```

O coletor não sobrescreve um dataset com manifesto concluído. Para uma nova versão use `--out App/data/bitcoin_nova_versao`. Se houve interrupção antes do manifesto, os ZIPs já baixados são reutilizados após nova verificação do checksum. O conjunto e os resultados são locais e ficam ignorados pelo Git; copiar o projeto via Git não copia os dados.
