# MudMap

O MudMap é um software destinado ao mapeamento e à classificação mineralógica de imagens obtidas por microscopia eletrônica de varredura (MEV), com foco na caracterização de rochas sedimentares analisadas em lâminas petrográficas.

O software permitirá a identificação e classificação dos minerais presentes nas amostras a partir da integração de diferentes mapas elementares obtidos por espectroscopia de raios X por dispersão de energia (EDS). Como as lâminas petrográficas são confeccionadas com resina epóxi, o sistema também contará com uma etapa de correção dos teores de carbono e oxigênio associados à resina, de modo a minimizar sua influência na classificação mineralógica.

A classificação dos minerais será realizada por meio de técnicas de aprendizado de máquina, considerando tanto as composições químicas teóricas e características de cada mineral, quanto dados reais provenientes de um banco de dados de referência. Dessa forma, o MudMap será capaz de integrar os dados elementares obtidos por EDS e, a partir das assinaturas químicas identificadas, atribuir classes mineralógicas aos diferentes pixels ou regiões da imagem.

O objetivo é desenvolver, portanto, uma ferramenta capaz de automatizar e tornar mais consistente o processo de interpretação mineralógica de imagens de MEV-EDS, permitindo a geração de mapas mineralógicos quantitativos e a caracterização da distribuição espacial dos minerais em rochas sedimentares.

# Ancoragem de centros na imagem BSE/SE

Etapa final de um workflow de segmentação mineral a partir de mapas EDS
(um mapa em tons de cinza por elemento químico). Depois que a segmentação
produz um **mapa mestre de rótulos** (`0 = não atribuído`, `1..N = minerais`),
este script:

1. separa cada mineral em regiões conectadas (grãos) e calcula o **centroide**
   de cada grão, de forma determinística;
2. abre a **imagem de elétrons (BSE ou SE)** do mesmo campo e escala no
   [napari](https://napari.org) com os centros desenhados e nomeados por cima;
3. permite **ajustar** os pontos na mão (arrastar, adicionar, remover);
4. ao fechar a janela, salva os centros validados em `saida/centros_bse.csv`
   e `saida/centros_bse.json`.

Esses centros servem como conferência final da segmentação e como alvos para
análises pontuais quantificadas (que depois alimentam, por exemplo, o diagrama
ternário de feldspatos Or–Ab–An).

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

O napari abre uma janela Qt de verdade, então rode numa máquina **com tela**
(desktop/notebook). Em servidor remoto sem ambiente gráfico a janela não aparece.

## Uso

Ver a interface funcionando sem nenhum dado (gera um exemplo sintético):

```bash
python ancorar_centros_bse.py --demo
```

Uso real:

```bash
python ancorar_centros_bse.py \
    --rotulos estado/rotulos.npy \
    --bse data/bse.tif \
    --nomes estado/progresso.json
```

Na janela: arraste os pontos que caíram fora do centro do grão, apague os
espúrios, adicione os que faltaram. **Feche a janela para salvar.**
Pontos adicionados por você entram com o nome `?` — renomeie no CSV depois,
ou ajuste o mineral atual pelo painel de *features* do napari antes de adicionar.

### Entradas

| Argumento    | Padrão                   | Descrição |
|--------------|--------------------------|-----------|
| `--rotulos`  | `estado/rotulos.npy`     | mapa de rótulos 2D inteiro (`.npy`, `.tif` ou `.png`) |
| `--bse`      | `data/bse.tif`           | imagem BSE/SE do mesmo campo (grayscale ou RGB) |
| `--nomes`    | `estado/progresso.json`  | (opcional) mapeia id → nome do mineral |
| `--afim`     | —                        | (opcional) matriz afim 3×3 (row,col) EDS→BSE, em JSON |
| `--area-min` | `20`                     | área mínima do grão em pixels do EDS |
| `--size`     | `14`                     | tamanho do marcador |
| `--saida`    | `saida`                  | pasta de saída |

O `--nomes` aceita dois formatos:

```json
{ "1": "quartzo", "2": "clorita", "3": "biotita" }
```

```json
[ { "id": 1, "mineral": "quartzo" }, { "id": 2, "mineral": "clorita" } ]
```

## Alinhamento BSE × EDS (leia isto)

O reposicionamento por **fator de escala** só é válido se a BSE e os mapas EDS
cobrem exatamente o mesmo campo de visão, mudando apenas o número de pixels.
Se houver deslocamento, zoom ou rotação entre as imagens, os pontos cairão no
lugar errado. O script **avisa** quando a razão de aspecto das duas imagens não
bate. Nesse caso, meça uma transformação afim (3–4 feições reconhecíveis nas
duas imagens) e passe-a em JSON via `--afim`. Confira na primeira vez alternando
a opacidade da camada BSE e vendo se os centros pousam no meio dos grãos.

## Saída

`saida/centros_bse.csv` (e `.json`) com colunas:
`ponto_id, mineral, row_bse, col_bse, x_bse, y_bse, row_eds, col_eds`
— coordenadas nos dois sistemas (pixel da BSE e pixel do EDS).
