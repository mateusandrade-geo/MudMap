"""Importa a segmentação do usuário de uma IMAGEM com pontos coloridos.

Dois fluxos:
- modo POLÍGONO (angular|convexo): cada grupo de >4 pontos vira uma região (fecho).
- modo SEMENTE: cada ponto é o CENTRO de um grão; extrai grão REDONDO (buraco de baixo Si
  com Fe) por disco local. Usado p/ óxido de Fe (grãos arredondados disseminados).

Imagem pode ser:
- --fonte-imagem mapa: 1:1 com o mapa (recorta barra de info).
- --fonte-imagem figura: figura matplotlib; detecta o quadro dos eixos (spines) e remapeia.

--auto-holes soma centros de buracos redondos auto-detectados (na ROI = máscara commitada).
--commit grava em rotulos.npy SUBSTITUINDO o mineral (backup rotulos_prev.npy); senão salva
a semente seg_seed_<mineral>.npy. Sempre gera prévia PRÉ p/ o chat.
"""
import argparse
import json
import warnings
from datetime import date
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import ConvexHull
from skimage.draw import polygon as draw_polygon
from skimage.filters import threshold_otsu
from skimage import measure, morphology
from sklearn.cluster import DBSCAN
from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra, id_e_regra)

warnings.filterwarnings("ignore")
EST = Path("estado")
SAIDA = Path("saida")


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[k:k + 2], 16) for k in (0, 2, 4)])


def extrair_pontos(img_rgb, cor_hex, tol, area_min_pt=8):
    """Detecta marcas pela COR. Robusto a compressão JPG: usa o padrão de canais
    altos/baixos do alvo (ex.: magenta = R,B altos, G baixo); fallback por distância."""
    img = img_rgb.astype(int)
    alvo = hex_rgb(cor_hex).astype(int)
    hi, lo = alvo > 140, alvo < 90
    m = np.ones(img.shape[:2], bool)
    for k in range(3):
        if hi[k]:
            m &= img[..., k] > 110
        elif lo[k]:
            m &= img[..., k] < 120
    if m.sum() < 5:                                   # fallback: distância tolerante
        d = np.sqrt(((img - alvo) ** 2).sum(-1))
        m = d <= max(tol, 120)
    lab, n = ndi.label(m)
    if n == 0:
        return np.empty((0, 2))
    cen, sz = ndi.center_of_mass(m, lab, range(1, n + 1)), np.bincount(lab.ravel())[1:]
    cen = [cen] if n == 1 else cen
    return np.array([[r, c] for (r, c), s in zip(cen, sz) if s >= area_min_pt])


# ---------- FIGURA matplotlib: detectar quadro dos eixos e remapear ----------
def detectar_quadro(gray):
    """bbox (x0,x1,y0,y1) do quadro dos eixos via spines (corridas longas de escuro)."""
    H, W = gray.shape
    dark = gray < 90

    def maior_corrida(v):
        best = c = 0
        for x in v:
            c = c + 1 if x else 0
            if c > best:
                best = c
        return best

    rr = np.array([maior_corrida(dark[i]) for i in range(H)])
    cc = np.array([maior_corrida(dark[:, j]) for j in range(W)])
    srows = np.where(rr > 0.5 * W)[0]
    scols = np.where(cc > 0.5 * H)[0]
    return int(scols.min()), int(scols.max()), int(srows.min()), int(srows.max())


def centros_da_imagem(caminho, cor_hex, tol, fonte, shape):
    """Centros (row,col) em coords do MAPA a partir da imagem marcada."""
    img = np.array(Image.open(caminho).convert("RGB")).astype(int)
    H, W = shape
    if fonte == "figura":
        x0, x1, y0, y1 = detectar_quadro(img.mean(2))
        pts = extrair_pontos(img, cor_hex, tol)
        out = []
        for (cy, cx) in pts:
            mr = (cy - y0) / (y1 - y0) * H
            mc = (cx - x0) / (x1 - x0) * W
            if 0 <= mr < H and 0 <= mc < W:
                out.append((mr, mc))
        print(f"  [figura] quadro x[{x0},{x1}] y[{y0},{y1}] -> {len(out)} pontos mapeados")
        return np.array(out) if out else np.empty((0, 2))
    a = img[:H, :W]
    return extrair_pontos(a, cor_hex, tol)


