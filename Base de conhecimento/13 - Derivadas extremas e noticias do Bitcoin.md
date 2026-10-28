# Derivadas extremas e notícias de Bitcoin

Análise concluída em 27/10/2026 sobre os 4.805.101 candles válidos BTC/USDT spot da Binance, de agosto de 2017 a outubro de 2026. O SHA-256 do histórico foi conferido contra o manifesto antes do cálculo. Resultados representam esse par e bolsa, não uma cotação global consolidada de Bitcoin.

## O que foi calculado

Com `p(t) = ln(fechamento(t))`, usando t como o fim do candle e h em minutos:

- Velocidade: `v_h(t) = 100 × [p(t) - p(t-h)] / h`, em percentual logarítmico por minuto.
- Aceleração: `a_h(t) = 100 × [p(t) - 2p(t-h) + p(t-2h)] / h²`, em percentual logarítmico por minuto ao quadrado.

Foram usados h = 1, 5 e 30. As diferenças são para trás, sem futuro; nenhuma atravessa lacunas. A aceleração de 30 minutos usa 60 minutos de suporte. A derivada do log compara movimentos proporcionais entre épocas; a mudança nominal em USDT também está no CSV. Aceleração é mudança na velocidade do preço, não probabilidade de compra.

Há 120 posições nos rankings: dez extremos positivos e negativos por ordem/horizonte. Primeiro retém-se o extremo de cada dia UTC; depois impõe-se distância mínima de 24 horas em cada ranking. Para pesquisa documental selecionaram-se dez episódios por intensidade da velocidade logarítmica de 30 minutos, separados por ao menos 48 horas. Os maiores extremos globais de um minuto já pertenciam a esses episódios. Isso agrupa a queda e o rebote de março de 2020 no mesmo episódio; o ranking completo preserva ambos.

Esse critério prioriza velocidade em até 30 minutos. Uma crise com grande perda acumulada por dias pode ficar fora da seleção. Parte dos episódios vem do início da negociação do par nessa bolsa; spread, profundidade e preços de outras bolsas não foram conferidos nesta etapa. Não tratar um extremo local como movimento idêntico em todas as bolsas.

## Extremos globais

| Medida | Fim UTC | Retorno simples no intervalo |
| --- | --- | --- |
| Maior alta em 1 minuto | 13/03/2020 02:32 | +7,4970% |
| Maior queda em 1 minuto | 12/03/2020 10:48 | −7,2355% |
| Maior alta em 5 minutos | 13/03/2020 02:40 | +18,4288% |
| Maior queda em 5 minutos | 12/03/2020 10:48 | −14,5699% |
| Maior alta em 30 minutos | 13/03/2020 02:45 | +33,6439% |
| Maior queda em 30 minutos | 12/03/2020 10:48 | −23,0631% |

A maior aceleração positiva de um minuto foi +14,3173 unidades log-percentuais/min² em 12/03/2020 10:49 UTC, imediatamente depois do maior choque negativo de um minuto. A maior negativa foi −12,0711 em 13/03/2020 02:41. Esses valores medem reversões muito rápidas e são sensíveis à resolução de um minuto.

## Episódios e evidência documental

Cada retorno abaixo é de fechamento a fechamento em 30 minutos, terminando no horário indicado. A coluna de contexto não identifica causalidade.

