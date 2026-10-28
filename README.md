# NNModel / QuantLab

Laboratório de pesquisa financeira com histórico de Bitcoin, janelas de 30 minutos, análise de movimentos extremos e uma arquitetura neural multimodal definida. O simulador atual usa médias móveis; a rede financeira ainda precisa ser implementada e treinada.

- [Como executar e interpretar o protótipo](App/README.md).
- [Histórico real de Bitcoin e snapshots de 30 minutos](App/DADOS_BITCOIN.md).
- [Maiores derivadas e relação documental com notícias](Base%20de%20conhecimento/13%20-%20Derivadas%20extremas%20e%20noticias%20do%20Bitcoin.md).
- [Arquitetura neural definida e ferramentas](Planos/Arquitetura%20neural%20e%20ferramentas.md).
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
- 35 testes automatizados, incluindo validação das skills e do catálogo de notícias, executados no GitHub Actions a cada push e pull request (Python 3.12 e 3.14).

Ainda não há rede financeira treinada, corpus histórico suficiente de notícias, validação econômica fora da amostra ou conexão a corretora. Os testes verificam o software, sem comprovar rentabilidade.

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

O coletor preserva datasets já concluídos; use outra pasta para uma nova versão. Os dados são de BTC/USDT spot de uma bolsa e não representam o histórico global de Bitcoin. Para validar as skills localmente, instale também requirements-dev.txt; sem PyYAML esse teste é ignorado. O histórico de decisões está em Planos; commits seguem a exigência de entendimento humano de Agents.md.
