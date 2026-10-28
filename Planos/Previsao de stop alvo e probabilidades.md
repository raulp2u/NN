# Previsão de stop, alvo e probabilidades (numérico v2)

## Objetivo

Substituir os placeholders da CNN v1 por previsões do próprio modelo, conforme `Interface de operacao ao vivo.md` e `Arquitetura neural e ferramentas.md`:

1. **Cabeça de excursões:** quantis da maior alta e da maior queda do preço nos próximos 30 minutos, medidos a partir da abertura de execução.
2. **Cabeça de desfecho:** para um par de níveis stop/alvo e um lado, probabilidade de alvo primeiro, stop primeiro ou nenhum até o fim do horizonte, mais o retorno esperado quando nenhum é atingido.
3. **Probabilidades calibradas:** escala de temperatura ajustada fora do treino e diagrama de confiabilidade publicado.
4. **Política por valor esperado:** entra só se `P(alvo)·ganho + P(stop)·perda + P(tempo)·resultado no tempo − custos` superar uma margem escolhida na validação.
5. **Outros dados:** contexto de 48 candles de 5 minutos (4 h) e 48 candles de 1 hora (2 dias) além dos 30 candles de 1 minuto; funding, open interest e razão de volume comprador/vendedor dos futuros perpétuos.
6. **Faixa de previsão:** quantis 5%, 25%, 50%, 75% e 95% do retorno de 30 minutos, com ajuste conformal para que a faixa de 90% cubra cerca de 90% dos casos fora do treino.

O checkpoint v1 continua disponível e inalterado (`--model cnn`). O v2 é um modelo novo (`--model v2`) que o usuário treina localmente; nada nesta entrega afirma que o v2 tenha vantagem.

## Decisões de desenho

### Rótulos sem vazamento

Decisão no fechamento do minuto `t`; execução na abertura de `t+1`; caminho futuro = candles `t+1 … t+H`. As mesmas regras do `Engine` definem o desfecho: stop e alvo checados pela máxima e mínima, stop primeiro quando os dois caem no mesmo candle, abertura além do nível executa na abertura, saída por tempo no fechamento de `t+H`. Uma única função (`trading_engine.first_touch`) calcula esse desfecho para rótulos, simulação de validação e o próprio motor, e um teste compara os três.

### Cabeça de desfecho condicionada aos níveis

O plano anterior previa rótulos com níveis da cabeça de excursões gerados fora da amostra (cross-fitting). Em vez disso, a cabeça de desfecho recebe o lado e as distâncias de stop e alvo como entrada, e no treino os níveis são sorteados a cada lote (0,3 a 4 desvios da volatilidade recente, log-uniforme). O rótulo depende só do caminho de preço e dos níveis sorteados, nunca de um modelo ajustado, então não há vazamento a evitar com cross-fitting. Na operação, os níveis vêm da cabeça de excursões.

### Contexto multi-tempo causal

Candles de 5 minutos e de 1 hora são agregados na grade do relógio a partir do 1 minuto. Só entram candles completos (todos os minutos presentes) e encerrados até a decisão; o candle em formação fica de fora e sua informação aparece na visão de 1 minuto. A janela exige 48 candles consecutivos em cada escala, sem preencher lacunas.

### Derivativos

Fonte primária: Binance Public Data, futuros USDⓈ-M, BTCUSDT, com checksum SHA-256 de cada arquivo.

| Dado | Arquivo | Frequência | Disponibilidade assumida |
|---|---|---|---|
| Funding liquidado | `futures/um/monthly/fundingRate` | 8 h | no instante de liquidação |
| Open interest e razão taker | `futures/um/daily/metrics` | 5 min | 5 min após o registro (atraso conservador) |

Atributos: último funding (bps), idade do funding, variação log do open interest em 1 h, 4 h e 24 h, log da razão de volume taker e dois indicadores de cobertura. Antes do início de cada série (funding em 2019, métricas em 2021), os atributos valem zero e o indicador de cobertura é zero: ausência de cobertura não é tratada como evento.

**Liquidações ficam de fora.** O histórico público não tem uma série contínua de liquidações; o stream `forceOrder` só existe dali para frente e é amostrado. Incluí-las exigiria uma coleta prospectiva própria, registrada como próxima etapa.

Ao vivo, os mesmos atributos vêm da API pública `fapi` (histórico de funding, `openInterestHist` e `takerlongshortRatio` de 5 minutos), consultada a cada minuto, sem chave. Se a consulta falhar, os indicadores de cobertura vão a zero e a tela mostra o alerta.

### Arquitetura

Três extratores convolucionais pequenos (1 min × 30, 5 min × 48, 1 h × 48; oito canais cada, os mesmos de `supervised_data.features`), um MLP para os derivativos e a volatilidade, fusão por concatenação e MLP. Cabeças:

- retorno: 5 quantis monótonos (perda pinball);
- excursões: 3 quantis monótonos (25%, 50%, 75%) para a alta e para a queda (pinball);
- desfecho: entrada = representação + lado + níveis em desvios de volatilidade; saída = 3 logits (entropia cruzada) e retorno esperado no tempo (erro quadrático só nos casos sem toque).

Pesos das perdas fixados antes do treino: 1, 1, 1 e 0,5.

### Seleção, calibração e avaliação

Divisões temporais do manifesto (treino até dez/2024, validação até nov/2025, teste até out/2026). A validação é dividida em duas metades cronológicas:

1. **Calibração (primeira metade):** temperatura do desfecho, ajuste conformal da faixa de 90%, quantis de stop e alvo (grade 25/50/75%) e margem do valor esperado (grade 0 a 0,3%). A política escolhida é a de maior resultado médio por operação com pelo menos 30 operações; sem candidata, a política fica sem operar.
2. **Avaliação (segunda metade):** confiabilidade (ECE, Brier), cobertura da faixa e simulação da política congelada.
3. **Teste:** aberto uma única vez, ao final, com tudo congelado.

O histórico inteiro já foi explorado em análises anteriores; os resultados continuam retrospectivos.

### Integração

- `Signal` ganha `interval` e `sides`. O motor calcula o valor esperado de cada lado com sua própria aritmética de custos, entra no melhor lado acima da margem e usa os níveis previstos (`levels_source = "modelo"`).
- Cada decisão resolvida registra o desfecho real do lado avaliado (alvo, stop ou tempo) e se o preço ficou dentro da faixa. A aba Desempenho mostra a calibração observada na sessão.
- O gráfico mostra só a previsão mais recente com a faixa; as quatro anteriores aparecem esmaecidas, sem a “vassoura” de 40 linhas.

## Reproduzir

```powershell
.venv/Scripts/python.exe App/derivatives_data.py --as-of 2026-10-27
.venv/Scripts/python.exe App/supervised_v2.py
.venv/Scripts/python.exe App/train_v2.py
.venv/Scripts/python.exe App/trading_server.py replay --model v2 --start 2025-01-10 --end 2025-01-17 --usdtbrl-fixo 5.40
```

## Validação desta entrega

O treinamento real não foi executado neste ambiente: os dados ficam no computador do usuário e a Binance é bloqueada aqui. A entrega é validada com dados sintéticos: construção do dataset, treino curto completo, calibração, adaptador, motor e servidor, além de testes de causalidade e de equivalência entre rótulos e motor.
