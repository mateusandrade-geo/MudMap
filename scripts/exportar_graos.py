"""Exporta dados por GRÃO para o inspetor HTML interativo.

Gera em saida/graos/:
  - graos_bse.png   : composto visível (BSE em cinza + TODOS os pixels classificados,
                      coloridos por mineral) = máscara final.
  - graos_idmap.png : R + G*256 = id do OBJETO (componentes >= --min-obj);
                      canal B = id do MINERAL (1..N) de CADA pixel classificado.
                      Assim o clique num speck fino (sem objeto próprio) ainda
                      recupera o mineral e mostra a composição média dele.
  - graos.json      : meta + objetos {id, mineral, área, diâmetro, classe, bbox,
                      composição em FRAÇÃO e em INTENSIDADE BRUTA, Na-K-Ca p/ feldspato,
                      flag sub (área < area_min)} + tabela por mineral (fallback).

Objetos ABAIXO de area_min ENTRAM (marcados sub=true); só o speckle < --min-obj px
(default 3) é descartado como ruído.

Uso: PYTHONPATH=scripts python scripts/exportar_graos.py [--min-obj 3]
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage.measure import regionprops
from matplotlib.colors import to_rgb

import common
from relatorio_final import carregar_bse, classe_wentworth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/classificacao.yaml")
    ap.add_argument("--min-obj", type=int, default=3,
                    help="área mínima (px) p/ um objeto virar clicável (dropa speckle)")
    ap.add_argument("--estado", default="estado",
                    help="pasta com rotulos.npy (sítio arquivado: sitios/<s>/estado)")
    args = ap.parse_args()

    cfg = common.carregar_config(args.config)
    pasta = cfg["pasta_dados"]
    px = float(cfg["pixel_um"])
    elementos = cfg["elementos"]
    area_min = int(cfg.get("area_min", 30))

    stack, overlay = common.carregar_mapas(pasta, elementos)
    frac, soma = common.fracao_cations(stack)
    mask = common.mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, elementos)
    gray = carregar_bse(pasta, ref_shape=mask.shape)

    rotulos = np.load(Path(args.estado) / "rotulos.npy")
    H, W = rotulos.shape
    cores = {i: m["cor"] for i, m in enumerate(cfg["minerais"], start=1)}
    nomes = {i: m["nome"] for i, m in enumerate(cfg["minerais"], start=1)}
    id_fsp = next((i for i, m in enumerate(cfg["minerais"], start=1)
                   if m.get("feldspato") or m["nome"] == "feldspato"), None)
    tem_na = "Na" in elementos   # sem Na (ex.: sítio 1.2) -> ternário de feldspato desativado
    iNa = elementos.index("Na") if tem_na else None
    iK, iCa = elementos.index("K"), elementos.index("Ca")

    def med(coords, arr):
        return arr[coords[:, 0], coords[:, 1]].mean(axis=0)

    # ---- objetos = componentes conexos por mineral (>= min_obj) ----
    objid = np.zeros((H, W), dtype=np.int32)     # id do objeto por pixel
    minid = np.zeros((H, W), dtype=np.uint8)     # id do mineral por pixel (todos)
    graos = []
    gid = 0
    for i in range(1, len(cfg["minerais"]) + 1):
        mi = rotulos == i
        if not mi.any():
            continue
        minid[mi] = i
        lab = ndi.label(mi)[0]
        for r in regionprops(lab):
            if r.area < args.min_obj:
                continue
            gid += 1
            coords = r.coords
            objid[coords[:, 0], coords[:, 1]] = gid
            mf = med(coords, frac)
            mr = med(coords, stack)
            area_um2 = r.area * px * px
            d_um = 2 * np.sqrt(area_um2 / np.pi)
            g = {
                "id": gid, "m": nomes[i],
                "a": int(r.area), "um2": round(area_um2, 3), "d": round(float(d_um), 3),
                # matriz (config `matriz: true`) não é grão: conta como argila no relatório
                "cl": "matriz" if cfg["minerais"][i - 1].get("matriz") else classe_wentworth(d_um),
                "cx": round(float(r.centroid[1]), 1), "cy": round(float(r.centroid[0]), 1),
                "bb": [int(r.bbox[1]), int(r.bbox[0]), int(r.bbox[3]), int(r.bbox[2])],
                "c": [round(float(v), 4) for v in mf],
                "r": [round(float(v), 1) for v in mr],
                "sub": bool(r.area < area_min),
            }
            if i == id_fsp and tem_na:
                s = mf[iNa] + mf[iK] + mf[iCa]
                if s > 0:
                    g["nk"] = [round(float(mf[iNa] / s), 3),
                               round(float(mf[iK] / s), 3), round(float(mf[iCa] / s), 3)]
            graos.append(g)

    # ---- tabela por mineral (fallback p/ pixels sem objeto próprio) ----
    minerais = {}
    for i in range(1, len(cfg["minerais"]) + 1):
        mi = rotulos == i
        if not mi.any():
            continue
        cc = np.array(np.nonzero(mi)).T
        minerais[nomes[i]] = {
            "id": i, "cor": cores[i], "npx": int(mi.sum()),
            "pct": round(100 * mi.sum() / max(1, mask.sum()), 2),
            "c": [round(float(v), 4) for v in med(cc, frac)],
            "r": [round(float(v), 1) for v in med(cc, stack)],
        }

    # ---- mapa de IDs: R+G = objeto, B = mineral ----
    idmap_rgb = np.zeros((H, W, 3), dtype=np.uint8)
    idmap_rgb[..., 0] = (objid & 0xFF).astype(np.uint8)
    idmap_rgb[..., 1] = ((objid >> 8) & 0xFF).astype(np.uint8)
    idmap_rgb[..., 2] = minid

    # ---- composto visível: BSE + TODOS os pixels classificados coloridos ----
    g0 = gray - gray.min()
    g0 = (255 * g0 / (g0.max() + 1e-9)).astype(np.uint8)
    vis = np.dstack([g0, g0, g0]).astype(float)
    alpha = 0.62
    id2rgb = {i: np.array(to_rgb(c)) * 255 for i, c in cores.items()}
    ys, xs = np.nonzero(minid > 0)
    cor_pix = np.array([id2rgb[k] for k in minid[ys, xs]])
    vis[ys, xs] = (1 - alpha) * vis[ys, xs] + alpha * cor_pix
    vis = vis.clip(0, 255).astype(np.uint8)

    out = Path("saida/graos"); out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(vis).save(out / "graos_bse.png")
    Image.fromarray(idmap_rgb).save(out / "graos_idmap.png")

    meta = {
        "sitio": pasta, "pixel_um": px, "shape": [H, W],
        "fov_um": [round(W * px, 1), round(H * px, 1)],
        "elementos": elementos, "area_min": area_min, "min_obj": args.min_obj,
        "minerais": minerais, "n_obj": len(graos),
        "n_graos": int(sum(1 for g in graos if not g["sub"] and g["cl"] != "matriz")),
    }
    dados_json = json.dumps({"meta": meta, "graos": graos}, ensure_ascii=False)
    (out / "graos.json").write_text(dados_json, encoding="utf-8")

    # monta o inspetor a partir do template (dados INLINE -> reprodutível por código)
    tmpl_path = Path(__file__).with_name("inspetor_template.html")
    if tmpl_path.exists():
        html = tmpl_path.read_text(encoding="utf-8").replace("__DATA__", dados_json)
        (out / "index.html").write_text(html, encoding="utf-8")
    else:
        print("AVISO: scripts/inspetor_template.html ausente — index.html não montado.")

    n_sub = sum(1 for g in graos if g["sub"])
    print(f"objetos: {len(graos)}  (>= area_min: {meta['n_graos']}, "
          f"< area_min: {n_sub})  min_obj={args.min_obj}px  ->  {out}")
    print(f"inspetor: {out / 'index.html'}")


if __name__ == "__main__":
    main()
