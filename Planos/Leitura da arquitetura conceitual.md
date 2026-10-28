# Leitura da arquitetura conceitual do usuário

Data: 27/10/2026.
Origem: C:/Users/raul_/Downloads/ARQUITETURA INICIAL CONCEITUAL.drawio.svg.
O original não foi alterado. Foram examinados os rótulos e as conexões do modelo draw.io incorporado ao SVG.

## O que está explícito

O modelo contém seis nós de informação com notícias, categoria, histórico e peso; seis nós analíticos com gráfico, vela, tendência e probabilidade; quatro concentradores; quatro intermediários; quatro nós subcondensados; um nó condensado; dezoito blocos rotulados pesos; caminhos rotulados tendência, gráfico, métricas e ação; resultados e conexões de ajustes de volta a estágios anteriores.

Os grupos de informação e análise convergem por caminhos hierárquicos, inclusive conexões que chegam diretamente a níveis posteriores. Isso expressa uma arquitetura funcional com múltiplas fontes, combinação de evidências e realimentação. Não especifica ainda as funções matemáticas nem o treinamento desses componentes.

## Minha interpretação, a confirmar com o usuário

Sistema de decisão financeira com fusão hierárquica de especialistas e atualização orientada por resultados. Um caminho interpreta eventos e seu histórico; outro interpreta séries de mercado. Níveis intermediários resumem e combinam suas saídas, que alimentam uma decisão. Resultados observados podem orientar revisões dos modelos e da combinação.

Há semelhança conceitual com ensembles e misturas hierárquicas de especialistas. Só seria uma mistura de especialistas com combinação aprendida se definirmos e treinarmos um mecanismo que escolha ou pondere os especialistas segundo o contexto. Um diagrama com nós e pesos não determina por si só uma rede neural. Também não determina GNN, Transformer ou aprendizado por reforço.

## Lapidação proposta

Tratar os círculos como módulos com contratos de entrada/saída. Separar extração de notícias, atributos numéricos, previsão, combinação, decisão e avaliação. Os módulos podem usar técnicas diferentes: classificador textual ou SLM para notícias; modelos estatísticos, árvores ou redes neurais para séries; combinador inicialmente simples e depois aprendido, se demonstrar vantagem.

Antes de acrescentar camadas, definir:

- O significado das repetições: fontes, categorias de eventos, ativos, horizontes temporais ou especialistas com métodos diferentes. O desenho não resolve essa escolha.
- O alvo comum: por exemplo, distribuição do retorno futuro de BTC/USDT em 30 minutos, com instante de disponibilidade e horizonte explícitos.
- O significado de cada peso: relevância da notícia, confiança na extração, evidência histórica de impacto e participação do especialista na previsão são quantidades distintas.
- A função de cada intermediário e condensador. Manter uma camada somente se realizar uma transformação identificável e verificável.
- O objetivo de atualização: qualidade da previsão, calibração e desempenho simulado líquido sob limites. Uma perda isolada não identifica qual peso deve mudar.

Cada especialista deve entregar informação compatível com o combinador, por exemplo previsão de retorno, probabilidade calibrada de ultrapassar um limiar definido e estimativa de incerteza. O limiar pode depender dos custos, mas precisa ser especificado. Uma pontuação arbitrária de 0 a 1 não é automaticamente probabilidade.

Adicionar entre previsão e ação uma política que considere custos, posição atual, tamanho de posição, incerteza e limites de perda. A ação pode ser aguardar. Avaliar previsões mesmo quando não houver operação, para não aprender apenas com casos selecionados pela política de negociação.

As notícias precisam estar disponíveis no instante da decisão; não usar análises posteriores como conhecimento passado. Evitar contar o mesmo anúncio várias vezes porque apareceu em várias fontes. Gráfico e candles derivados do mesmo OHLCV também compartilham informação; tratá-los como evidências independentes duplica confiança.

## Fluxo funcional sugerido

Notícias disponíveis → extração de eventos e atributos textuais → especialista de notícias.

OHLCV disponível → retornos, volume, derivadas e contexto temporal → especialista de mercado.

Especialistas → combinação de previsões → política de decisão e risco → simulação/ação → resultados observados.

Resultados → avaliação temporal → atualização versionada dos especialistas e/ou combinador. A realimentação conceitual não implica retreinamento automático em produção ou atualização após cada operação.

## Fundamentação da nomenclatura

- Jacobs, Jordan, Nowlan e Hinton (1991), *Adaptive Mixtures of Local Experts*, Neural Computation 3, 79–87. https://www.cs.toronto.edu/~fritz/absps/jjnh91.pdf — especialistas e mecanismo de combinação; não é prova de rentabilidade financeira.
- Jordan e Jacobs (1991), *Hierarchies of Adaptive Experts*, NeurIPS. https://proceedings.nips.cc/paper_files/paper/1991/file/59b90e1005a220e2ebc542eb9d950b1e-Paper.pdf — organização hierárquica de especialistas.
- Baltrušaitis, Ahuja e Morency, *Multimodal Machine Learning: A Survey and Taxonomy*, IEEE TPAMI (2019), manuscrito dos autores: https://arxiv.org/abs/1705.09406 — representação, alinhamento temporal e fusão entre modalidades. A classificação do desenho como multimodal é uma interpretação funcional das entradas texto e séries numéricas.

Esta nota interpreta o conceito e propõe refinamentos; não implementa nem escolhe definitivamente os modelos. Nenhum commit realizado.
