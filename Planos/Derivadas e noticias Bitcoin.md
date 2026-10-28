# Maiores derivadas e notícias de Bitcoin

Data: 27/10/2026. Solicitação: analisar os maiores movimentos do histórico completo e relacioná-los às notícias.

1. Medir diferenças finitas do logaritmo do fechamento em horizontes de 1, 5 e 30 minutos. Primeira derivada: velocidade percentual por minuto; segunda: aceleração percentual por minuto ao quadrado. Comparar também retorno simples e variação nominal para não confundir preço alto com movimento proporcional extremo.
2. Percorrer todo o CSV de um minuto, reiniciando janelas nas lacunas. Identificar horário de fim/disponibilidade do candle; não usar máxima/mínima como se fossem preços executáveis.
3. Produzir ranking de altas, quedas e acelerações com desagregação temporal para evitar centenas de linhas do mesmo choque. Preservar métrica, intervalo, split e identificador do evento.
4. Investigar uma seleção explícita dos maiores episódios: núcleo pelos movimentos de 30 minutos, acrescido de extremos de 1 minuto e aceleração que não estejam representados. Registrar quais foram pesquisados e quais permanecem sem atribuição.
5. Buscar fontes primárias e acadêmicas: comunicados oficiais, decisões, bancos centrais, emissores, exchanges, publicações científicas. Preservar URL, autor/instituição, data de publicação, horário e precisão conhecidos, descrição e limitações. Horário desconhecido continua desconhecido.
6. Construir CSV relacionando evento e notícia por evidência: evento documentado no período, compatibilidade temporal ou atribuição não estabelecida. Não tratar correlação temporal como causalidade, nem inventar coeficiente estatístico com uma amostra selecionada de extremos.
7. Entregar gráficos, ranking, catálogo de notícias e relatório em português. Testar cálculo, alinhamento, exclusão de lacunas e deduplicação. Sem commit.

## Limites de interpretação

Esta é uma análise exploratória de todo o histórico por solicitação expressa, incluindo intervalos antes reservados ao teste. Decisões de modelo inspiradas nesses achados precisam de novo período intocado ou avaliação prospectiva; não chamar a série examinada de teste independente para essas decisões. Não anexar explicações retrospectivas de notícias como atributos disponíveis antes da publicação.

Uma fonte oficial pode comprovar a ocorrência de um evento sem demonstrar que ele causou o retorno observado. Atribuições de vários dias não justificam automaticamente uma causa para um candle de um minuto. Notícias e movimentos do próprio mercado também podem se retroalimentar.

## Entrega concluída

- Calculadas diferenças causais de primeira e segunda ordem nos três horizontes sobre 4.805.101 candles. Nenhuma atravessa lacunas. Hash do histórico original conferido.
- Geradas 120 posições de ranking e selecionados dez episódios distintos. Maiores variações simples de 30 minutos: −23,0631% em 12/03/2020 10:48 UTC e +33,6439% em 13/03/2020 02:45 UTC. Derivadas logarítmicas e retornos simples mantidos em colunas distintas.
- Catálogo pesquisado com 12 fontes institucionais, acadêmicas e de operadores de mercado. Dez episódios avaliados: um incidente com coincidência temporal precisa, três com mecanismo de mercado descrito retrospectivamente, cinco com contexto e um sem atribuição suficiente. Zero causas marcadas como identificadas; sem estimativa de coeficiente populacional de correlação de notícias.
- CSVs de ranking, seleção, fontes, relações documentais, eventos anotados e retornos ancorados no incidente em App/results/bitcoin_events. Gráficos científicos PNG/PDF, contextos e manifestos na mesma pasta. Catálogo versionável em App/research/bitcoin_news_sources.json.
- Relatório interpretativo: Base de conhecimento/13 - Derivadas extremas e noticias do Bitcoin.md. Gráficos inspecionados visualmente; 31 testes passaram.
- NumPy 2.5.4 e Matplotlib 3.11.2 instalados no ambiente .venv e registrados em requirements-analysis.txt. Nenhum commit realizado.
