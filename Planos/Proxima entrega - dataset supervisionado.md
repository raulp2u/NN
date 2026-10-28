# Próxima entrega: dataset supervisionado e referência numérica

Data: 27/10/2026. Execução autorizada pelo usuário em "então faça": construir o dataset, treinar as referências e CNN, validar e publicar a entrega com o trailer solicitado.

## Objetivo

Converter as janelas reais em pares entrada/alvo verificáveis, antes de treinar a rede. Começar pelo ramo numérico enquanto é construído um corpus histórico de notícias com disponibilidade confiável.

## Contrato inicial

- Entrada X: os 30 candles completos de um minuto que terminam em t, com OHLCV e atributos calculados exclusivamente com informações disponíveis até t.
- Alvo y: retorno logarítmico `ln(close(t+30min) / close(t))`. É resultado futuro para supervisão, não uma ordem de compra/venda nem lucro executável.
- Metadados: identificador da janela, início, disponibilidade t, fim do alvo, divisão temporal e versão/hash dos dados.
- Exigir continuidade no intervalo de entrada e no horizonte futuro. Não interpolar lacunas. Contabilizar exclusões por falta de futuro, lacuna e fronteira.
- Preservar as divisões cronológicas existentes, retirando exemplos cujo alvo ultrapasse seu conjunto. Transformações aprendidas, inclusive normalização, usam somente o treino.

## Execução prevista

1. Implementar gerador de rótulos e atributos, preservando CSV original e salvando derivados em Parquet com manifesto.
2. Verificar manualmente exemplos pequenos e testar causalidade, timestamps, lacunas e fronteiras. Confirmar o número efetivo de exemplos por conjunto após os descartes.
3. Treinar primeiro referência de previsão zero e regressão regularizada para medir o nível de dificuldade e detectar problemas nos dados.
4. Treinar uma CNN 1D pequena em PyTorch sob o mesmo protocolo de desenvolvimento; registrar configurações, perdas de treino/validação, checkpoint e métricas.
5. Avaliar o modelo escolhido em período reservado, distinguindo erro de previsão de resultado financeiro após custos.

## Independência da avaliação

A análise anterior de extremos examinou todo o histórico. Não alegar que a divisão existente fornece avaliação final independente para escolhas inspiradas nesses achados. Rotular os resultados atuais como retrospectivos e reservar período futuro ainda não examinado, ou acompanhamento prospectivo, antes da avaliação final dessas escolhas. Não consultar repetidamente o teste para ajustar arquitetura ou parâmetros.

## Entregáveis

Gerador reproduzível, contrato de atributos/rótulos, manifesto de qualidade e contagens, testes de vazamento, referência estatística e posteriormente relatório do primeiro treinamento numérico. O ramo de notícias depende de corpus próprio; as anotações retrospectivas dos dez extremos não serão tratadas como feed disponível no passado.

## Protocolo pré-fixado desta execução

Janelas de entrada e alvo de 30 minutos, sem sobreposição entre horizontes futuros. A próxima janela completa fornece o fechamento futuro e preços de execução para avaliação; estes últimos nunca entram nos atributos. Oito canais: log OHLC relativos à primeira abertura, log1p(volume BTC), diferença de log-fechamento, segunda diferença e corpo logarítmico. Derivadas iniciais sem suporte são preenchidas com zero pela posição fixa na janela, sem usar o futuro. Escala dos canais e do alvo ajustadas exclusivamente no treino.

Comparar previsão zero, Ridge alpha=10 e uma CNN de duas convoluções (8→16→32 canais, kernel 3, GELU, pooling médio e MLP 32→16→1). Semente 42, AdamW lr=0,001, weight_decay=0,0001, batch 512, até 20 épocas e patience=4. Selecionar checkpoint e candidato por MSE da validação; não buscar novos parâmetros após observar o teste. Registrar teste histórico como retrospectivo devido à exploração anterior.

Avaliação financeira secundária: spot comprado ou caixa, cada previsão positiva acima da barreira logarítmica de custo estimado pode abrir uma posição na abertura seguinte e liquidá-la ao fim do horizonte de 30 minutos. Custos hipotéticos por lado: 10 bps de taxa e 5 bps de slippage. Não otimizar limiar pelo teste. A marcação de drawdown será de fechamento de horizonte, com possibilidade de perda intraperíodo maior. Comparar caixa e compra e manutenção com custos terminais. Esta convenção avalia o motor e não implica execução real.

## Próximo commit

O usuário solicitou o trailer abaixo no próximo commit. A preferência está registrada em Agents.md; o histórico já publicado não será reescrito por esta solicitação.

```text
Co-authored-by: Codex <noreply@openai.com>
```

## Execução concluída

Dataset gerado: 160.119 exemplos (128.089/16.015/16.015). Exclusões: 34 por lacunas futuras, duas por fronteira e uma sem futuro. Oito canais de entrada com formato [8,30], rótulo de retorno logarítmico de 30 minutos, Parquet e hashes. Auditoria recalculou todos os alvos e verificou normalização só no treino.

Treinadas previsão zero, Ridge e CNN numérica de 2.513 parâmetros. Semente e configuração pré-fixadas; parada na época 6 e checkpoint da época 2 escolhido por validação. CNN reduziu MSE de teste em aproximadamente 0,098% contra previsão zero; resultado fraco. Simulação gerou +4,69% em apenas duas operações, sem demonstrar robustez. Nenhum ramo de notícias foi treinado.

Revisão numérica corrigiu a fórmula aproximada do limiar de custos para sua expressão exata. Não houve retreino ou ajuste por desempenho: previsões, operações e retornos permaneceram iguais, verificados por código. Auditoria reproduziu as 16.015 previsões de teste e a contabilidade a partir dos artefatos congelados.

43 testes locais passaram. O workflow existente foi adaptado para dependências numéricas CPU. Pesos e relatório pequenos preparados para publicação; Parquets e resultados completos permanecem locais. Relatório e ressalvas em Relatorios/numerico_v1/README.md. O repositório já continha o refinamento integrado f0f3e93; suas alterações foram preservadas.