| ID | Fim UTC | Retorno | Associação verificada e limite |
| --- | --- | --- | --- |
| E01 | 13/03/2020 02:45 | +33,64% | A [BitMEX](https://www.bitmex.com/blog/how-we-are-responding-to-last-weeks-ddos-attacks) relata interrupção às 02:16 UTC, dentro dessa janela. O texto foi publicado em 16/03; não demonstra que a interrupção causou a recuperação na Binance. |
| E02 | 19/05/2021 13:10 | −20,22% | [Comunicado das associações chinesas, texto integral republicado](https://www.xinhuanet.com/fortune/2021-05/18/c_1127461941.htm), de 18/05, oferece contexto regulatório. [Relatório posterior da Binance](https://www.binance.com/en/blog/all/421499824684902170) documenta liquidações e queda do open interest. Não atribuir o choque de 19/05 à decisão de mineração de 21/05. |
| E03 | 15/09/2017 14:12 | +18,72% | [CSRC, 04/09](https://www.csrc.gov.cn/csrc/c100028/c1001463/content.shtml): restrições a ICOs e plataformas como contexto de setembro. Onze dias de distância não explicam o gatilho ou o sinal desse rebote. |
| E04 | 16/01/2018 22:58 | +18,24% | [FSS, comunicado arquivado no KDI](https://eiec.kdi.re.kr/policy/materialView.do?num=173028): força-tarefa sobre cripto anunciada naquela data. Não foi estabelecido vínculo causal com a recuperação do intervalo. |
| E05 | 04/12/2021 05:28 | −15,36% | [Genesis Research, relatório de dezembro, p. 7](https://info.genesistrading.com/hubfs/monthly-reviews/2021/21-december-market-review.pdf): pouca liquidez e alavancagem amplificaram a venda de 3–4/12 por liquidações em cascata. Relatório retrospectivo; nenhuma manchete isolada identificada como gatilho. |
| E06 | 29/11/2017 19:41 | −14,57% | A pesquisa não localizou fonte primária ou acadêmica suficiente para atribuir o movimento. Mantido como não resolvido. |
| E07 | 12/11/2017 07:11 | +16,67% | [Crypto Facilities](https://crypto-facilities.ghost.io/announcing-segwit2x-hard-fork-policy/) registra cancelamento de SegWit2x em atualização de 08/11 às 18:00 UTC. Contexto anterior, sem demonstrar causa do rebote dias depois. |
| E08 | 10/05/2020 00:21 | −13,98% | [Binance, relatório de maio de 2020](https://www.binance.com/en/blog/all/421499824684900622) documenta venda e liquidações pré-halving. O halving era programado e ainda não havia ocorrido nesse minuto. |
| E09 | 07/09/2021 15:10 | −13,95% | O [FMI](https://www.imf.org/en/news/articles/2021/11/22/mcs-el-salvador-staff-concluding-statement-of-the-2021-article-iv-mission) confirma adoção de Bitcoin em El Salvador naquela data. Coincidência de dia, sem demonstrar que a adoção causou essa venda. |
| E10 | 11/01/2018 04:36 | −13,84% | [FSA Institute, DP2017-7, cronologia p. 27 do PDF](https://www.fsa.go.jp/frtc/seika/discussion/2017/DP2017-7.pdf) registra declarações coreanas sobre fechamento de exchanges naquela data. Pesquisa retrospectiva; horário original não estabelecido. |

A declaração de pandemia pela [OMS em 11/03/2020](https://www.who.int/news-room/speeches/item/who-director-general-s-opening-remarks-at-the-media-briefing-on-covid-19---11-march-2020) é contexto antecedente de E01, não uma notícia nova no minuto da recuperação. As fontes primárias de notícias são distintas dos candles da Binance.

No incidente com hora conhecida de E01, o fechamento de BTCUSDT caiu 15,32% nos 30 minutos anteriores a 02:16 e subiu 30,23% nos 30 seguintes. São retornos ancorados no incidente, diferentes da janela de maior alta, que começa às 02:15 e termina às 02:45. Sem grupo de controle e tratamento de eventos concorrentes, esses números são descritivos.

## O que a relação com notícias permite concluir

Dez episódios foram avaliados: um tem incidente documentado com coincidência intraminuto, três têm mecanismos de mercado descritos em relatórios posteriores, cinco têm apenas contexto documental e um permanece sem atribuição suficiente. Nenhum foi marcado como causa comprovada. Não foi estimado coeficiente de correlação entre preços e notícias: uma seleção de extremos e documentos retrospectivos não permite medir essa associação para o mercado inteiro.

O estudo de [Auer e Claessens, BIS Quarterly Review, setembro de 2018](https://www.bis.org/publ/qtrpdf/r_qt1809f.pdf) demonstra uma abordagem de estudo de eventos para notícias regulatórias. Para avançar aqui, precisamos de um corpus de notícias coletado independentemente dos retornos, com horário original e de disponibilidade, períodos sem notícia, comparações temporais e controle de anúncios simultâneos. A presente pesquisa não replica esse estudo.

## Uso no treinamento

As derivadas calculadas para trás podem ser atributos causais, respeitando a disponibilidade do candle. As explicações retrospectivas são anotações de pesquisa e estão marcadas como não prontas para atributos em tempo real. Não usar o post-mortem de 16/03 como informação observável em 13/03, nem o relatório do FMI de novembro como texto disponível em setembro.

Examinar só extremos produziria uma amostra enviesada para treinar decisões gerais de compra/venda. Manter janelas normais e quedas/altas menores, usar pesos de amostragem quando apropriado e separar rótulos futuros. O contexto gráfico ±90 minutos inclui futuro exclusivamente para diagnóstico.

Esta exploração examinou todo o histórico por solicitação do usuário. Se escolhermos atributos ou modelos a partir desses resultados, será necessário um novo período intocado ou teste prospectivo para avaliar essas escolhas. O histórico original e suas divisões foram preservados.

## Arquivos e reprodução

Em `App/results/bitcoin_events`: derivative_rankings.csv, research_events.csv, events_with_news.csv, news_sources.csv, event_news.csv, timed_incident_returns.csv, event_context.csv, analysis_manifest.json, news_manifest.json, eventos.png e eventos.pdf. O catálogo pesquisado fica versionado em `App/research/bitcoin_news_sources.json`. Datas e horas não verificadas ficam vazias, com precisão explícita.

Na raiz, executar:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-analysis.txt
.venv/Scripts/python.exe App/bitcoin_events.py
.venv/Scripts/python.exe App/bitcoin_event_news.py
.venv/Scripts/python.exe -m unittest discover -s App -p "test_*.py" -v
```

Os rankings verificam o hash do histórico; manifestos registram as fórmulas e os hashes do catálogo e da seleção. Os gráficos foram inspecionados visualmente. A suíte de 31 testes passou, incluindo curvas analíticas, lacunas, ausência de futuro, associação documental e horários desconhecidos. Resultados grandes e figuras geradas ficam fora do Git; catálogo de referências e código são preservados. Nenhum commit realizado.
