# Trading e simulação de execução

Consulta: 27/10/2026.

Um backtest selecionado entre muitas tentativas pode capturar ruído. Bailey e colaboradores propõem quantificar a probabilidade de sobreajuste de backtests; uma divisão simples treino/teste não elimina o efeito de seleção entre muitas estratégias.

**Decisão de engenharia:** registrar todas as tentativas. Simular sinal no fechamento e negociação na abertura seguinte, com comissão e deslizamento por lado. Compra aumenta unidades e reduz caixa; venda encerra unidades e credita caixa após custos. Reportar patrimônio marcado a mercado e valor líquido de liquidação final. Não supor execução dentro de um candle a partir apenas de suas máximas e mínimas.

No spot sem empréstimo, vender significa sair de uma posição comprada. Staking não é venda nem previsão de preço; requer avaliação própria de custódia e protocolo.

**Fonte:** Bailey et al. (2015), *The Probability of Backtest Overfitting*, [manuscrito dos autores](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). Limite: método estatístico, não validação de uma estratégia particular.
