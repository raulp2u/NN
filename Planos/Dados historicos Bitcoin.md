# Histórico de Bitcoin e snapshots

Data: 27/10/2026. Solicitação: obter histórico confiável e snapshots de 30 minutos em CSV para treinamento.

## Decisões e execução

1. Usar arquivos públicos primários de BTCUSDT spot da Binance; identificar explicitamente que USDT não é USD e que dados representam uma bolsa, não todo o Bitcoin desde sua criação.
2. Consultar o catálogo, baixar arquivos mensais completos disponíveis e verificar SHA-256 publicado. Preservar ZIPs e checksums com manifesto de origem; não usar credenciais.
3. O usuário confirmou janelas de 30 minutos para experimentar linha, candles e pesos. Usar OHLCV de um minuto (30 amostras completas por janela), preservando dados brutos. Essa resolução não reconstrói movimentos dentro do minuto. Formar janelas em grade UTC, a cada 30 minutos, sem sobreposição; manter histórico de um minuto para experimentos posteriores com outros passos.
4. Normalizar timestamps UTC (milissegundos/microssegundos conforme a fonte), verificar OHLCV, ordem, duplicatas e lacunas. Nunca interpolar silenciosamente nem formar janelas atravessando lacunas.
5. Salvar CSVs e metadados em App/data/bitcoin. Selecionar recortes em grade temporal, sem escolher picos e fundos com conhecimento do futuro. Cada exemplo deve conter somente seu passado.
6. Separar cronologicamente treino, validação e teste; evitar exemplos sobrepostos nas fronteiras. Não treinar o modelo nesta etapa.
7. Testar conversão de timestamps, integridade, formação de intervalos e ausência de futuro. Entregar cobertura efetiva, contagens, lacunas e caminhos reais. Sem commit.

## Contrato dos snapshots

Uma linha por janela: início, fim exclusivo/disponibilidade, identificador e 30 grupos open/high/low/close/volume em ordem cronológica. Divisão temporal em splits.csv, associada pelo identificador, para evitar duplicação dos dados. Preços em USDT, volume em BTC. Sem normalização global, imagem, rótulo futuro ou seleção retrospectiva de formas. Divisão cronológica 80%/10%/10% por número de janelas completas; é uma organização inicial a preservar antes de escolher modelos. Dados e snapshots grandes ficam em App/data, ignorado pelo Git. Manifesto registra arquivos, hashes, lacunas, descartes e fronteiras. Acrescentar dias completos disponíveis de outubro até 26/10/2026; não incluir dia corrente parcial.

## Achado durante validação

Os 136 ZIPs passaram no checksum, mas o histórico de setembro de 2017 contém fechamento fora do padrão exato de um minuto. Decisão: preservar registro original em quarentena com motivo e excluir a janela afetada, sem ajustar o horário silenciosamente. Aplicar a mesma regra OHLCV/tempo em todo o conjunto e reportar os descartes. Duplicatas ou inversões temporais continuam sendo erros fatais.

## Resultado concluído

- 136 fontes verificadas: 110 meses (2017-08 a 2026-09) e 26 dias de outubro de 2026.
- 4.826.719 linhas brutas; 4.805.101 candles aceitos; 21.618 em quarentena. Motivos: 21.602 aberturas fora da grade UTC e 16 fechamentos fora do contrato exato. Registros fora do contrato não são automaticamente preços falsos; não reinterpretamos a amostragem antiga.
- 160.156 janelas de 30 minutos: treino 128.124, validação 16.016, teste 16.016.
- Cobertura: 17/08/2017 04:00 UTC a 27/10/2026 00:00 UTC exclusivo. Série limpa com 34 descontinuidades e 30.179 minutos ausentes na grade, incluindo exclusões da quarentena.
- App/data/bitcoin contém histórico 1m, snapshots, índice de divisões, quarentena, manifesto, fontes e arquivos brutos. Dados grandes ignorados pelo Git conforme previsto.
- Auditoria concluída: quatro hashes de CSVs, contagens, ordenação e contrato de todas as janelas; nove janelas/270 minutos comparados campo a campo. Prévia CSV e SVG gerada. Vinte testes passaram.
- Código: App/bitcoin_data.py e App/audit_bitcoin_data.py. Contrato, reprodução e números documentados em App/DADOS_BITCOIN.md.
- Sem treinamento, rótulos futuros ou commit nesta etapa. Próxima decisão: definir o que prever e em qual horizonte antes de ajustar pesos/modelos. Não usar o conjunto de teste para escolher representação.

## Fontes consultadas

- https://github.com/binance/binance-public-data — formato, checksums e alterações dos arquivos.
- https://data.binance.vision/ — arquivos primários.

Checksum comprova correspondência ao arquivo publicado; não comprova exatidão de cada negociação. Falhas conhecidas e alterações posteriores precisam permanecer rastreáveis pelo hash.
