# Primeiro treinamento numérico — 27/10/2026

Foi implementado e treinado o primeiro ramo numérico: 30 minutos de entrada para prever o retorno logarítmico dos próximos 30 minutos. A CNN teve melhora pequena sobre a previsão zero. Esta entrega valida o pipeline; não demonstra estratégia de negociação pronta.

## Dados e exclusões

Das 160.156 janelas originais, foram aceitos **160.119 exemplos supervisionados**:

| Divisão | Exemplos |
| --- | ---: |
| Treino | 128.089 |
| Validação | 16.015 |
| Teste retrospectivo | 16.015 |

Exclusões: 34 janelas sem continuidade durante o horizonte futuro, duas que ultrapassariam a fronteira entre conjuntos e a última sem dados futuros. Os preços futuros são metadados de supervisão/avaliação, separados dos oito canais de entrada. Normalização dos canais e do alvo ajustada exclusivamente no treino. Nenhum rótulo atravessa lacuna ou fronteira.

O histórico já havia sido explorado na análise de extremos. O período chamado teste é uma avaliação retrospectiva; as escolhas baseadas nesta pesquisa precisam de período novo intocado ou acompanhamento prospectivo para validação independente.

## Modelos e protocolo

Referências: previsão zero e regressão Ridge com alpha=10. Modelo neural: CNN 1D de 2.513 parâmetros, duas convoluções 8→16→32 com kernel 3, GELU, pooling médio e MLP 32→16→1. Oito canais representam OHLC relativo à primeira abertura, log1p(volume), primeira e segunda diferenças do log-fechamento e corpo da vela. As posições iniciais sem suporte de derivada recebem zero, sem buscar observações futuras.

Uma configuração e semente 42, CPU, AdamW lr=0,001, weight_decay=0,0001, batch 512, limite de 20 épocas e parada após quatro épocas sem melhora na validação. Treinamento terminou na época 6; checkpoint selecionado na época 2. Modelo e checkpoint foram selecionados pelo MSE de validação antes de calcular as métricas de teste. Nenhum hiperparâmetro foi alterado para melhorar o teste.

## Qualidade da previsão

Alvo em retorno logarítmico decimal; MSE e MAE abaixo não são percentuais de lucro.

| Modelo | MSE validação | MSE teste retrospectivo | MAE teste | Acerto direcional teste |
| --- | ---: | ---: | ---: | ---: |
| Previsão zero | 1,145717e-5 | 1,055777e-5 | 0,002066485 | Não se aplica: sem direção |
| Ridge | 1,159940e-5 | 1,064264e-5 | 0,002079671 | 50,58% |
| CNN | 1,141972e-5 | 1,054743e-5 | 0,002066190 | 50,31% |

A CNN foi selecionada pela validação. Sua redução relativa de MSE é de aproximadamente **0,327% na validação e 0,098% no teste** contra previsão zero. R² do teste é aproximadamente 0,000973. A melhora é pequena e sua significância estatística não foi demonstrada. Acerto direcional perto de 50% não sustenta alegação de vantagem de negociação.

## Simulação secundária após custos

Política pré-especificada: comprar à vista na abertura seguinte se a previsão exceder a barreira de custo; encerrar após 30 minutos. Cada operação usa todo o capital disponível, sem alavancagem. Taxa de 10 bps e slippage de 5 bps por lado são hipóteses, não custos de execução verificados. A execução na abertura exata é idealizada; não há imposto, impacto, limite de volume, spread dinâmico ou latência.

| Modelo | Operações completas | Retorno líquido simulado |
| --- | ---: | ---: |
| Previsão zero / caixa | 0 | 0,00% |
| Ridge | 3 | +0,47% |
| CNN | 2 | +4,69% |

A referência de compra e manutenção no período teve retorno terminal de −12,54%, com custos de entrada e saída. **Duas operações não permitem concluir robustez ou rentabilidade futura.** O drawdown calculado nos fechamentos dos horizontes foi zero para a CNN porque ambas as operações terminaram positivas; isso não significa ausência de perdas intraperíodo. O limiar não foi otimizado pelo resultado financeiro.

Na revisão da contabilidade, a aproximação inicial do custo foi substituída pela expressão exata `log((1+taxa)/(1-taxa)) + log((1+slippage)/(1-slippage))`. As previsões e pesos ficaram congelados; foi verificado que a correção não mudou nenhuma operação ou retorno nesta execução. A revisão está registrada no JSON, e as cinco operações dos modelos estão em trades_test_retrospective.csv.

## Auditoria e reprodução

Foram recalculados os 160.119 alvos, conferidas as fronteiras e os parâmetros de normalização e reproduzidas as 16.015 previsões de teste a partir do checkpoint salvo. Hashes de datasets e artefatos e contabilidade das operações conferidos. A suíte local passou com **43 testes**. O GitHub Actions foi atualizado para instalar as dependências numéricas CPU nos testes de Python 3.12 e 3.14.

Arquivos pequenos desta execução são publicados aqui: report.json, dataset_manifest.json, audit.json, history.csv, trades_test_retrospective.csv e training.png. Checkpoint, Ridge, scalers e configuração estão em ../../Modelos/numerico_v1. Dados Parquet, previsões completas e TensorBoard continuam em App/data e App/results locais, ignorados pelo Git.

Após instalar requirements-torch-cpu.txt, requirements-numeric.txt e requirements-dev.txt, na raiz:

```powershell
.venv/Scripts/python.exe App/supervised_data.py
.venv/Scripts/python.exe App/train_numeric.py
.venv/Scripts/python.exe App/audit_numeric.py
.venv/Scripts/python.exe -m unittest discover -s App -p "test_*.py" -v
```

É necessário ter reproduzido primeiro a coleta de Bitcoin. O dataset e o treinador não sobrescrevem execuções concluídas; para repetir, use novas pastas com --out e ajuste --data. O tempo de cada época variou em torno de 2,2 segundos na máquina local; isso não inclui coleta, preparação ou imports.

O ramo de notícias e a fusão multimodal ainda não foram treinados. Seu desenvolvimento exige um corpus temporal próprio; o catálogo retrospectivo de doze fontes não serve como notícias conhecidas antes dos movimentos.
