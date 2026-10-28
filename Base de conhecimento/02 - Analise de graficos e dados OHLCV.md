# Análise de gráficos e dados OHLCV

Consulta: 27/10/2026.

Lo, Mamaysky e Wang formalizaram padrões gráficos e encontraram informação incremental em alguns indicadores em ações americanas de 1962–1996. Isso não demonstra rentabilidade atual após custos, nem valida padrões desenhados subjetivamente.

OHLCV representa abertura, máxima, mínima, fechamento e volume de um intervalo. Uma imagem perde precisão de preços e depende de escala, cores e resolução.

**Decisão de engenharia:** analisar os dados que originam o gráfico; deixar reconhecimento de screenshots para uma comparação posterior. Validar timestamps, candles fechados, lacunas e `low <= open, close <= high`. Sinal que usa fechamento só pode ser executado depois de esse fechamento estar disponível.

**Fonte:** Lo, Mamaysky e Wang (2000), *Foundations of Technical Analysis*, Journal of Finance 55(4), 1705–1765. [NBER e publicação](https://www.nber.org/papers/w7613). Limite: amostra histórica e indicadores específicos.
