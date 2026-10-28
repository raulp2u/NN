# Correções de inicialização e operação

- Usar qualquer janela contínua de 30 candles fechados, com nova previsão a cada minuto.
- Carregar o histórico imediatamente; liberar a decisão no último candle atualizado, sem ordens nos candles anteriores.
- Recuperar lacunas sem executar ordens históricas; cancelar ordens pendentes e tratar posições existentes na retomada.
- Validar o câmbio na execução e calcular as estatísticas na moeda exibida.
- Cobrir inicialização, janelas móveis, lacunas, câmbio e estatísticas com testes de regressão e executar a suíte completa.

O checkpoint continua congelado. A política de janelas móveis precisa de nova avaliação; os resultados publicados da política anterior não a validam. Nenhum commit faz parte desta entrega.

## Validação executada

- Suíte completa: 77 testes passaram, sem testes ignorados.
- Regressões verificam decisão fora de :00/:30, continuidade após lacuna, inicialização com histórico e câmbio, cancelamento na recuperação, posição retomada e estatísticas convertidas por operação.
- `git diff --check` passou.
- A Binance real não foi acessada nesta validação; os testes da fonte ao vivo usam relógio, REST e WebSocket simulados.
