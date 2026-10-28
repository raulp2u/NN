# Checkpoint numérico inicial

CNN 1D de 2.513 parâmetros, selecionada pela validação na época 2. Artefato experimental de pesquisa, sem validação prospectiva ou aprovação para operar dinheiro real.

- cnn.pt: state_dict da CNN, carregável com torch.load(..., weights_only=True).
- scalers.npz: médias/escalas de oito canais e do alvo, ajustadas no treino.
- ridge.npz: coeficientes e intercepto da referência linear.
- config.json: ordem dos canais, semente, hiperparâmetros, versões e hash do manifesto de dados.

A implementação da arquitetura é NumericCNN em App/train_numeric.py. A entrada tem formato [batch, 8, 30], construída por features() em App/supervised_data.py e normalizada com os scalers salvos. A saída da rede está na escala padronizada do alvo: multiplicar por target_scale e somar target_mean para obter retorno logarítmico decimal previsto para 30 minutos.

A cabeça emite uma previsão de retorno, não uma probabilidade calibrada ou uma ação diretamente. Não há entrada de notícias neste checkpoint. Detalhes e métricas em ../../Relatorios/numerico_v1/README.md.
