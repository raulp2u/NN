# Algoritmos eficientes e desempenho

Consulta: 27/10/2026.

LightGBM introduz amostragem baseada em gradientes e agrupamento de atributos exclusivos para reduzir custo de treinamento de árvores. Ganhos medidos no artigo não são garantidos em qualquer conjunto financeiro. SGD é uma família de métodos importante para treinamento em grande escala.

**Decisão de engenharia:** medir tempo e memória no volume de dados real antes de escolher GPU ou arquitetura. Atualizar médias móveis com somas e filas em O(1) por candle, em vez de recalcular cada janela. Começar com execução em CPU e cache de dados imutáveis. Registrar hardware, versões e configuração nos benchmarks.

**Fontes:** Ke et al. (2017), *LightGBM: A Highly Efficient Gradient Boosting Decision Tree*, [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html); Bottou (2012), *Stochastic Gradient Tricks*, Springer, [página do autor](https://leon.bottou.org/papers/bottou-tricks-2012).
