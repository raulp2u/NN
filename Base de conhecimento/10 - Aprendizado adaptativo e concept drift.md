# Aprendizado adaptativo e concept drift

Consulta: 27/10/2026.

Concept drift é mudança na distribuição relevante ao aprendizado ao longo do tempo. Bifet e Gavaldà propõem janelas adaptativas que crescem em estabilidade e encolhem quando mudanças são detectadas. Detectar mudança não demonstra que retreinar uma rede aumentará lucro.

**Decisão de engenharia:** avaliar primeiro modelo estático e retreino periódico. Em avaliação sequencial, prever antes de observar o alvo e atualizar só quando o resultado futuro estiver disponível. Monitorar atributos, erro e custos separadamente. Versionar cada modelo e permitir reversão.

Uma janela adaptativa é um mecanismo de adaptação de dados, não uma rede neural por si só. Evitar atualização cega a cada perda, que pode reagir a ruído.

**Fontes:** Bifet e Gavaldà, *Learning from Time-Changing Data with Adaptive Windowing*, [manuscrito primário de 2006](https://www.cs.upc.edu/~Gavalda/papers/adwin06.pdf); Gama et al. (2014), *A Survey on Concept Drift Adaptation*, ACM Computing Surveys, [DOI](https://doi.org/10.1145/2523813).
