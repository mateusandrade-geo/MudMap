# Contexto do projeto (para o Claude Code)

Projeto de **segmentação mineral a partir de mapas EDS** (microanálise por
energia dispersiva de raios X). A entrada são imagens em tons de cinza, **um
mapa por elemento químico** (Si, Al, Fe, Mg, K, Ca, Na, …), todas alinhadas
pixel a pixel e com tamanho de pixel conhecido.

## Princípio inegociável: classificação determinística

A atribuição de mineral a cada pixel/região sai de **código determinístico**
(regras estequiométricas sobre o vetor de elementos, ou clustering), nunca de
julgamento "no olho" do modelo. O papel do agente é escrever, rodar e explicar
o código, e resumir evidências (ex.: "região X: Si dominante, cátions ≈ 0 →
candidata a quartzo"). Isso mantém tudo reprodutível e auditável.

## Fluxo geral

1. **Reconhecimento**: k-means rápido sobre os pixels de amostra para levantar
   candidatos (quais minerais provavelmente existem), sem commitar nada.
2. **Segmentação por partes, um mineral por vez**: cada rodada atua só nos
   pixels ainda livres (`rotulos == 0`), na ordem do mais distinto (quartzo)
   para o mais ambíguo. Estado persistente em disco permite retomar em sessões
   separadas:
   - `estado/rotulos.npy` — mapa mestre (0 = livre, 1..N = minerais commitados)
   - `estado/progresso.json` — o que já foi feito (id, mineral, regra, data)
3. **Revisão humana no napari** a cada mineral (edição de máscara na mão).
4. **Mapa colorido rotulado** das fases.
5. **Ancoragem dos centros na BSE/SE** — este script (`ancorar_centros_bse.py`).
6. **Diagrama ternário de feldspatos** (Or–Ab–An) a partir das frações de
   cátion K/Na/Ca das regiões de feldspato.

## Regras de mineral

Ficam em `config/classificacao.yaml`, como condições compostas (E lógico) sobre
frações de cátion normalizadas. A ordem = prioridade (primeiro que casa vence).
Discriminadores importam: p.ex. clorita vs biotita se separam pelo **K**
(clorita `K<0.03`, biotita `K>0.08`). Limiares devem ser calibrados a partir de
histogramas de ROIs conhecidos (grãos de referência), não chutados.

## Este script (`ancorar_centros_bse.py`)

Etapa 5. Calcula centroides por grão do mapa mestre, projeta-os no espaço de
pixels da BSE (mesmo campo/escala), abre o napari para ajuste manual e salva
`saida/centros_bse.csv` / `.json`.

- Instalar: `pip install -r requirements.txt`
- Testar sem dados: `python ancorar_centros_bse.py --demo`
- Precisa de ambiente **gráfico** (napari abre janela Qt).
- Cuidado de alinhamento: escala simples só vale se BSE e EDS cobrem o mesmo
  campo de visão; caso contrário passar afim 3×3 via `--afim`.

## Convenções

- Coordenadas em convenção **(row, col)** = (y, x), como no napari e no scipy.
- "Presente" ≈ fração de cátion `> 0.08`; "ausente/traço" ≈ `< 0.03`; a faixa
  intermediária fica sem classe de propósito (pixels mistos de borda → revisar).
- Não incluir O nas frações de cátion (O é discriminador fraco no EDS).
