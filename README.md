# NNModel / QuantLab

Laboratório de pesquisa financeira com histórico de Bitcoin, janelas de 30 minutos e análise de movimentos extremos. O primeiro ramo neural numérico foi implementado e treinado; a integração de notícias e a fusão multimodal continuam em desenvolvimento.

- [Como executar e interpretar o protótipo](App/README.md).
- [Histórico real de Bitcoin e snapshots de 30 minutos](App/DADOS_BITCOIN.md).
- [Maiores derivadas e relação documental com notícias](Base%20de%20conhecimento/13%20-%20Derivadas%20extremas%20e%20noticias%20do%20Bitcoin.md).
- [Arquitetura neural definida e ferramentas](Planos/Arquitetura%20neural%20e%20ferramentas.md).
- [Primeiro treinamento: dados, métricas e limitações](Relatorios/numerico_v1/README.md).
- [Interface de operação simulada: replay e paper trading](App/INTERFACE.md).
- [Definição da ferramenta e etapas de pesquisa](Planos/Ferramenta%20quantitativa.md).
- [Execução inicial](Planos/Execucao%20inicial.md).
- [Base de conhecimento](Base%20de%20conhecimento): 13 notas com fontes acadêmicas e primárias, consultadas em 27/10/2026.
- [Skills locais](Skills/README.md): seis fluxos reutilizáveis.

## Estado atual

- Coletor de dados oficiais BTCUSDT, verificações SHA-256, quarentena, snapshots e divisões temporais.
- Coleta local documentada: 4.805.101 candles válidos de um minuto e 160.156 janelas completas de 30 minutos.
- Análise de velocidades e acelerações, rankings e relações documentais com notícias.
- Simulador com custos, relatórios JSON/CSV e gráfico SVG; exemplo sintético incluído.
- Arquitetura neural com ramos numérico e textual, fusão e treinamento supervisionado documentada.
- Ambiente PyTorch CPU, Transformers, Polars, scikit-learn e TensorBoard verificado.
- Dataset supervisionado com 160.119 exemplos, Ridge e CNN 1D de 2.513 parâmetros; seleção por validação e checkpoint publicado.
- Interface web local que mostra a CNN operando em replay do histórico ou ao vivo em simulação, com R$ 50 por operação, compra e venda a descoberto, stop e alvo, diário e desempenho.
- 72 testes automatizados (eram 43), incluindo causalidade dos rótulos, scalers de treino, contabilidade, skills e catálogo; workflow para Python 3.12 e 3.14 em CPU.

A CNN teve melhora pequena de previsão contra retorno zero; sua simulação fez apenas duas operações. Ainda faltam corpus de notícias, ramo textual/fusão, avaliação prospectiva independente e integração de corretora. Os testes verificam o software, sem comprovar rentabilidade.

## Executar no Windows

O ambiente completo requer Python 3.12+ (exigência do NumPy fixado) e foi verificado no Windows com Python 3.14.7. O simulador básico usa somente a biblioteca padrão.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-torch-cpu.txt
.venv/Scripts/python.exe -m pip install -r requirements-ml.txt
.venv/Scripts/python.exe App/verify_ml_environment.py
.venv/Scripts/python.exe -m unittest discover -s App -p "test_*.py" -v
```

Para demonstrar o simulador sem dependências externas:

```powershell
python App/make_example.py
python App/quantlab.py App/examples/synthetic.csv --asset SINTETICO --provenance "Serie artificial demonstrativa" --out App/results/demo
```

## Dados e resultados locais

Os arquivos reais grandes em App/data, resultados em App/results, ambiente .venv e arquivos .env ficam ignorados pelo Git. Clonar este repositório copia código, pesquisa e documentação; reproduza a coleta conforme [DADOS_BITCOIN.md](App/DADOS_BITCOIN.md):

```powershell
.venv/Scripts/python.exe App/bitcoin_data.py --as-of 2026-10-27
.venv/Scripts/python.exe App/audit_bitcoin_data.py App/data/bitcoin
.venv/Scripts/python.exe App/bitcoin_events.py
.venv/Scripts/python.exe App/bitcoin_event_news.py
```

Para preparar rótulos e treinar o primeiro modelo numérico:

```powershell
.venv/Scripts/python.exe App/supervised_data.py
.venv/Scripts/python.exe App/train_numeric.py
.venv/Scripts/python.exe App/audit_numeric.py
```

Os resultados e a trilha das operações estão em [Relatorios/numerico_v1](Relatorios/numerico_v1/README.md); os pesos pequenos e scalers em [Modelos/numerico_v1](Modelos/numerico_v1/README.md). O dataset preserva as divisões temporais e exclui alvos que cruzam suas fronteiras. O teste histórico é retrospectivo porque a série já foi explorada; a avaliação independente precisa de novo período.

O coletor preserva datasets já concluídos; use outra pasta para uma nova versão. Os dados são de BTC/USDT spot de uma bolsa e não representam o histórico global de Bitcoin. Para validar as skills localmente, instale também requirements-dev.txt; sem PyYAML esse teste é ignorado. O histórico de decisões está em Planos; commits seguem a exigência de entendimento humano de Agents.md.
