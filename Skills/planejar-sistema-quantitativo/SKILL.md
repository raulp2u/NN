---
name: planejar-sistema-quantitativo
description: Definir arquitetura, escopo e critérios de aceitação de uma ferramenta de análise financeira ou evolução do QuantLab.
---

Leia Agents.md e o código existente antes de propor mudanças. Consulte ../../Planos/Ferramenta quantitativa.md para decisões iniciais; elas são hipóteses revisáveis, não requisitos universais.

Escreva todo plano em Planos/*.md. Defina mercado, moeda, horizonte de decisão, origem e instante de disponibilidade dos dados, entradas/saídas e critérios verificáveis. Separe validação do software de evidência econômica. Identifique informações faltantes que impedem dimensionar risco real sem bloquear pesquisa independente.

Explicite contratos entre ingestão, atributos, previsão, decisão e simulação. Justifique modelo simples antes de aumentar complexidade. Registre tradeoffs e etapas executáveis. Fontes externas devem ser primárias ou acadêmicas, com link e limites. Antes de commit, explique concretamente alterações e aguarde confirmação de entendimento humano.
