# QuantLab

Para os dados reais de Bitcoin e janelas de 30 minutos, consulte [DADOS_BITCOIN.md](DADOS_BITCOIN.md). O exemplo abaixo continua sendo artificial para demonstração isolada do simulador.

Protótipo local em Python 3.10+ (verificado em 3.14), somente biblioteca padrão. Analisa candles numéricos e emite COMPRAR, VENDER ou AGUARDAR por médias móveis. Não contém modelo aprendido. VENDER encerra uma posição comprada; não abre venda descoberta.

Na raiz do projeto, PowerShell:

```powershell
python App/make_example.py
python App/quantlab.py App/examples/synthetic.csv --asset SINTETICO --provenance "Serie artificial demonstrativa" --out App/results/demo
python -m unittest discover -s App -p "test_*.py" -v
```

Abra App/results/demo/chart.svg para visualizar. report.json contém parâmetros, hash SHA-256 do CSV, fonte declarada, sinais e métricas; equity.csv contém a trilha de caixa, unidades e patrimônio. Dados sintéticos servem apenas para verificar funcionamento.

Para CSV real, use o mesmo comando substituindo o caminho, ativo e procedência. O arquivo deve ter cabeçalho `timestamp,open,high,low,close,volume`, ponto decimal, timestamp ISO 8601 em UTC explícito (`Z` ou `+00:00`), indicando **abertura** do candle. Por padrão, os intervalos devem ser exatamente uma hora; altere `--interval-seconds` para outra periodicidade. Só inclua candles fechados. Dados brutos da bolsa precisam de conversão para esse contrato; não há importador automático nesta entrega.

Parâmetros: `--fast 5 --slow 20 --initial 10000 --fee-bps 10 --slippage-bps 5`. Um bps equivale a 0,01%. Defaults são hipóteses, não tarifas verificadas de uma corretora.

O sinal usa o fechamento do candle t, e só executa na abertura de t+1. A simulação supõe preenchimento integral e usa todo o caixa em cada entrada, portanto não implementa dimensionamento de risco. Taxa incide no valor negociado; slippage aumenta o preço de compra e reduz o de venda. Não há posições vendidas, impostos, juros, latência, limite de liquidez ou impacto de mercado.

Patrimônio intermediário é marcado ao fechamento. O relatório também calcula liquidação hipotética ao último fechamento com custos de saída; essa liquidação é uma convenção de avaliação e não uma ordem da estratégia. Drawdown inclui esse valor terminal. O último sinal é calculado a partir da posição antes dessa liquidação hipotética. A referência de compra e manutenção entra na primeira abertura elegível após o aquecimento e usa os mesmos custos. Caixa rende zero na referência. A trilha inclui aquecimento sem posições.

O gráfico mostra fechamentos; marcadores identificam o candle da execução, e não o preço de preenchimento. Lucro em uma série artificial ou em um histórico não comprova lucro futuro. Nenhum estudo com histórico real ou validação fora da amostra foi realizado nesta entrega.