# ---------- modo SEMENTE: grão redondo (buraco de baixo Si com Fe) ----------
def dominio_oxido(stack, els, frac, fg, fe_min):
    """Domínio do óxido de Fe: ESCURO em Si (buraco) E com Fe."""
    si = ndi.gaussian_filter(stack[..., els.index("Si")].astype(float), 1.0)
    fef = frac[..., els.index("Fe")]
    t = threshold_otsu(si[fg])
    return (si < t) & (fef > fe_min), fef, float(t)


def graos_por_sementes(domain, centros, R, shape):
    """Por centro: componente conexo do domínio num disco local R -> grão redondo."""
    yy, xx = np.ogrid[-R:R + 1, -R:R + 1]
    dsk0 = (yy * yy + xx * xx) <= R * R
    mask = np.zeros(shape, bool)
    for (mr, mc) in centros:
        r, c = int(round(mr)), int(round(mc))
        r = min(max(r, 0), shape[0] - 1); c = min(max(c, 0), shape[1] - 1)
        y0, y1 = max(0, r - R), min(shape[0], r + R + 1)
        x0, x1 = max(0, c - R), min(shape[1], c + R + 1)
        dsk = dsk0[(y0 - (r - R)):(y0 - (r - R)) + (y1 - y0),
                   (x0 - (c - R)):(x0 - (c - R)) + (x1 - x0)]
        dwin = domain[y0:y1, x0:x1] & dsk
        if not dwin.any():
            continue
        ll, _ = ndi.label(dwin)
        sr, sc = r - y0, c - x0
        lid = ll[sr, sc]
        if lid == 0:
            ys, xs = np.where(dwin)
            k = ((ys - sr) ** 2 + (xs - sc) ** 2).argmin()
            lid = ll[ys[k], xs[k]]
        mask[y0:y1, x0:x1] |= (ll == lid)
    return mask


def auto_holes_centros(domain, fef, roi, ecc_max, fe_min, amin=30, amax=6000):
    """Centroides de buracos redondos com Fe dentro da ROI (fecho)."""
    cand = domain & ndi.binary_fill_holes(roi)
    cand = morphology.remove_small_objects(cand, 15)
    lab = measure.label(cand)
    cen = []
    for p in measure.regionprops(lab):
        if amin <= p.area <= amax and p.eccentricity <= ecc_max \
                and np.median(fef[tuple(p.coords.T)]) >= fe_min:
            cen.append(p.centroid)
    return cen


def dedup_centros(centros, dmin=15):
    out = []
    for c in centros:
        if all((c[0] - o[0]) ** 2 + (c[1] - o[1]) ** 2 > dmin * dmin for o in out):
            out.append(c)
    return out


def filtrar_redondos(mask, ecc_max, amin):
    lab = measure.label(mask)
    out = np.zeros_like(mask)
    for p in measure.regionprops(lab):
        if p.area >= amin and p.eccentricity <= ecc_max:
            out[tuple(p.coords.T)] = True
    return out


def stats_oxido(mask, fef, pixel_um):
    lab, n = ndi.label(mask)
    regs = measure.regionprops(lab)
    diam = [2 * np.sqrt(p.area * (pixel_um or 1) ** 2 / np.pi) for p in regs]
    fes = [float(np.median(fef[tuple(p.coords.T)])) for p in regs]
    return {
        "n_graos": int(n), "n_pixels": int(mask.sum()),
        "area_um2": (round(float(mask.sum()) * (pixel_um ** 2), 1) if pixel_um else None),
        "d_equiv_um": {"p50": round(float(np.median(diam)), 3),
                       "p90": round(float(np.percentile(diam, 90)), 3)} if diam else {},
        "fe_frac": {"p50": round(float(np.median(fes)), 3),
                    "min": round(float(np.min(fes)), 3),
                    "max": round(float(np.max(fes)), 3)} if fes else {},
        "circularidade_media": round(float(np.mean(
            [1 - p.eccentricity for p in regs])), 3) if regs else None,
    }


# ---------- polígonos (fluxo original) ----------
def poligonos(pts, shape, min_pontos=5, eps=None, modo="angular"):
    if len(pts) == 0:
        return []
    if eps is None:
        eps = 0.04 * float(np.hypot(*shape))
    cl = DBSCAN(eps=eps, min_samples=1).fit_predict(pts)
    out = []
    for g in sorted(set(cl)):
        grp = pts[cl == g]
        if len(grp) < min_pontos:
            continue
        if modo == "convexo":
            try:
                hull = ConvexHull(np.column_stack([grp[:, 1], grp[:, 0]]))
                out.append(grp[hull.vertices]); continue
            except Exception:
                pass
        cen = grp.mean(0)
        ang = np.arctan2(grp[:, 0] - cen[0], grp[:, 1] - cen[1])
        out.append(grp[np.argsort(ang)])
    return out


