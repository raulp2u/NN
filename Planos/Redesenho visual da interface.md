# Redesenho visual da interface de operação simulada

## Objetivo

Melhorar a leitura da interface em `App/interface` sem mudar o que ela mostra nem de onde vêm os dados. O motor continua sendo a fonte única; a mudança é de apresentação (HTML e CSS), com ajustes mínimos no `app.js` para cores e acessibilidade.

Público: quem acompanha o modelo operando no replay ou no paper trading e precisa responder rápido a três perguntas: o que o modelo decidiu agora e por quê, como está a posição aberta e se o resultado acumulado supera custos e sorte.

## Problemas da versão atual

- Cabeçalho fixo com quatro faixas (aviso, chips, relógio, controles, abas) ocupa cerca de 170 px antes do gráfico.
- A decisão do modelo, a informação mais importante da lateral, tem o mesmo peso visual dos demais cartões.
- Na aba Desempenho, nove cartões iguais ficam altos e vazios; o resultado líquido não se destaca do restante.
- Grade do gráfico usa a mesma cor das bordas e compete com os candles.
- Sem foco visível de teclado nos botões e abas; abas sem semântica de `tablist`.

## Direção visual: caderno de laboratório

A ferramenta é um instrumento de pesquisa, não uma corretora. A estética vem do caderno de laboratório e da folha de medição: papel frio, tinta azul-escura, réguas finas separando medidas, sem sombras nem cartões flutuando.

### Cores

| Papel | Claro | Escuro |
|---|---|---|
| Fundo (papel) | `#E9EDF2` | `#10151F` |
| Superfície | `#F9FAFC` | `#171E2B` |
| Tinta (texto) | `#16213A` | `#E3E8F1` |
| Tinta secundária | `#5A6479` | `#97A2B6` |
| Régua | `#CDD4DE` | `#2A3346` |
| Alta / compra | `#1C7F55` | `#3DBE84` |
| Baixa / venda | `#BE3A27` | `#F06A55` |
| Previsão | `#7D4FC0` | `#B596F5` |

Verde e vermelho seguem a convenção do mercado; a forma (▲ ▼, C e V) continua carregando o lado para quem não distingue as cores.

### Tipografia

Uma única família, Archivo (SIL OFL 1.1), servida localmente em `vendor/` para o replay funcionar sem internet. O eixo de largura carrega a hierarquia:

- largura expandida e peso alto só na decisão do modelo e no saldo;
- largura normal no texto corrido;
- largura semicondensada em chips, tabelas e rótulos densos;
- algarismos tabulares em todos os números.

### Layout

```
┌ faixa hachurada: SIMULAÇÃO, nenhum dinheiro real ───────────────┐
│ Painel  Diário  Desempenho      ▶ Iniciar  +1 min  [vel.]  relógio │
│ replay 20/11 → 27/11   modelo   divisão   R$ 50 por operação      │
├────────────────────────────────────────────┬────────────────────┤
│ gráfico de candles                         │ Decisão            │
│                                            │ AGUARDAR (grande)  │
│                                            │ motivo             │
│ legenda                                    │ medidas com réguas │
│ saldo acumulado                            │ Posição            │
│                                            │ Dados              │
├────────────────────────────────────────────┴────────────────────┤
│ saldo + últimas operações                                       │
└─────────────────────────────────────────────────────────────────┘
```

- Cabeçalho em duas linhas: navegação e controles na primeira, sessão na segunda. Fixo só em telas largas.
- Lateral como uma única folha com seções separadas por réguas, não três cartões.
- A decisão ganha uma barra lateral colorida pelo tipo de ação e o verbo em tipo expandido.
- Desempenho: o resultado líquido ocupa duas colunas; as demais medidas ficam numa grade compacta com réguas.
- Abaixo de 900 px a lateral desce para baixo do gráfico; abaixo de 600 px os controles quebram linha e a tabela rola na horizontal.

### Princípios

- Um só elemento chamativo: a decisão. O resto é discreto.
- Estrutura só onde informa: réguas separam medidas, cor só para lado e resultado.
- A faixa de simulação é hachurada para nunca ser confundida com um aviso comum.
- Foco de teclado visível, contraste AA nos dois temas, nenhuma animação automática.

## Validação

- Capturas de tela do replay sintético nos temas claro e escuro, desktop e celular, antes e depois.
- Testes existentes (`App/test_trading_server.py`) continuam passando, pois IDs e rotas não mudam.
