"""Relatório final — estatística + triângulo ternário granulométrico (Shepard).

Decisões do usuário (ver "Decisões já tomadas" em .claude/skills/mudmap/SKILL.md):
- Ternário GRANULOMÉTRICO por tamanho de grão medido (Wentworth), por ÁREA:
  argila <3,9 µm, silte 3,9–62,5 µm, areia ≥62,5 µm.
- Grãos = componentes conexos POR MINERAL em rotulos.npy com área ≥ area_min (os menores são
  cimento/finos, fora do ternário). Minerais `matriz: true` não são grãos: a área inteira entra na
  argila (decisão 2026-09-28).
- Ressalva de escala: FOV ~111 µm (1.1) / ~56 µm (1.2); grão de areia não cabe inteiro →
  fração "areia" truncada. OK p/ amostra de lama (silte+argila).

Gera o painel (máscara e grãos sobre a BSE, ternário de Shepard, tamanho ponderado por área com
D50, composição média e nº de grãos por mineral, Na-K-Ca do feldspato) em
saida/relatorio_final_previa.png e os números em saida/relatorio_final.json.
Uso: python scripts/relatorio_final.py --previa [--estado sitios/<s>/estado] [--abertura 0]
"""
import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly
from scipy import ndimage as ndi
from skimage.filters import sobel, gaussian
from skimage.morphology import h_minima
from skimage.segmentation import watershed
from skimage.measure import regionprops
from skimage.color import label2rgb

import common

# Limites de Wentworth (µm)
LIM_ARGILA = 3.9
LIM_AREIA = 62.5


def carregar_bse(pasta, ref_shape=None):
    """Decodifica a BSE (Electron Image) em intensidade float, sem barra de info."""
    from PIL import Image
    p = next(Path(pasta).glob("Electron Image*.tif"))
    im = Image.open(p)
    arr = np.array(im)
    h = common._altura_mapa(im, arr)
    arr = arr[:h]
    gray = arr[..., :3].mean(-1) if arr.ndim == 3 else arr.astype(float)
    if ref_shape is not None and gray.shape != ref_shape:
        r = min(gray.shape[0], ref_shape[0]); c = min(gray.shape[1], ref_shape[1])
        gray = gray[:r, :c]
    return gray


def graos_de_rotulos(rotulos, cfg, area_min, abertura=0):
    """Grãos = componentes conexos POR mineral em rotulos.npy.

    Trabalha só com os objetos já segmentados. abertura>0 aplica abertura
    morfológica (raio em px) para remover speckle antes de rotular.
    Minerais com `matriz: true` NÃO viram grãos (a matriz contínua não é um grão;
    entra na argila como fração fina não resolvida — ver main).
    Retorna lista de regionprops-like: (mineral_id, area_px, coords).
    """
    from skimage.morphology import binary_opening, disk
    graos = []
    for i, m in enumerate(cfg["minerais"], start=1):
        mi = rotulos == i
        if not mi.any() or m.get("matriz"):
            continue
        if abertura > 0:
            mi = binary_opening(mi, disk(abertura))
        lab = ndi.label(mi)[0]
        for r in regionprops(lab):
            if r.area >= area_min:
                graos.append((i, r.area, r.coords))
    return graos


def classe_wentworth(d_um):
    if d_um < LIM_ARGILA:
        return "argila"
    if d_um < LIM_AREIA:
        return "silte"
    return "areia"


def mineral_dominante(rotulos, coords):
    """id de mineral majoritário nos pixels do grão (0 se maioria sem classe)."""
    vals = rotulos[coords[:, 0], coords[:, 1]]
    vals = vals[vals > 0]
    if vals.size == 0:
        return 0
    u, c = np.unique(vals, return_counts=True)
    return int(u[c.argmax()])


