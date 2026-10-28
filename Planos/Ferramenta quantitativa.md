# Ferramenta quantitativa: QuantLab

## Decisão inicial

Construir laboratório local de análise de candles, sinais e backtests reproduzíveis. Universo inicial proposto: BTC/USDT à vista; intervalo: uma hora. São hipóteses de engenharia por facilidade de pesquisa com dados públicos, não um ranking comprovado de volatilidade ou rentabilidade. Não selecionar altcoins ilíquidas pelo maior movimento passado. Retorno é na moeda de cotação e depende também dos riscos dessa moeda e da bolsa.

Analisar o gráfico por seus dados numéricos OHLCV. Não há evidência reunida que justifique começar com screenshots, SLM ou rede neural adaptativa. Modelo inicial: médias móveis como referência transparente. Alvo futuro: distribuição de retorno líquido em horizonte definido; comparar regressão regularizada, árvores e MLP antes de escolher.

## Protótipo desta entrega

CLI Python sem dependências externas. CSV de candles fechados, UTC, intervalos regulares. Sinais no fechamento; execução na abertura seguinte. Compra usa caixa disponível; venda encerra posição comprada; aguardar mantém estado. Sem venda descoberta ou alavancagem. Comissão e deslizamento configuráveis por lado. Relatório JSON, trilha CSV e gráfico SVG local. Dados de exemplo são artificiais, sem valor de evidência financeira.

## Próximas etapas de pesquisa

1. Importar histórico real de fonte primária, preservar arquivos e hashes, documentar lacunas e custos praticáveis. Comparar BTC, ETH e alternativa cambial sob liquidez e acesso, antes de fixar o universo.
2. Pré-registrar universo, horizonte, alvos, parâmetros e orçamento de tentativas. Dividir cronologicamente desenvolvimento/validação/teste; remover sobreposições de rótulos e ajustar transformações apenas no treino.
3. Comparar referências de caixa e compra e manutenção, regressão regularizada, árvores e MLP. Reportar retorno líquido, drawdown, giro, número de operações, intervalos de incerteza e sensibilidade a custos. Não selecionar pelo teste final.
4. Exigir desempenho consistente entre janelas e superior às referências sob custos conservadores; se falhar, rejeitar a hipótese. Nenhum limiar estatístico garante lucro futuro.
5. Acompanhar sinais em simulação ao vivo e medir execução possível. Definir tamanho de posição e limite de perda com o humano antes de projetar operação real.

## Limites atuais

O protótipo não treina ML, não extrai screenshot, não acessa corretora e não prova vantagem econômica. Simula preenchimento integral na abertura seguinte; custos fixos não modelam livro de ofertas, impacto, latência, impostos ou indisponibilidade. O usuário ainda não definiu capital, perda tolerável ou acesso a mercados. Essas informações são necessárias para dimensionamento real, mas não impedem pesquisa local.

## Versionamento

Repositório na raiz para manter App, pesquisa e skills juntos. Preparar arquivos sem commit. A regra de Agents.md exige garantir entendimento humano antes de qualquer commit; explicar entregáveis e limites na entrega e aguardar confirmação para o commit.