def mascara_de_poligonos(polys, shape):
    m = np.zeros(shape, bool)
    for p in polys:
        rr, cc = draw_polygon(p[:, 0], p[:, 1], shape=shape)
        m[rr, cc] = True
    return m


PALETA = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
          "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9a6324"]


def previa_png(caminho, base, titulo, mask, cor=(0, 0.47, 0.84), centros=None):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(b, cmap="gray")
    ov = np.zeros((*mask.shape, 4)); ov[mask] = [*cor, 0.8]
    ax.imshow(ov)
    if centros is not None and len(centros):
        ax.scatter([c[1] for c in centros], [c[0] for c in centros], s=14,
                   c="magenta", edgecolors="white", linewidths=0.4)
    _, n = ndi.label(mask)
    ax.set_title(f"{titulo} — {n} regiões, {int(mask.sum())} px")
    ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=130, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}  >> Agente: EXIBA este PNG aqui no chat.")


def previa_regioes(caminho, base, titulo, polys):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(b, cmap="gray")
    for i, p in enumerate(polys):
        cor = PALETA[i % len(PALETA)]
        pc = np.vstack([p, p[:1]])
        ax.fill(pc[:, 1], pc[:, 0], facecolor=cor, alpha=0.45, edgecolor=cor, lw=2)
        ax.plot(p[:, 1], p[:, 0], ".", color=cor, ms=4)
        r, c = p[:, 0].mean(), p[:, 1].mean()
        ax.text(c, r, str(i + 1), color="white", fontsize=11, ha="center", va="center",
                bbox=dict(fc=cor, ec="none", alpha=0.8, pad=1))
    ax.set_title(f"{titulo} — {len(polys)} regiões")
    ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=130, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}  >> Agente: EXIBA este PNG aqui no chat.")