def desenhar_ternario(ax, fr_areia, fr_silte, fr_argila):
    """Triângulo Shepard simples: topo=areia, esq=silte, dir=argila."""
    V = {"areia": np.array([0.5, np.sqrt(3) / 2]),
         "silte": np.array([0.0, 0.0]),
         "argila": np.array([1.0, 0.0])}
    tri = MplPoly([V["silte"], V["areia"], V["argila"]], closed=True,
                  fill=False, ec="k", lw=1.5)
    ax.add_patch(tri)
    # grades a cada 20%
    for f in np.linspace(0.2, 0.8, 4):
        ax.plot([V["silte"][0] + f * (V["areia"][0] - V["silte"][0]),
                 V["argila"][0] + f * (V["areia"][0] - V["argila"][0])],
                [V["silte"][1] + f * (V["areia"][1] - V["silte"][1]),
                 V["argila"][1] + f * (V["areia"][1] - V["argila"][1])],
                color="0.85", lw=0.6, zorder=0)
        ax.plot([V["silte"][0] + f * (V["argila"][0] - V["silte"][0]),
                 V["areia"][0] + f * (V["argila"][0] - V["areia"][0])],
                [V["silte"][1] + f * (V["argila"][1] - V["silte"][1]),
                 V["areia"][1] + f * (V["argila"][1] - V["areia"][1])],
                color="0.85", lw=0.6, zorder=0)
        ax.plot([V["argila"][0] + f * (V["silte"][0] - V["argila"][0]),
                 V["areia"][0] + f * (V["silte"][0] - V["areia"][0])],
                [V["argila"][1] + f * (V["silte"][1] - V["argila"][1]),
                 V["areia"][1] + f * (V["silte"][1] - V["areia"][1])],
                color="0.85", lw=0.6, zorder=0)
    P = fr_areia * V["areia"] + fr_silte * V["silte"] + fr_argila * V["argila"]
    ax.scatter([P[0]], [P[1]], s=140, c="#c0392b", ec="k", zorder=5)
    ax.text(V["areia"][0], V["areia"][1] + 0.04, "areia", ha="center", fontsize=10)
    ax.text(V["silte"][0] - 0.03, -0.05, "silte", ha="right", fontsize=10)
    ax.text(V["argila"][0] + 0.03, -0.05, "argila", ha="left", fontsize=10)
    ax.set_xlim(-0.15, 1.15); ax.set_ylim(-0.15, 1.0)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Ternário granulométrico (Shepard)\n(por área de grão)", fontsize=11)


def composicao_por_mineral(frac, rotulos, elementos, ids_presentes, nomes):
    """Composição química média (fração de cátions) por mineral, sobre TODOS os
    pixels da região em rotulos.npy. Retorna {nome: {elemento: media_frac}}."""
    comp = {}
    for i in ids_presentes:
        m = rotulos == i
        if not m.any():
            continue
        medias = frac[m].mean(axis=0)   # média por elemento nos pixels do mineral
        comp[nomes[i]] = {e: float(medias[j]) for j, e in enumerate(elementos)}
    return comp


def feldspato_objetos(frac, rotulos, elementos, id_fsp, area_min):
    """Para cada OBJETO de feldspato (componente conexo >= area_min), a média
    de Na/K/Ca em fração, normalizada p/ Na+K+Ca=1 -> ponto no ternário.
    Retorna lista de (na, k, ca, area_px)."""
    iNa, iK, iCa = elementos.index("Na"), elementos.index("K"), elementos.index("Ca")
    lab = ndi.label(rotulos == id_fsp)[0]
    pts = []
    for r in regionprops(lab):
        if r.area < area_min:
            continue
        cc = r.coords
        na = frac[cc[:, 0], cc[:, 1], iNa].mean()
        k = frac[cc[:, 0], cc[:, 1], iK].mean()
        ca = frac[cc[:, 0], cc[:, 1], iCa].mean()
        s = na + k + ca
        if s <= 0:
            continue
        pts.append((na / s, k / s, ca / s, int(r.area)))
    return pts


