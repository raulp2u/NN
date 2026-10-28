# Planejamento de sistemas quantitativos

Consulta: 27/10/2026.

Sculley et al. descrevem dependências de dados, ciclos de feedback e mudanças externas como fontes de dívida técnica em sistemas de ML. O modelo é apenas parte do sistema em operação.

**Decisão de engenharia:** separar ingestão, validação, atributos, previsão, decisão, simulação e relatório. Versionar contratos de dados e configurações junto ao código. Manter dados brutos com hash e registrar instante de disponibilidade. Toda execução precisa de origem dos dados, parâmetros e resultados reproduzíveis.

Promover por evidência: referência simples; validação temporal; teste final; simulação acompanhada ao vivo. Execução real requer projeto específico de limites, reconciliação de ordens, falhas e credenciais. Bons testes de software demonstram funcionamento; não demonstram lucro futuro.

**Fonte:** Sculley et al. (2015), *Hidden Technical Debt in Machine Learning Systems*, [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2015/hash/86df7dcfd896fcaf2674f757a2463eba-Abstract.html).
