---
name: implementar-ferramenta-quantitativa
description: Implementar ingestão, indicadores, simulação e relatórios em código de uma ferramenta quantitativa; usar em alterações de backend e CLI.
---

Leia Agents.md, o plano aplicável em Planos e os contratos existentes. Registre decisões de implementação que constituem plano em Planos/*.md.

Preserve causalidade: atributo do fechamento não pode executar retroativamente nesse fechamento. Diferencie sinal, ordem simulada, posição e patrimônio. Modele taxas em cada lado e documente a hipótese de preenchimento. Rejeite NaN, infinito, preços inválidos, timestamps fora de ordem e intervalos inesperados, com mensagem que permita corrigir o dado.

Evite integrar corretora ou credenciais como consequência automática de implementar uma simulação. Verifique contabilidade e causalidade com exemplos calculáveis; execute testes adequados e relate limitações. Não apresente dados artificiais como evidência de retorno. Antes de commit, explique alterações e aguarde confirmação de entendimento humano.
