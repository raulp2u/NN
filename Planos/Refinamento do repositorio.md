# Refinamento do repositório

Data: 28/10/2026. Pedido do usuário: refinar tudo o que existe no repositório.

Revisão completa de código, testes, documentação, base de conhecimento e skills. Os 31 testes passavam antes da revisão e os links relativos dos .md resolvem. Os refinamentos abaixo corrigem defeitos concretos e afirmações desatualizadas; não mudam a arquitetura, os dados nem as decisões de pesquisa já registradas.

## Correções de código

1. `bitcoin_events.py`: `return_1m_pct` comparava o pico com o candle anterior mesmo quando havia lacuna entre eles. Para episódios escolhidos pelo horizonte de 30 minutos, esse retorno podia atravessar uma descontinuidade. Passa a ser vazio quando o candle anterior não é exatamente um minuto antes, como já ocorre com as derivadas.
2. `quantlab.py`: `validate` consultava o relógio a cada candle. O instante atual passa a ser lido uma vez, o que também torna a verificação consistente dentro da mesma chamada.

## Testes e verificação contínua

3. `test_skills.py`: o README pedia PyYAML para validar as skills, mas o validador era externo ao repositório. O teste local confere frontmatter YAML, nome igual à pasta, descrição e corpo não vazio.
4. `test_news_catalog.py`: confere o catálogo documental: identificadores únicos, URLs HTTPS, datas ISO, horários em UTC explícito e associações apontando para fontes existentes.
5. `.github/workflows/tests.yml`: executa a suíte em cada push e pull request, com Python 3.12 e 3.14 e as versões fixadas de requirements-analysis.txt e requirements-dev.txt. PyTorch e Transformers não são instalados no CI, pois nenhum teste os usa.

## Documentação

6. Versão mínima: o README declarava Python 3.10+, mas os scripts de dados interpretam timestamps terminados em `Z` (aceitos por `datetime.fromisoformat` a partir do 3.11) e o NumPy fixado, 2.5.4, exige 3.12. README passa a declarar 3.12+ para o ambiente completo; o simulador continua usando somente a biblioteca padrão.
7. Base de conhecimento 03 e 05 citavam candles de uma hora como hipótese atual; o laboratório usa candles de 1 minuto e janelas de 30 minutos. O simulador de médias móveis continua com intervalo padrão de uma hora.
8. README atualizado com contagem de testes, CI e versão do Python.

Planos anteriores são registros históricos e não foram reescritos.

## Fora do escopo

- Executar o simulador sobre `btc_usdt_1m.csv`: o histórico tem 34 lacunas, e o simulador rejeita lacunas por contrato. Aceitá-las exige decidir como tratar posições durante a lacuna; fica para um plano próprio.
- Implementar a rede neural definida em `Arquitetura neural e ferramentas.md`.
