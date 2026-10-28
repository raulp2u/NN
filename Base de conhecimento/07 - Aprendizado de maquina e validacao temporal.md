# Aprendizado de máquina e validação temporal

Consulta: 27/10/2026.

Aprendizado supervisionado ajusta uma função de atributos para alvos observados. Treino, seleção de hiperparâmetros e avaliação final têm funções distintas. Erro no treino não estima sozinho generalização.

**Decisão de engenharia:** prever retorno futuro ou sua distribuição usando apenas atributos conhecidos no instante de decisão. Ajustar normalização e seleção de atributos dentro de cada treino. Usar janelas cronológicas e separar intervalos cujos rótulos futuros se sobrepõem. Preservar teste final intocado e registrar as tentativas.

Começar por regressão regularizada e referência sem ML; só promover complexidade que melhore resultados fora da amostra após custos. Acurácia direcional sozinha não mede resultado financeiro.

**Fontes:** James et al. (2023), *An Introduction to Statistical Learning with Applications in Python*, Springer, [site dos autores](https://www.statlearning.com/); [TimeSeriesSplit, documentação oficial](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html). `gap` separa observações; não resolve automaticamente todos os vazamentos de rótulos financeiros.
