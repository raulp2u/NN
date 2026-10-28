# Interface de operação simulada

Mostra o modelo operando sobre o gráfico do BTC/USDT: onde comprou ou vendeu a descoberto, stop e alvo, o que aconteceu depois, como cada operação terminou e o saldo em reais. **Nenhuma ordem real é enviada.** Plano completo em [Interface de operacao ao vivo.md](../Planos/Interface%20de%20operacao%20ao%20vivo.md).

## Instalar

Além do ambiente numérico (requirements-torch-cpu.txt e requirements-numeric.txt):

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-interface.txt
```

## Replay do histórico

Exige a coleta de [DADOS_BITCOIN.md](DADOS_BITCOIN.md). Na raiz do projeto:

```powershell
.venv/Scripts/python.exe App/trading_server.py replay --start 2025-11-20 --end 2025-11-27 --usdtbrl-fixo 5.40
```

O navegador abre em `http://127.0.0.1:8000`, com o replay pausado. Use **Iniciar**, **+1 min** e a velocidade (1x a máxima).

- `--model cnn` (padrão) usa o checkpoint `Modelos/numerico_v1`, conferido pelo hash do relatório. `--model medias` usa as médias móveis do quantlab.
- O período que toca o **teste** é recusado sem `--allow-test`; o desbloqueio fica registrado e aparece em vermelho na tela.
- Reais: `--fx-csv` com histórico USDTBRL (`timestamp,close`) converte pelo câmbio de cada minuto. `--usdtbrl-fixo` usa uma cotação fixa, marcada como hipótese. Sem nenhum dos dois, os valores aparecem em USDT.
- Padrões: R$ 50 por operação, compra e venda a descoberto, taxa de 10 bps e slippage de 5 bps por lado, custo de empréstimo de 0,1 bps por hora na venda, saída por tempo em 30 minutos, stop e alvo a 2 desvios da volatilidade. Ajuste com `--stake`, `--no-short`, `--fee-bps`, `--slippage-bps`, `--borrow-bps-hora`, `--horizon`, `--stop-k`, `--target-k` e `--no-stops`.

## Ao vivo (paper trading)

```powershell
.venv/Scripts/python.exe App/trading_server.py live
```

Recebe candles fechados de 1 minuto e o USDTBRL pelo stream público da Binance, sem chave. Ao abrir, carrega imediatamente os últimos 30 minutos de histórico: não há espera de 30 minutos ou uma hora. O último candle atualizado já permite decidir; os anteriores apenas preparam a janela. A CNN recalcula a previsão a cada minuto, usando os últimos 30 candles contínuos, sem restrição a :00 ou :30. Se houver lacunas, aguarda uma janela completa.

Ao reconectar, os minutos perdidos são buscados na API REST apenas para atualizar o modelo, sem executar ordens retroativas. Ordens pendentes são canceladas; uma posição que atravessou a recuperação é encerrada na abertura do primeiro candle atualizado, com motivo `lacuna`. A conexão real com a Binance precisa de validação operacional; os testes usam fontes simuladas.

## O que cada tela mostra

- **Painel:** candles de 1 minuto; setas de entrada (C compra, V venda a descoberto); círculo na saída com o motivo e o resultado; faixa da posição no preço de entrada, verde ou vermelha conforme o resultado líquido; linhas de entrada, empate após custos, alvo e stop; linha tracejada da previsão para 30 minutos; barras inferiores com a influência de cada minuto na previsão (Integrated Gradients). Ao lado: previsão, custo, decisão e motivo, posição aberta e alertas de dados.
- **Diário de operações:** uma linha por operação, com custos separados, previsto contra realizado e colunas retrospectivas (eficiência da saída e "e se"), que só aparecem 30 minutos após a saída. Clique numa linha para ver o detalhe, as decisões durante a operação e o comando para reproduzi-la.
- **Desempenho:** resultado, acerto, fator de lucro, maior queda, custos e intervalo bootstrap de 90% do resultado médio; histograma; previsto contra realizado; erro do modelo contra prever zero; resultados por lado e por tipo de saída.

## Limitações desta versão

- A CNN v1 prevê só o retorno de 30 minutos. **Stop e alvo são provisórios** (múltiplos da volatilidade recente) até existir a cabeça de excursões do plano, e a confiança calibrada aparece como indisponível.
- O checkpoint foi treinado com janelas sem sobreposição. A operação agora usa janelas móveis sobrepostas; os resultados publicados da política anterior não validam essa nova frequência. Previsões consecutivas são dependentes.
- Com stop e alvo no mesmo candle, a simulação assume o stop. Execução na abertura seguinte é idealizada.
- O custo de empréstimo da venda descoberta é hipótese. Sem impostos, impacto ou limite de liquidez.
- Cada sessão grava um log SQLite somente acréscimo em `App/results/sessions/`, ignorado pelo Git.