def desenhar_ternario_fsp(ax, pts):
    """Ternário Na-K-Ca (feldspato): topo=Ca(An), esq=Na(Ab), dir=K(Or).
    pts = lista de (na, k, ca, area); tamanho do marcador ∝ área."""
    V = {"Ca": np.array([0.5, np.sqrt(3) / 2]),
         "Na": np.array([0.0, 0.0]),
         "K":  np.array([1.0, 0.0])}
    tri = MplPoly([V["Na"], V["Ca"], V["K"]], closed=True, fill=False, ec="k", lw=1.5)
    ax.add_patch(tri)
    for f in np.linspace(0.2, 0.8, 4):
        for a, b, c in (("Na", "Ca", "K"), ("Na", "K", "Ca"), ("K", "Na", "Ca")):
            ax.plot([V[a][0] + f * (V[b][0] - V[a][0]), V[c][0] + f * (V[b][0] - V[c][0])],
                    [V[a][1] + f * (V[b][1] - V[a][1]), V[c][1] + f * (V[b][1] - V[c][1])],
                    color="0.85", lw=0.6, zorder=0)
    if pts:
        areas = np.array([p[3] for p in pts], dtype=float)
        smax = areas.max()
        for na, k, ca, a in pts:
            P = ca * V["Ca"] + na * V["Na"] + k * V["K"]
            ax.scatter([P[0]], [P[1]], s=40 + 160 * a / smax,
                       c="#e8846b", ec="k", lw=0.6, alpha=0.85, zorder=5)
    ax.text(V["Ca"][0], V["Ca"][1] + 0.04, "Ca (An)", ha="center", fontsize=9)
    ax.text(V["Na"][0] - 0.03, -0.05, "Na (Ab)", ha="right", fontsize=9)
    ax.text(V["K"][0] + 0.03, -0.05, "K (Or)", ha="left", fontsize=9)
    ax.set_xlim(-0.2, 1.2); ax.set_ylim(-0.15, 1.0)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(f"Feldspato — ternário Na-K-Ca\n(por objeto, n={len(pts)})", fontsize=11)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/classificacao.yaml")
    ap.add_argument("--abertura", type=int, default=0,
                    help="raio (px) de abertura morfológica p/ remover speckle antes de rotular")
    ap.add_argument("--previa", action="store_true")
    ap.add_argument("--estado", default="estado",
                    help="pasta com rotulos.npy (sítio arquivado: sitios/<s>/estado)")
    ap.add_argument("--saida", default="saida/relatorio_final_previa.png")
    args = ap.parse_args()

    cfg = common.carregar_config(args.config)
    pasta = cfg["pasta_dados"]
    px = float(cfg["pixel_um"])
    elementos = cfg["elementos"]

    # máscara de amostra só para dimensões/FOV e fundo do painel
    stack, overlay = common.carregar_mapas(pasta, elementos)
    frac, soma = common.fracao_cations(stack)
    mask = common.mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, elementos)
    gray = carregar_bse(pasta, ref_shape=mask.shape)

    rotulos = np.load(Path(args.estado) / "rotulos.npy")
    cores = {i: m["cor"] for i, m in enumerate(cfg["minerais"], start=1)}
    nomes = {i: m["nome"] for i, m in enumerate(cfg["minerais"], start=1)}
    # id do feldspato (flag no config ou nome)
    id_fsp = next((i for i, m in enumerate(cfg["minerais"], start=1)
                   if m.get("feldspato") or m["nome"] == "feldspato"), None)

    # grãos = componentes conexos por mineral em rotulos.npy (só objetos segmentados)
    area_min = int(cfg.get("area_min", 30))
    graos = graos_de_rotulos(rotulos, cfg, area_min, args.abertura)
    diam = np.array([2 * np.sqrt(a * px * px / np.pi) for _i, a, _c in graos])
    classes = np.array([classe_wentworth(d) for d in diam])
    areas_um2 = np.array([a * px * px for _i, a, _c in graos])
    min_dom = np.array([i for i, _a, _c in graos])

    # frações de ÁREA por classe granulométrica; a MATRIZ (minerais `matriz: true`, decisão do
    # usuário 2026-09-28) entra INTEIRA na argila = fração fina não resolvida (convenção de lamitos)
    ids_matriz = [i for i, m in enumerate(cfg["minerais"], start=1) if m.get("matriz")]
    area_matriz = {nomes[i]: float((rotulos == i).sum() * px * px) for i in ids_matriz}
    tot = areas_um2.sum() + sum(area_matriz.values())
    fr = {c: (areas_um2[classes == c].sum() + (sum(area_matriz.values()) if c == "argila" else 0)) / tot
          for c in ("areia", "silte", "argila")}

    # estatística por mineral (área e nº grãos, via grão dominante)
    stats_min = {}
    for i in np.unique(min_dom):
        sel = min_dom == i
        nome = "nao_classificado" if i == 0 else nomes[i]
        stats_min[nome] = {"n_graos": int(sel.sum()),
                           "area_um2": float(areas_um2[sel].sum()),
                           "pct_area": float(100 * areas_um2[sel].sum() / tot)}
    for nome, a in area_matriz.items():
        stats_min[nome] = {"matriz": True, "area_um2": a, "pct_area": float(100 * a / tot)}

    # composição química média por mineral (fração de cátions dos pixels da região)
    ids_presentes = [i for i in np.unique(rotulos) if i > 0]
    comp = composicao_por_mineral(frac, rotulos, elementos, ids_presentes, nomes)

    # ternário Na-K-Ca por objeto de feldspato (exige Na no dataset e feldspato commitado)
    pode_fsp = bool(id_fsp) and ("Na" in elementos) and bool(np.any(rotulos == id_fsp))
    pts_fsp = feldspato_objetos(frac, rotulos, elementos, id_fsp, area_min) if pode_fsp else []

    resumo = {
        "sitio": pasta,
        "n_graos": len(graos),
        "d50_um": float(np.median(diam)) if len(diam) else None,   # só matriz/cimento: sem grãos
        "d_medio_um": float(diam.mean()) if len(diam) else None,
        "fracoes_area": {k: round(100 * v, 1) for k, v in fr.items()},
        "matriz_na_argila": {"minerais": list(area_matriz),
                             "pct_area": round(100 * sum(area_matriz.values()) / tot, 1)},
        "por_mineral": stats_min,
        "composicao_frac_cations": {
            nome: {e: round(v, 4) for e, v in d.items()} for nome, d in comp.items()},
        "feldspato_objetos_nakca": [
            {"na": round(p[0], 3), "k": round(p[1], 3), "ca": round(p[2], 3),
             "area_px": p[3]} for p in pts_fsp],
        "params": {"abertura": args.abertura, "area_min": area_min, "pixel_um": px},
        # limite de resolução: grãos menores que d_min não são contados; se d_min ≥ 3,9 µm
        # a argila NÃO é medida neste sítio (ponto no ternário fica enviesado p/ silte)
        "resolucao": {"d_min_um": round(2 * np.sqrt(area_min / np.pi) * px, 3),
                      "argila_medida": bool(2 * np.sqrt(area_min / np.pi) * px < LIM_ARGILA)},
    }
    Path("saida").mkdir(exist_ok=True)
    Path("saida/relatorio_final.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))

    if not args.previa:
        return

    # ---- painel ----
    from matplotlib.colors import to_rgb
    fig = plt.figure(figsize=(18, 15))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.25, 1.25, 1])

    # 1) MÁSCARA FINAL completa (TODOS os pixels classificados) sobre a BSE
    ax0 = fig.add_subplot(gs[0, :2])
    rgb_m = np.zeros((*rotulos.shape, 3))
    alpha_m = np.zeros(rotulos.shape)
    for i in ids_presentes:
        m = rotulos == i
        rgb_m[m] = to_rgb(cores[i])
        alpha_m[m] = 0.65
    ax0.imshow(gray, cmap="gray")
    ax0.imshow(np.dstack([rgb_m, alpha_m]))
    ax0.set_title("Máscara final dos objetos sobre a BSE (rotulos.npy — todos os pixels)",
                  fontsize=11)
    ax0.axis("off")
    from matplotlib.patches import Patch
    leg = [Patch(fc=cores[i], ec="k", label=f"{nomes[i]}") for i in ids_presentes]
    ax0.legend(handles=leg, loc="upper left", bbox_to_anchor=(1.01, 1.0),
               fontsize=8, frameon=False)

    # 2) ternário granulométrico Shepard
    ax1 = fig.add_subplot(gs[0, 2])
    desenhar_ternario(ax1, fr["areia"], fr["silte"], fr["argila"])
    ax1.text(0.5, -0.06,
             f"areia {100*fr['areia']:.1f}%  silte {100*fr['silte']:.1f}%  "
             f"argila {100*fr['argila']:.1f}%\nd_min {resumo['resolucao']['d_min_um']} µm"
             + (f" · matriz→argila {resumo['matriz_na_argila']['pct_area']}%" if area_matriz else "")
             + ("" if resumo["resolucao"]["argila_medida"] else " — ARGILA NÃO RESOLVIDA"),
             ha="center", va="top", fontsize=9, transform=ax1.transAxes)

    # 3) grãos segmentados (>=area_min), coloridos por mineral, sobre a BSE
    ax2 = fig.add_subplot(gs[1, :2])
    rgb = np.zeros((*rotulos.shape, 3))
    alpha = np.zeros(rotulos.shape)
    for (i, _a, coords), d in zip(graos, diam):
        rgb[coords[:, 0], coords[:, 1]] = to_rgb(cores[i])
        alpha[coords[:, 0], coords[:, 1]] = 0.75
    ax2.imshow(gray, cmap="gray")
    ax2.imshow(np.dstack([rgb, alpha]))
    ax2.set_title(f"Grãos (componentes >= area_min, n={len(graos)}) — cor = mineral",
                  fontsize=11)
    ax2.axis("off")

    # 4) ternário Na-K-Ca do feldspato (por objeto)
    ax3 = fig.add_subplot(gs[1, 2])
    desenhar_ternario_fsp(ax3, pts_fsp)

    # 5) composição química média por mineral (heatmap minerais × elementos, fração)
    ax4 = fig.add_subplot(gs[2, 0])
    nomes_comp = list(comp.keys())
    M = np.array([[comp[n][e] for e in elementos] for n in nomes_comp])
    im = ax4.imshow(M, cmap="viridis", aspect="auto")
    ax4.set_xticks(range(len(elementos))); ax4.set_xticklabels(elementos, fontsize=8)
    ax4.set_yticks(range(len(nomes_comp))); ax4.set_yticklabels(nomes_comp, fontsize=8)
    for r in range(M.shape[0]):
        for c in range(M.shape[1]):
            ax4.text(c, r, f"{M[r, c]:.2f}", ha="center", va="center",
                     fontsize=6, color="w" if M[r, c] < M.max() * 0.6 else "k")
    fig.colorbar(im, ax=ax4, fraction=0.046, pad=0.04)
    ax4.set_title("Composição química média\n(fração de cátions por mineral)", fontsize=10)

    # 6) histograma de diâmetro (log)
    ax5 = fig.add_subplot(gs[2, 1])
    if len(diam):
        ax5.hist(diam, bins=np.logspace(np.log10(max(diam.min(), 0.1)),
                                        np.log10(diam.max() + 1e-9), 40),
                 weights=areas_um2, color="#5a7d9a", ec="white")
    ax5.set_xscale("log")
    for lim, lab in ((LIM_ARGILA, "argila|silte"), (LIM_AREIA, "silte|areia")):
        ax5.axvline(lim, color="#c0392b", ls="--", lw=1)
        ax5.text(lim, ax5.get_ylim()[1] * 0.9, lab, rotation=90,
                 va="top", ha="right", fontsize=8, color="#c0392b")
    ax5.set_xlabel("diâmetro equivalente (µm)")
    ax5.set_ylabel("área (µm²)")
    ax5.set_title("Tamanho (ponderado por área) — " + (f"D50={resumo['d50_um']:.2f} µm"
                                                       if len(diam) else "sem grãos"),
                  fontsize=10)

    # 7) tabela de estatística por mineral
    ax6 = fig.add_subplot(gs[2, 2]); ax6.axis("off")
    linhas = [["mineral", "n", "% área"]]
    for nome, s in sorted(stats_min.items(), key=lambda kv: -kv[1]["pct_area"]):
        linhas.append([nome, "matriz" if s.get("matriz") else str(s["n_graos"]), f"{s['pct_area']:.1f}"])
    tab = ax6.table(cellText=linhas, loc="center", cellLoc="left")
    tab.auto_set_font_size(False); tab.set_fontsize(8); tab.scale(1, 1.3)
    ax6.set_title("Grãos por mineral dominante", fontsize=10)

    fig.suptitle(f"Relatório final — {pasta}  |  FOV {mask.shape[1]*px:.0f}×{mask.shape[0]*px:.0f} µm  "
                 f"|  areia truncada pela escala", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(args.saida, dpi=110)
    print("prévia:", args.saida)


if __name__ == "__main__":
    main()
