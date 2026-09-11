#!/usr/bin/env python3
"""
ancorar_centros_bse.py
======================

Etapa FINAL do workflow de segmentacao mineral por EDS.

O que faz
---------
1. Le o mapa mestre de rotulos da segmentacao (0 = nao atribuido, 1..N = minerais).
2. Para cada mineral, separa as regioes conectadas (graos) e calcula o CENTROIDE
   de cada grao -- de forma deterministica, nao "no olho".
3. Le a imagem de eletrons (BSE ou SE) do MESMO campo e escala do EDS.
4. Reposiciona os centroides no espaco de pixels da BSE (a BSE costuma ter mais
   pixels) e abre o napari mostrando os pontos rotulados sobre a imagem.
5. Voce arrasta / adiciona / remove os pontos na mao. Ao FECHAR a janela, os
   centros ajustados sao gravados em CSV e JSON (nos dois sistemas de coordenadas).

Esses centros validados servem tanto como conferencia final da segmentacao quanto
como alvos exatos para analises pontuais quantificadas (que depois alimentam, por
exemplo, o diagrama ternario de feldspatos).

Entradas esperadas (caminhos ajustaveis por argumento)
------------------------------------------------------
  estado/rotulos.npy     mapa de rotulos inteiro (H_eds x W_eds). Aceita tambem .tif/.png.
  data/bse.tif           imagem BSE/SE do mesmo campo (grayscale ou RGB).
  estado/progresso.json  (opcional) mapeia id -> nome do mineral. Formatos aceitos:
                           {"1": "quartzo", "2": "clorita"}
                           ou  [{"id": 1, "mineral": "quartzo"}, ...]

Saidas
------
  saida/centros_bse.csv
  saida/centros_bse.json
    colunas: ponto_id, mineral, row_bse, col_bse, x_bse, y_bse, row_eds, col_eds

Uso rapido
----------
  # ver funcionando sem dado nenhum (gera exemplo sintetico):
  python ancorar_centros_bse.py --demo

  # uso real:
  python ancorar_centros_bse.py \
      --rotulos estado/rotulos.npy \
      --bse data/bse.tif \
      --nomes estado/progresso.json

Requisitos: veja requirements.txt (numpy, scipy, pandas, imageio, tifffile, napari[all]).

IMPORTANTE sobre alinhamento
----------------------------
O reposicionamento simples (fator de escala) so vale se a BSE e os mapas EDS cobrem
EXATAMENTE o mesmo campo de visao, mudando apenas o numero de pixels. Se houver
deslocamento, zoom ou rotacao entre as duas imagens, passe uma transformacao afim
3x3 (convencao row, col) em JSON via --afim. O script avisa quando a razao de
aspecto das duas imagens nao bate, o que costuma indicar campos diferentes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Paleta categorica com boa separacao visual (uma cor por mineral).
PALETA = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
]


# --------------------------------------------------------------------------- #
# Carregamento de dados
# --------------------------------------------------------------------------- #
def carregar_rotulos(caminho: Path) -> np.ndarray:
    """Le o mapa de rotulos (.npy, .tif ou .png) como inteiro."""
    if caminho.suffix.lower() == ".npy":
        rot = np.load(caminho)
    else:
        import imageio.v3 as iio
        rot = iio.imread(caminho)
    if rot.ndim != 2:
        raise ValueError(f"O mapa de rotulos deve ser 2D; recebi shape {rot.shape}.")
    return rot.astype(np.int64)


def carregar_bse(caminho: Path):
    """Le a imagem BSE/SE. Retorna (array, eh_rgb)."""
    import imageio.v3 as iio
    img = iio.imread(caminho)
    eh_rgb = img.ndim == 3 and img.shape[-1] in (3, 4)
    return img, eh_rgb


def carregar_nomes(caminho: Path | None, ids_presentes: np.ndarray) -> dict[int, str]:
    """Mapeia id de mineral -> nome. Cai para 'fase_N' quando nao ha arquivo."""
    nomes: dict[int, str] = {}
    if caminho and caminho.exists():
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            nomes = {int(k): str(v) for k, v in dados.items()}
        elif isinstance(dados, list):
            for item in dados:
                nomes[int(item["id"])] = str(item["mineral"])
    for i in ids_presentes:
        nomes.setdefault(int(i), f"fase_{int(i)}")
    return nomes


# --------------------------------------------------------------------------- #
# Centroides por grao (componentes conectados dentro de cada mineral)
# --------------------------------------------------------------------------- #
def centros_por_grao(rotulos: np.ndarray, area_min: int):
    """
    Para cada mineral (valor > 0), separa graos por conexao e devolve o centroide
    de cada grao com area >= area_min.

    Retorna: lista de (row, col, id_mineral), em coordenadas de PIXEL do EDS.
    """
    from scipy import ndimage as ndi

    pontos = []
    for m in np.unique(rotulos):
        if m == 0:
            continue
        mascara = rotulos == m
        cc, n = ndi.label(mascara)          # rotula graos separados desse mineral
        if n == 0:
            continue
        tamanhos = np.bincount(cc.ravel())  # tamanhos[0] = fundo
        centros = ndi.center_of_mass(mascara, cc, range(1, n + 1))
        if n == 1:
            centros = [centros]             # center_of_mass devolve tupla unica quando n==1
        for k, (r, c) in enumerate(centros, start=1):
            if tamanhos[k] >= area_min:
                pontos.append((float(r), float(c), int(m)))
    return pontos


# --------------------------------------------------------------------------- #
# Transformacao EDS -> BSE
# --------------------------------------------------------------------------- #
def afim_por_escala(shape_eds, shape_bse) -> np.ndarray:
    """Afim 3x3 (row, col) que so reescala do espaco EDS para o espaco BSE."""
    sr = shape_bse[0] / shape_eds[0]
    sc = shape_bse[1] / shape_eds[1]
    dif = abs(sr - sc) / max((sr + sc) / 2, 1e-9)
    if dif > 0.02:
        print(
            f"[AVISO] Razao de aspecto EDS vs BSE difere em {dif*100:.1f}%.\n"
            "        Isso sugere campos de visao diferentes. Considere passar uma\n"
            "        transformacao afim medida via --afim em vez do reescalonamento.",
            file=sys.stderr,
        )
    return np.array([[sr, 0, 0], [0, sc, 0], [0, 0, 1]], dtype=float)


def aplicar_afim(A: np.ndarray, pts_rowcol: np.ndarray) -> np.ndarray:
    """Aplica afim 3x3 a pontos (N,2) em convencao (row, col)."""
    h = np.column_stack([pts_rowcol, np.ones(len(pts_rowcol))])
    return (A @ h.T).T[:, :2]


# --------------------------------------------------------------------------- #
# Dados sinteticos para o modo --demo
# --------------------------------------------------------------------------- #
def gerar_demo():
    """Cria um mapa de rotulos e uma BSE sinteticos (BSE com 2x a resolucao)."""
    H = W = 240
    rot = np.zeros((H, W), dtype=np.int64)
    yy, xx = np.mgrid[0:H, 0:W]
    discos = [
        ((70, 70), 34, 1),    # quartzo
        ((70, 170), 28, 2),   # clorita
        ((165, 120), 40, 3),  # biotita
        ((190, 200), 18, 2),  # outro grao de clorita
    ]
    for (cy, cx), r, m in discos:
        rot[(yy - cy) ** 2 + (xx - cx) ** 2 <= r ** 2] = m

    rng = np.random.default_rng(0)
    base = np.zeros((H, W), float)
    for (cy, cx), r, m in discos:
        base[(yy - cy) ** 2 + (xx - cx) ** 2 <= r ** 2] = 0.4 + 0.15 * m
    bse = np.kron(base, np.ones((2, 2)))                 # 2x -> 480x480
    bse = np.clip(bse + rng.normal(0, 0.04, bse.shape), 0, 1)
    nomes = {1: "quartzo", 2: "clorita", 3: "biotita"}
    return rot, bse, False, nomes


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Ancorar centros das regioes segmentadas na imagem BSE/SE (napari).")
    ap.add_argument("--rotulos", type=Path, default=Path("estado/rotulos.npy"))
    ap.add_argument("--bse", type=Path, default=Path("data/bse.tif"))
    ap.add_argument("--nomes", type=Path, default=Path("estado/progresso.json"))
    ap.add_argument("--afim", type=Path, default=None,
                    help="JSON com matriz afim 3x3 (row,col) EDS->BSE; substitui o reescalonamento.")
    ap.add_argument("--saida", type=Path, default=Path("saida"))
    ap.add_argument("--area-min", type=int, default=20, help="Area minima do grao em pixels (EDS).")
    ap.add_argument("--size", type=float, default=14.0, help="Tamanho do marcador no napari.")
    ap.add_argument("--demo", action="store_true", help="Roda com dados sinteticos, sem precisar de arquivos.")
    args = ap.parse_args()

    # --- carregar dados -----------------------------------------------------
    if args.demo:
        rotulos, bse, eh_rgb, nomes = gerar_demo()
    else:
        if not args.rotulos.exists():
            print(f"[ERRO] Nao encontrei o mapa de rotulos: {args.rotulos}\n"
                  f"       Rode a segmentacao antes, ou use --demo para ver a interface.",
                  file=sys.stderr)
            return 1
        if not args.bse.exists():
            print(f"[ERRO] Nao encontrei a imagem BSE/SE: {args.bse}", file=sys.stderr)
            return 1
        rotulos = carregar_rotulos(args.rotulos)
        bse, eh_rgb = carregar_bse(args.bse)
        nomes = carregar_nomes(args.nomes, np.unique(rotulos[rotulos > 0]))

    # --- centroides por grao ------------------------------------------------
    pontos = centros_por_grao(rotulos, args.area_min)
    if not pontos:
        print("[ERRO] Nenhum grao acima da area minima. Reduza --area-min.", file=sys.stderr)
        return 1
    centros_eds = np.array([[r, c] for r, c, _ in pontos])       # (N,2) row,col EDS
    ids_min = [m for _, _, m in pontos]
    minerais = [nomes[m] for m in ids_min]

    # --- transformacao EDS -> BSE ------------------------------------------
    shape_bse = bse.shape[:2]
    if args.afim and args.afim.exists():
        A = np.array(json.loads(args.afim.read_text(encoding="utf-8")), dtype=float)
        if A.shape != (3, 3):
            print("[ERRO] A matriz afim deve ser 3x3.", file=sys.stderr)
            return 1
    else:
        A = afim_por_escala(rotulos.shape, shape_bse)
    centros_bse = aplicar_afim(A, centros_eds)                   # (N,2) row,col BSE

    # --- cores por mineral --------------------------------------------------
    nomes_unicos = sorted(set(minerais))
    cor_de = {nm: PALETA[i % len(PALETA)] for i, nm in enumerate(nomes_unicos)}
    cores_ponto = [cor_de[nm] for nm in minerais]

    # --- napari -------------------------------------------------------------
    try:
        import napari
        import pandas as pd
    except ImportError:
        print("[ERRO] napari nao esta instalado. Rode:  pip install \"napari[all]\" pandas",
              file=sys.stderr)
        return 1

    print("Legenda de cores:")
    for nm in nomes_unicos:
        print(f"  {cor_de[nm]}  {nm}")
    print(f"\n{len(centros_bse)} centros. Ajuste na janela (arraste/adicione/remova) e FECHE para salvar.")

    viewer = napari.Viewer(title="Ancorar centros na BSE/SE")
    viewer.add_image(bse, name="BSE/SE", colormap="gray", rgb=eh_rgb)
    feats = pd.DataFrame({"mineral": minerais})
    camada = viewer.add_points(
        centros_bse,
        name="centros",
        size=args.size,
        features=feats,
        face_color=cores_ponto,
        text={"string": "{mineral}", "size": 10, "color": "yellow",
              "anchor": "upper_left", "translation": [-6, 0]},
    )
    camada.feature_defaults["mineral"] = "?"   # pontos novos ficam como "?" ate voce renomear
    napari.run()

    # --- ler de volta e salvar ---------------------------------------------
    dados = np.asarray(camada.data)                              # (M,2) row,col BSE (ja ajustado)
    if "mineral" in camada.features:
        minerais_fin = list(camada.features["mineral"])
    else:
        minerais_fin = ["?"] * len(dados)

    A_inv = np.linalg.inv(A)
    eds = aplicar_afim(A_inv, dados)                             # volta ao espaco EDS

    args.saida.mkdir(parents=True, exist_ok=True)
    linhas = []
    for i, ((rb, cb), (re_, ce), nm) in enumerate(zip(dados, eds, minerais_fin), start=1):
        linhas.append(dict(
            ponto_id=i, mineral=nm,
            row_bse=round(float(rb), 2), col_bse=round(float(cb), 2),
            x_bse=round(float(cb), 2), y_bse=round(float(rb), 2),  # x=coluna, y=linha
            row_eds=round(float(re_), 2), col_eds=round(float(ce), 2),
        ))

    csv_path = args.saida / "centros_bse.csv"
    json_path = args.saida / "centros_bse.json"
    pd.DataFrame(linhas).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSalvos {len(linhas)} centros:")
    print(f"  {csv_path}")
    print(f"  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
