"""Editor napari COMPLETO para um mineral: reúne todas as funções do fluxo como
atalhos numa única janela.

Camadas:
  - mapas de elemento (imagens)
  - "<mineral>"  -> Labels editável (PINCEL cresce, BORRACHA encolhe,
                    BALDE+rótulo 0 remove grão inteiro, Alt+clique pega rótulo)
  - "pontos"     -> Points: clique ao redor de cada grão (>4 pontos) e tecle G
  - "formas"     -> Shapes: desenhe RETÂNGULO ou ELIPSE sobre grãos e tecle M
                    (o polígono/lasso é bugado nesta versão do napari e foi omitido)

Ferramentas nativas do napari que funcionam (camada Labels ativa):
  Pincel (cresce) · Borracha (encolhe) · Balde/fill+rótulo 0 (remove grão) ·
  Conta-gotas/pick (Alt+clique pega o rótulo) · Ctrl+Z desfaz a última pincelada.

Atalhos personalizados (foco no canvas):
  G  pontos -> regiões (agrupa por proximidade, >4 pontos = 1 região) e pinta
  M  formas (retângulo/elipse) desenhadas -> pinta no mineral
  P  propaga por exemplo (aprende a assinatura do que já está pintado e adiciona
     mais regiões com o mesmo padrão químico)
  C  limpa as camadas "pontos" e "formas"
  H  ajuda no terminal

Ao FECHAR a janela: commita o mineral em estado/rotulos.npy (sem sobrescrever
outros minerais), atualiza a semente e gera a prévia PÓS.
"""
import argparse
import json
import warnings
from datetime import date
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi
from skimage import morphology
from skimage.draw import polygon as draw_polygon
from sklearn.cluster import DBSCAN
from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra, mascara_mineral, id_e_regra)

warnings.filterwarnings("ignore")
EST = Path("estado")
SAIDA = Path("saida")
ROT = EST / "rotulos.npy"
PROG = EST / "progresso.json"


def poligono_angular(cluster):
    pts = np.asarray(cluster, float)
    cen = pts.mean(0)
    ang = np.arctan2(pts[:, 0] - cen[0], pts[:, 1] - cen[1])
    return pts[np.argsort(ang)]


def pinta_poligonos(labels, polys, ident, shape):
    n = 0
    for p in polys:
        p = np.asarray(p, float)
        if len(p) < 3:
            continue
        rr, cc = draw_polygon(p[:, 0], p[:, 1], shape=shape)
        labels[rr, cc] = ident
        n += 1
    return n


def candidato_inicial(args, cfg, els, stack, frac, fg, ident, mineral):
    if args.fonte == "exclusao" and ROT.exists():
        # B = amostra MENOS os grãos de arcabouço já commitados (matriz argilosa por exclusão).
        r = np.load(ROT)
        FRAME = [1, 2, 3, 5, 6, 12]        # quartzo,sulfato_ca,pirita,oxido_ti,oxido_fe,feldspato
        return fg & ~np.isin(r, FRAME)
    if args.fonte == "rotulos" and ROT.exists():
        r = np.load(ROT)
        if (r == ident).any():
            return (r == ident)
    if args.fonte == "seed":
        sp = EST / f"seg_seed_{args.mineral}.npy"
        if sp.exists():
            return np.load(sp)
    if args.fonte == "cluster" and (EST / "clusters.npy").exists():
        lab = np.load(EST / "clusters.npy")
        j = json.loads((EST / "clusters.json").read_text(encoding="utf-8"))
        ids = [int(c) for c, nm in j["nomes"].items() if nm == args.mineral]
        return np.isin(lab, ids) & fg
    if mineral.get("mapas_seg"):
        from skimage.filters import threshold_otsu
        m = fg.copy()
        for e in mineral["mapas_seg"]:
            ch = stack[..., els.index(e)]
            m &= ch > threshold_otsu(ch[fg])
        return m
    return mascara_mineral(frac, els, mineral["condicoes"]) & fg


def mahalanobis(x, mu, inv):
    d = x - mu
    return np.sqrt(np.einsum("...i,ij,...j->...", d, inv, d))


def propaga(labels, ident, stack, frac, fg, els, mineral, area_min, thr_f=1.2, gate_q=0.10):
    atual = labels == ident
    if atual.sum() < 30:
        print("[P] pinte algumas regiões primeiro para eu aprender o padrão.")
        return 0
    nucleo = morphology.binary_erosion(atual, morphology.disk(2)) & fg
    if nucleo.sum() < 50:
        nucleo = atual & fg
    px = frac[nucleo]
    mu = px.mean(0)
    inv = np.linalg.inv(np.cov(px.T) + np.eye(len(els)) * 1e-6)
    thr = float(np.quantile(mahalanobis(px, mu, inv), 0.98)) * thr_f

    lab_s, ns = ndi.label(atual)
    tam = np.bincount(lab_s.ravel())[1:] if ns else np.array([area_min])
    amin = max(area_min, int(np.median(tam) * 0.25))
    amax = int(tam.max() / 0.3)

    mapas = mineral.get("mapas_seg") or ["Si"]
    gate = {}
    for e in mapas:
        ch = stack[..., els.index(e)]
        med = [np.median(ch[lab_s == k]) for k in range(1, ns + 1)] if ns else [0]
        gate[e] = float(np.quantile(med, gate_q))

    livre = fg & (labels == 0)
    dist = mahalanobis(frac, mu, inv)
    cand = (dist <= thr) & livre
    cand = morphology.remove_small_holes(morphology.remove_small_objects(cand, amin), amin)
    lab_c, nc = ndi.label(cand)
    add = 0
    for k in range(1, nc + 1):
        reg = lab_c == k
        a = int(reg.sum())
        if a < amin or a > amax:
            continue
        if any(np.median(stack[..., els.index(e)][reg]) < gate[e] for e in mapas):
            continue
        labels[reg] = ident
        add += 1
    print(f"[P] propaguei +{add} regiões (thr={thr:.2f}, amin={amin}).")
    return add


