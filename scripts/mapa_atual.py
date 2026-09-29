"""Prévia do estado atual: todos os minerais commitados em estado/rotulos.npy,
coloridos com as cores do config, sobre o mapa base, com legenda e contagens."""
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from scipy import ndimage as ndi
from common import carregar_config, carregar_mapas, id_e_regra

EST = Path("estado")
SAIDA = Path("saida")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Si",
                    help="fundo em cinza: nome de elemento (ex.: Si) ou 'bse' (Electron Image)")
    ap.add_argument("--excluir", default="",
                    help="minerais a OMITIR da prévia (nomes separados por vírgula); "
                         "as regiões deles aparecem como o fundo, não pintadas")
    ap.add_argument("--apenas", default="",
                    help="mostrar SÓ estes minerais (nomes separados por vírgula); "
                         "o resto aparece como o fundo")
    ap.add_argument("--saida", default=None,
                    help="nome do PNG de saída (default: previa_atual.png, ou "
                         "previa_atual_sem_<...>.png se houver --excluir)")
    ap.add_argument("--config", default="config/classificacao.yaml")
    ap.add_argument("--estado", default=str(EST),
                    help="pasta com rotulos.npy (sítio arquivado: sitios/<s>/estado)")
    args = ap.parse_args()

    cfg = carregar_config(args.config)
    els = cfg["elementos"]
    pixel_um = cfg.get("pixel_um")
    stack, _ = carregar_mapas(cfg["pasta_dados"], els)
    rot = np.load(Path(args.estado) / "rotulos.npy")
    if args.base.lower() == "bse":
        from common import _decodificar
        base, _ = _decodificar(cfg["bse"])
        if base.shape != rot.shape:                 # alinha se a barra recortou diferente
            r = min(base.shape[0], rot.shape[0]); c = min(base.shape[1], rot.shape[1])
            b = np.zeros(rot.shape, float); b[:r, :c] = base[:r, :c]
        else:
            b = base.astype(float)
    else:
        base = stack[..., els.index(args.base)]
        b = base.astype(float)
    b = b / (b.max() or 1)
    excluir = {n.strip() for n in args.excluir.split(",") if n.strip()}
    apenas = {n.strip() for n in args.apenas.split(",") if n.strip()}

    fig, ax = plt.subplots(figsize=(11, 11))
    ax.imshow(b, cmap="gray")

    handles = []
    linhas = []
    for m in cfg["minerais"]:
        if m["nome"] in excluir or (apenas and m["nome"] not in apenas):
            continue
        ident, _ = id_e_regra(cfg, m["nome"])
        mask = rot == ident
        px = int(mask.sum())
        if px == 0:
            continue
        cor = m.get("cor", "#888888")
        c = np.array([int(cor[k:k + 2], 16) / 255 for k in (1, 3, 5)])
        ov = np.zeros((*mask.shape, 4)); ov[mask] = [*c, 0.75]
        ax.imshow(ov)
        _, n = ndi.label(mask)
        handles.append(Patch(facecolor=cor, edgecolor="k", label=f"{m['nome']} ({n} grãos, {px} px)"))
        linhas.append((m["nome"], px, n))

    seg = sum(p for _, p, _ in linhas)
    titulo = f"Estado atual — {len(linhas)} minerais, {seg} px segmentados"
    if apenas:
        titulo = f"Estado atual — só {', '.join(sorted(apenas))} ({seg} px)"
    elif excluir:
        titulo += f"  (sem {', '.join(sorted(excluir))})"
    ax.set_title(titulo)
    ax.set_xticks([]); ax.set_yticks([])
    if handles:
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)

    if pixel_um:
        L = rot.shape[1]
        barra = round(0.2 * L / 50) * 50 or 50
        y = rot.shape[0] - 20
        ax.plot([20, 20 + barra], [y, y], color="white", lw=3)
        ax.text(20 + barra / 2, y - 8, f"{barra * pixel_um:.0f} µm", ha="center",
                color="white", fontsize=9)

    SAIDA.mkdir(exist_ok=True)
    if args.saida:
        nome_saida = args.saida
    elif apenas:
        nome_saida = "previa_atual_so_" + "_".join(sorted(apenas)) + ".png"
    elif excluir:
        nome_saida = "previa_atual_sem_" + "_".join(sorted(excluir)) + ".png"
    else:
        nome_saida = "previa_atual.png"
    fig.savefig(SAIDA / nome_saida, dpi=150, bbox_inches="tight")
    print(f"Salvo: saida/{nome_saida}")
    for nome, px, n in linhas:
        print(f"  {nome:14s} {px:>8} px  {n:>5} grãos")


if __name__ == "__main__":
    main()
