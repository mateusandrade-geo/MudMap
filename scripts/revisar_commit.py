"""Revisão por NÚMERO do mineral já commitado em estado/rotulos.npy.

- Sem --remover: renderiza saida/revisar_<mineral>.png com cada grão numerado
  (sobre o mapa base) para o usuário apontar quais tirar.
- Com --remover "3 7 9": zera esses grãos no rotulos (viram 'sem classe'),
  re-salva o estado e gera a prévia PÓS.

A numeração é estável: ndi.label em ordem de varredura (cima->baixo, esq->dir).
"""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import ndimage as ndi
from common import carregar_config, carregar_mapas, id_e_regra

EST = Path("estado")
SAIDA = Path("saida")
ROT = EST / "rotulos.npy"


def graos(rotulos, ident, area_min):
    lab, n = ndi.label(rotulos == ident)
    ids = [k for k in range(1, n + 1) if (lab == k).sum() >= area_min]
    return lab, ids


def render(caminho, base, titulo, lab, ids, cor="#00d0ff"):
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(11, 11))
    ax.imshow(b, cmap="gray")
    mask = np.isin(lab, ids)
    ov = np.zeros((*mask.shape, 4)); c = [int(cor[k:k+2], 16)/255 for k in (1, 3, 5)]
    ov[mask] = [*c, 0.55]
    ax.imshow(ov)
    for k in ids:
        r, cc = ndi.center_of_mass(lab == k)
        ax.text(cc, r, str(k), color="white", fontsize=9, ha="center", va="center",
                bbox=dict(fc="red", ec="none", alpha=0.85, pad=0.6))
    ax.set_title(f"{titulo} — {len(ids)} grãos")
    ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineral", required=True)
    ap.add_argument("--base", default="Si")
    ap.add_argument("--remover", default="", help="ids de grãos a remover, ex.: \"3 7 9\"")
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    area_min = cfg.get("area_min", 30)
    ident, _ = id_e_regra(cfg, args.mineral)
    stack, _ = carregar_mapas(cfg["pasta_dados"], els)
    base = stack[..., els.index(args.base)]
    rotulos = np.load(ROT)

    lab, ids = graos(rotulos, ident, area_min)
    print(f"{args.mineral}: {len(ids)} grãos | ids={ids}")

    if args.remover.strip():
        rem = [int(x) for x in args.remover.replace(",", " ").split()]
        alvo = np.isin(lab, rem)
        np.save(ROT.with_name("rotulos_prev.npy"), rotulos)       # backup de 1 passo (desfazer)
        rotulos[alvo] = 0
        np.save(ROT, rotulos)
        print(f"Removidos grãos {rem}: {int(alvo.sum())} px -> sem classe. Estado salvo "
              f"(backup em estado/rotulos_prev.npy).")
        lab, ids = graos(rotulos, ident, area_min)
        render(SAIDA / f"revisar_{args.mineral}_pos.png", base,
               f"PÓS revisão {args.mineral}", lab, ids)
        print(f"{args.mineral} agora: {len(ids)} grãos, {int((rotulos==ident).sum())} px.")
    else:
        render(SAIDA / f"revisar_{args.mineral}.png", base,
               f"Revisar {args.mineral} (diga os números a remover)", lab, ids)


if __name__ == "__main__":
    main()