def previa_png(caminho, base, titulo, mask, cor=(1, 0.85, 0.2)):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(11, 11))
    ax.imshow(b, cmap="gray")
    ov = np.zeros((*mask.shape, 4)); ov[mask] = [*cor, 0.55]
    ax.imshow(ov)
    _, n = ndi.label(mask)
    ax.set_title(f"{titulo} — {n} grãos, {int(mask.sum())} px")
    ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineral", required=True)
    ap.add_argument("--fonte", choices=["rotulos", "cluster", "mapa", "seed", "exclusao"], default="rotulos")
    ap.add_argument("--base", default=None)
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    area_min = cfg.get("area_min", 30)
    ident, mineral = id_e_regra(cfg, args.mineral)
    stack, _ = carregar_mapas(cfg["pasta_dados"], els)
    frac, soma = fracao_cations(stack)
    fg = mascara_amostra(soma, None, cfg.get("corte_fundo"))
    base_el = args.base or (mineral.get("mapas_seg") or ["Si"])[0]
    base = stack[..., els.index(base_el)]

    rotulos = np.load(ROT) if ROT.exists() else np.zeros(fg.shape, np.int64)
    outros = rotulos.copy(); outros[rotulos == ident] = 0
    inicial = candidato_inicial(args, cfg, els, stack, frac, fg, ident, mineral)
    inicial = inicial & (outros == 0)                 # não invade outros minerais
    labels0 = np.where(inicial, ident, 0).astype(np.int32)

    import napari
    viewer = napari.Viewer(title=f"Editor {args.mineral} — G:pontos M:polígonos P:propaga C:limpa H:ajuda | FECHE p/ salvar")
    vis = set(["Si", "Al", "K", "Fe"]) | set(mineral.get("mapas_seg") or [])
    for e in els:
        viewer.add_image(stack[..., els.index(e)], name=e, blending="additive", visible=e in vis)
    viewer.add_labels(rotulos, name="estado atual (ref)", opacity=0.4)  # referência: todos os minerais
    camada = viewer.add_labels(labels0, name=args.mineral)
    try:
        camada.selected_label = ident
        camada.brush_size = 12
        camada.mode = "paint"
    except Exception:
        pass
    pontos = viewer.add_points(np.empty((0, 2)), name="pontos", size=12,
                               face_color="yellow", border_color="black")
    # Shapes só com retângulo/elipse (o polígono-lasso é bugado nesta versão).
    formas = viewer.add_shapes(name="formas", edge_color="#00d0ff",
                               face_color=[0, 0.5, 1, 0.25], edge_width=2)

    shape = fg.shape

    def _pontos_para_regioes(v=None):
        pts = np.asarray(camada_pts(viewer))
        if len(pts) < 5:
            print("[G] preciso de >4 pontos.")
            return
        eps = 0.04 * float(np.hypot(*shape))
        cl = DBSCAN(eps=eps, min_samples=1).fit_predict(pts)
        polys = [poligono_angular(pts[cl == g]) for g in sorted(set(cl)) if (cl == g).sum() >= 5]
        n = pinta_poligonos(camada.data, polys, ident, shape)
        viewer.layers["pontos"].data = np.empty((0, 2))
        camada.refresh()
        print(f"[G] {len(pts)} pontos -> {n} região(ões) pintadas.")

    def camada_pts(v):
        return v.layers["pontos"].data

    def _formas_para_labels(v=None):
        try:
            masks = viewer.layers["formas"].to_masks(mask_shape=shape)
        except Exception as e:
            print("[M] erro ao ler formas:", e); return
        n = 0
        for m in masks:
            camada.data[np.asarray(m, bool) & fg] = ident; n += 1
        viewer.layers["formas"].data = []
        camada.refresh()
        print(f"[M] {n} forma(s) (retângulo/elipse) pintada(s).")

    def _propaga(v=None):
        propaga(camada.data, ident, stack, frac, fg, els, mineral, area_min)
        camada.refresh()

    def _limpa(v=None):
        viewer.layers["pontos"].data = np.empty((0, 2))
        viewer.layers["formas"].data = []
        print("[C] pontos e formas limpos.")

    def _ajuda(v=None):
        print(__doc__)

    for key, fn in [("g", _pontos_para_regioes), ("m", _formas_para_labels),
                    ("p", _propaga), ("c", _limpa), ("h", _ajuda)]:
        try:
            viewer.bind_key(key, fn, overwrite=True)
        except Exception as e:
            print("bind", key, "falhou:", e)

    print(__doc__)
    napari.run()

    final = np.asarray(camada.data) > 0
    novo = outros.copy()
    novo[final & (novo == 0)] = ident
    if ROT.exists():                                   # backup p/ "desfazer última revisão"
        np.save(EST / "rotulos_prev.npy", np.load(ROT))
    np.save(ROT, novo)
    np.save(EST / f"seg_seed_{args.mineral}.npy", novo == ident)
    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else []
    prog = [p for p in prog if p.get("id") != ident]
    prog.append(dict(id=ident, mineral=args.mineral, metodo="editor_completo", data=str(date.today())))
    PROG.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    previa_png(SAIDA / f"previa_{args.mineral}_pos.png", base, f"PÓS {args.mineral}", novo == ident)
    print(f"Commitado {args.mineral}: {int((novo==ident).sum())} px em {ROT}.")


if __name__ == "__main__":
    main()
