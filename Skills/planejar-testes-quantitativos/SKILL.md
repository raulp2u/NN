---
name: planejar-testes-quantitativos
description: Definir cobertura de testes e critérios de aceitação para dados, sinais e contabilidade de simuladores financeiros.
---

Escreva o plano de testes em Planos/*.md. Use riscos e contratos observáveis para escolher casos: dados inválidos, custo de ida e volta, gaps entre fechamento e próxima abertura, posição aberta no fim, referência e impossibilidade de usar futuro.

Defina resultados com exemplos pequenos calculados independentemente. Inclua invariância de prefixo: acrescentar candles futuros não altera sinais passados. Não congele patrimônio terminal liquidado de um prefixo como se fosse patrimônio intermediário de uma execução maior.

Separe testes unitários e integração de estudos econômicos. Para validação econômica, exija protocolo cronológico e dados reais identificados. Não use lucro de exemplo sintético como critério de aprovação. Priorize testes que detectam falhas materiais, evitando espelhar funções ou redigir testes para mudanças triviais.
