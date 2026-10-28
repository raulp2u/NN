# Entrega inicial — 27/10/2026

## Realizado

- Doze notas na Base de conhecimento com links, datas de consulta e limites das evidências.
- Definição do QuantLab e hipótese de pesquisa BTC/USDT spot, candles de uma hora.
- Seis skills em Skills, validadas pelo quick_validate.py oficial da skill-creator. Uso por indicação explícita do caminho; sem instalação global.
- App Python executável com CSV OHLCV, médias móveis, simulação de entrada/saída, custos por lado, referências, JSON, CSV e gráfico SVG.
- Exemplo artificial reproduzível em App/examples/synthetic.csv; resultados locais em App/results/demo.
- Git inicializado na raiz para incluir App e os materiais de pesquisa. Nenhum commit: depende do entendimento humano exigido por Agents.md.

## Verificação

`python -m unittest discover -s App -p 'test_*.py' -v`: dez testes passaram. Cobrem CSV, dados inválidos, causalidade por prefixos, execução após o sinal, gap entre aberturas, custos, liquidação terminal, drawdown e ausência de venda descoberta.

Executada a CLI com dados artificiais. Conferidos JSON, identificação de procedência, formato do hash SHA-256 e XML do SVG. Seis skills passaram no validador oficial. PyYAML 6.0.3 instalado somente no ambiente local .venv para essa validação; App não usa dependências externas.

## Pendente de evidência ou decisão humana

Sem backtest real, modelo aprendido, análise de screenshot ou comprovação de lucro. Antes de ampliar o produto, executar as etapas de pesquisa documentadas em Ferramenta quantitativa.md. Seleção definitiva do ativo depende de comparação, liquidez, custos e acesso. Capital e perda tolerável ainda não foram informados; o protótipo usa todo o caixa e não serve como dimensionamento de risco para operação real.

O humano deve compreender que a entrega é um laboratório funcional, e que bons testes não demonstram lucro. Confirmado esse entendimento, um primeiro commit poderá registrar os artefatos preparados. Dados reais, relatórios gerados e ambiente virtual ficam fora do Git.
