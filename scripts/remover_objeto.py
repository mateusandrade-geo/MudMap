"""Remove UM objeto marcado a azul (numa imagem anotada da prévia) de TODOS os
minerais em estado/rotulos.npy.

Fluxo: detecta a área do mapa na imagem anotada -> extrai os pixels azuis ->
mapeia p/ coordenadas do mapa (1024/2048) -> pega o(s) grão(s) de mineral que o
azul toca (fechamento morfológico p/ consolidar speckle) -> remove só esses.

Sem --aplicar: só gera a prévia (saida/remover_previa.png). Com --aplicar:
grava rotulos.npy (com backup em rotulos_prev.npy) e regenera saida/previa_atual.png.
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import morphology
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from common import carregar_config, carregar_mapas

EST = Path("estado")
SAIDA = Path("saida")
ROT = EST / "rotulos.npy"


def bbox_do_mapa(a):
    """Maior componente não-branco (o mapa) -> (y0, x0, y1, x1)."""
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    nonwhite = ~((R > 243) & (G > 243) & (B > 243))
    lab, n = ndi.label(nonwhite)
    if n == 0:
        raise SystemExit("Não achei o mapa na imagem.")
    tam = np.bincount(lab.ravel()); tam[0] = 0
    maior = int(tam.argmax())
    ys, xs = np.where(lab == maior)
    return ys.min(), xs.min(), ys.max(), xs.max()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imagem", required=True, help="imagem anotada com o traço azul")
    ap.add_argument("--cor", default="#3F48CC", help="cor do traço (padrão o azul do Paint)")
    ap.add_argument("--tol", type=int, default=60)
    ap.add_argument("--raio", type=int, default=30,
                    help="raio (px) ao redor do traço azul que define o objeto a remover")
    ap.add_argument("--base", default="Si")
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    stack, _ = carregar_mapas(cfg["pasta_dados"], els)
    H, W = stack.shape[:2]
    base = stack[..., els.index(args.base)]

    a = np.array(Image.open(args.imagem).convert("RGB")).astype(int)
    y0, x0, y1, x1 = bbox_do_mapa(a)
    print(f"[mapa na imagem] bbox=({y0},{x0},{y1},{x1}) -> {y1-y0}x{x1-x0}")
    alvo = np.array([int(args.cor.lstrip('#')[k:k+2], 16) for k in (0, 2, 4)])
    d = np.sqrt(((a - alvo) ** 2).sum(-1))
    blue = d <= args.tol
    ys, xs = np.where(blue)
    print(f"[azul] {len(ys)} px")
    if len(ys) == 0:
        raise SystemExit("Nenhum pixel azul encontrado.")
    # mapeia p/ coords do mapa
    mr = ((ys - y0) / max(y1 - y0, 1) * H).astype(int).clip(0, H - 1)
    mc = ((xs - x0) / max(x1 - x0, 1) * W).astype(int).clip(0, W - 1)
    blue_map = np.zeros((H, W), bool)
    blue_map[mr, mc] = True

    rot = np.load(ROT)
    seg = rot > 0
    # objeto = sulfato/mineral DENTRO de um raio do traço azul (isola o grão local,
    # sem varrer o resto da máscara via pontes de speckle)
    region = morphology.dilation(blue_map, morphology.disk(args.raio))
    remover = seg & region
    afetados = {}
    for i in np.unique(rot[remover]):
        if i > 0:
            nome = next((m["nome"] for j, m in enumerate(cfg["minerais"], 1) if j == i), str(i))
            afetados[nome] = int((remover & (rot == i)).sum())
    print(f"[remover] {int(remover.sum())} px (raio {args.raio}). Por mineral: {afetados}")

    # prévia
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(11, 11))
    ax.imshow(b, cmap="gray")
    ov = np.zeros((H, W, 4)); ov[seg & ~remover] = [1, 0.85, 0.2, 0.45]  # fica
    ax.imshow(ov)
    ov2 = np.zeros((H, W, 4)); ov2[remover] = [1, 0.1, 0.1, 0.85]         # sai (vermelho)
    ax.imshow(ov2)
    ax.plot(mc, mr, ".", color="cyan", ms=2)
    ax.set_title(f"REMOVER (vermelho): {int(remover.sum())} px | amarelo permanece")
    ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(SAIDA / "remover_previa.png", dpi=140, bbox_inches="tight"); plt.close(fig)
    print("Salvo: saida/remover_previa.png")

    if args.aplicar:
        np.save(EST / "rotulos_prev.npy", rot.copy())
        rot[remover] = 0
        np.save(ROT, rot)
        print(f"APLICADO: removidos {int(remover.sum())} px. Backup em estado/rotulos_prev.npy")


if __name__ == "__main__":
    main()