def commit_substituindo(ident, mask, nome, condicoes):
    """Grava em rotulos.npy SUBSTITUINDO o mineral (backup rotulos_prev.npy)."""
    ROT, PREV, PROG = EST / "rotulos.npy", EST / "rotulos_prev.npy", EST / "progresso.json"
    rot = np.load(ROT) if ROT.exists() else np.zeros(mask.shape, np.int64)
    np.save(PREV, rot)                                   # backup
    rot[rot == ident] = 0                                # remove o antigo (substitui)
    rot[mask & (rot == 0)] = ident                       # não sobrescreve outros minerais
    np.save(ROT, rot)
    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else []
    prog = [p for p in prog if p["id"] != ident]
    prog.append(dict(id=ident, mineral=nome, metodo="revisar_pontos(semente)",
                     condicoes=condicoes, data=str(date.today())))
    PROG.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Commitado id={ident} ({nome}): {int((rot == ident).sum())} px "
          f"(backup em {PREV}).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineral", required=True)
    ap.add_argument("--imagem", required=True, help="imagem editada com os pontos")
    ap.add_argument("--cor", required=True, help="cor dos pontos, ex.: #ff00ff (magenta)")
    ap.add_argument("--tol", type=int, default=60)
    ap.add_argument("--fonte-imagem", choices=["mapa", "figura"], default="mapa",
                    help="mapa: 1:1 com o mapa; figura: detecta o quadro dos eixos e remapeia")
    ap.add_argument("--modo", choices=["angular", "convexo", "semente"], default="angular",
                    help="semente: cada ponto é centro de grão redondo (buraco de Si+Fe)")
    ap.add_argument("--raio-grao", type=int, default=24, help="modo semente: raio local (px)")
    ap.add_argument("--fe-min", type=float, default=0.10, help="modo semente: Fe_frac mínimo")
    ap.add_argument("--ecc-max", type=float, default=0.85, help="modo semente: arredondamento")
    ap.add_argument("--auto-holes", action="store_true",
                    help="soma centros de buracos redondos auto-detectados na ROI (rotulos==id)")
    ap.add_argument("--eps-px", type=float, default=None)
    ap.add_argument("--base", default="Si")
    ap.add_argument("--previa", action="store_true")
    ap.add_argument("--commit", action="store_true",
                    help="grava em rotulos.npy substituindo o mineral (backup); senão salva semente")
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    ident, mineral = id_e_regra(cfg, args.mineral)
    stack, overlay = carregar_mapas(cfg["pasta_dados"], els)
    H, W = stack.shape[:2]
    base = stack[..., els.index(args.base)]

    if args.modo == "semente":
        frac, soma = fracao_cations(stack)
        fg = mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, els)
        domain, fef, tsi = dominio_oxido(stack, els, frac, fg, args.fe_min)
        centros = list(centros_da_imagem(args.imagem, args.cor, args.tol,
                                         args.fonte_imagem, (H, W)))
        n_marc = len(centros)
        if args.auto_holes:
            ROT = EST / "rotulos.npy"
            rot = np.load(ROT) if ROT.exists() else np.zeros((H, W), np.int64)
            roi = (rot == ident) if (rot == ident).any() else fg
            auto = auto_holes_centros(domain, fef, roi, args.ecc_max, args.fe_min)
            centros += auto
            print(f"  auto-holes na ROId: +{len(auto)} centros")
        centros = dedup_centros(centros)
        print(f"{args.mineral}: {n_marc} marcados + auto -> {len(centros)} centros "
              f"(dedup) | Otsu(Si)={tsi:.0f} fe_min={args.fe_min} R={args.raio_grao}")
        mask = graos_por_sementes(domain, centros, args.raio_grao, (H, W))
        mask = filtrar_redondos(mask, args.ecc_max, int(cfg.get("area_min", 30)))
        st = stats_oxido(mask, fef, cfg.get("pixel_um"))
        print("stats:", json.dumps(st, ensure_ascii=False))
        SAIDA.mkdir(exist_ok=True)
        (SAIDA / f"{args.mineral}_stats.json").write_text(
            json.dumps({"mineral": args.mineral, "metodo": "buracos_redondos_fe",
                        "params": {"si_limiar": "otsu", "fe_min": args.fe_min,
                                   "ecc_max": args.ecc_max, "raio_grao": args.raio_grao},
                        **st}, ensure_ascii=False, indent=2), encoding="utf-8")
        previa_png(SAIDA / f"previa_{args.mineral}_pre.png", base,
                   f"PRÉ {args.mineral} (holes+sementes, redondos)", mask, centros=centros)
        if args.previa:
            return
        import napari
        viewer = napari.Viewer(title=f"Revisar {args.mineral} (pincel/borracha) e FECHE p/ salvar")
        for e in els:
            viewer.add_image(stack[..., els.index(e)], name=e, blending="additive",
                             visible=e in ("Si", "Fe"))
        camada = viewer.add_labels(mask.astype(int), name=f"{args.mineral} (redondos)")
        napari.run()
        final = np.asarray(camada.data) > 0
        if args.commit:
            commit_substituindo(ident, final, args.mineral, mineral.get("condicoes", {}))
        else:
            np.save(EST / f"seg_seed_{args.mineral}.npy", final)
            print(f"Semente salva: estado/seg_seed_{args.mineral}.npy ({int(final.sum())} px).")
        previa_png(SAIDA / f"previa_{args.mineral}_pos.png", base,
                   f"PÓS {args.mineral}", final)
        return

    # ---- fluxo original (polígonos) ----
    a = np.array(Image.open(args.imagem))[..., :3][:H, :W]
    pts = extrair_pontos(a, args.cor, args.tol)
    polys = poligonos(pts, (H, W), eps=args.eps_px, modo=args.modo)
    print(f"{args.mineral}: {len(pts)} pontos '{args.cor}' -> {len(polys)} regiões")
    previa_regioes(SAIDA / f"previa_{args.mineral}_pre.png", base,
                   f"PRÉ {args.mineral} (sua segmentação)", polys)
    if args.previa:
        return
    import napari
    viewer = napari.Viewer(title=f"Revisar {args.mineral}: ajuste/apague polígonos e FECHE")
    for e in els:
        viewer.add_image(stack[..., els.index(e)], name=e, blending="additive",
                         visible=e in ("Si", "Al", "K", "Fe"))
    shp = viewer.add_shapes([p for p in polys], shape_type="polygon",
                            name=f"{args.mineral} (regiões)", edge_color="#00d0ff",
                            face_color=[0, 0.5, 1, 0.3], edge_width=2)
    shp.mode = "select"
    napari.run()
    rev = shp.to_masks(mask_shape=(H, W))
    seed = np.any(np.asarray(rev, bool), axis=0) if len(rev) else np.zeros((H, W), bool)
    EST.mkdir(exist_ok=True)
    np.save(EST / f"seg_seed_{args.mineral}.npy", seed)
    previa_png(SAIDA / f"previa_{args.mineral}_pos.png", base,
               f"PÓS {args.mineral} (semente revisada)", seed)
    print(f"Semente salva: estado/seg_seed_{args.mineral}.npy ({int(seed.sum())} px).")


if __name__ == "__main__":
    main()
