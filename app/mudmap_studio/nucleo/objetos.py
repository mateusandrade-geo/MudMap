"""Objetos (grãos) = componentes conexos POR mineral em rotulos, como no exportar_graos.py.

Toda a estatística sai de np.bincount canal a canal (composição média em fração e em
intensidade bruta, por objeto e por mineral), sem materializar pilhas float HxWxN —
escala para 4096². Objetos < min_obj px (speckle) não viram objeto clicável, mas os
pixels continuam no mineral (a sonda devolve a média do mineral).
"""
import numpy as np
from scipy import ndimage as ndi

LIM_ARGILA = 3.9     # µm (Wentworth) — igual ao relatorio_final.py
LIM_AREIA = 62.5
CLASSES = ("argila", "silte", "areia")


class Objetos:
    """Arrays indexados pelo id do objeto (0 = nenhum)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def nk(self, oid):
        """(na, k, ca) normalizados ou None (sem Na no dataset)."""
        if self.i_nkc is None:
            return None
        v = self.frac[oid, list(self.i_nkc)]
        s = float(v.sum())
        return tuple(float(a) / s for a in v) if s > 0 else None

    def nk_mineral(self, mid):
        if self.i_nkc is None:
            return None
        v = self.min_frac[mid, list(self.i_nkc)]
        s = float(v.sum())
        return tuple(float(a) / s for a in v) if s > 0 else None


def calcular(am, min_obj=3, progresso=None):
    prog = progresso or (lambda f, msg: None)
    rot = am.rotulos
    H, W = rot.shape
    presentes = [int(v) for v in np.unique(rot) if v > 0]

    # ---- rotulagem por mineral -> id global ----
    objid = np.zeros((H, W), np.int32)
    prox = 0
    for k, mid in enumerate(presentes):
        prog(0.05 + 0.35 * k / max(1, len(presentes)), f"separando grãos ({am.mineral(mid).nome if am.mineral(mid) else mid})")
        lab, n = ndi.label(rot == mid)
        if n:
            sel = lab > 0
            objid[sel] = lab[sel] + prox
            prox += n
        del lab

    # ---- descarta speckle < min_obj e renumera 1..n ----
    area_bruta = np.bincount(objid.ravel(), minlength=prox + 1)
    manter = area_bruta >= min_obj
    manter[0] = False
    remap = np.zeros(prox + 1, np.int32)
    n = int(manter.sum())
    remap[manter] = np.arange(1, n + 1, dtype=np.int32)
    objid = remap[objid]
    area = np.zeros(n + 1, np.int64)
    area[1:] = area_bruta[manter]
    del remap, area_bruta

    flat_o = objid.ravel()
    flat_r = rot.ravel()
    mineral = np.zeros(n + 1, np.int16)
    mineral[flat_o] = flat_r
    mineral[0] = 0

    # ---- bbox (x0, y0, x1, y1) exclusivo ----
    prog(0.45, "caixas dos grãos")
    bbox = np.zeros((n + 1, 4), np.int32)
    for i, sl in enumerate(ndi.find_objects(objid), start=1):
        if sl is not None:
            bbox[i] = (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)

    # ---- composição média por objeto e por mineral ----
    N = len(am.elementos)
    M = am.max_id
    frac = np.zeros((n + 1, N), np.float32)
    raw = np.zeros((n + 1, N), np.float32)
    min_npx = np.bincount(flat_r, minlength=M + 1)[:M + 1].astype(np.int64)
    min_frac = np.zeros((M + 1, N), np.float32)
    min_raw = np.zeros((M + 1, N), np.float32)
    a_obj = np.maximum(area, 1)
    a_min = np.maximum(min_npx, 1)
    inv = am.inv_soma.ravel()
    for i, mapa in enumerate(am.mapas):
        prog(0.5 + 0.45 * i / N, f"composição ({am.elementos[i]})")
        w_raw = mapa.ravel().astype(np.float32)
        raw[:, i] = np.bincount(flat_o, weights=w_raw, minlength=n + 1) / a_obj
        min_raw[:, i] = np.bincount(flat_r, weights=w_raw, minlength=M + 1)[:M + 1] / a_min
        w_f = w_raw * inv
        frac[:, i] = np.bincount(flat_o, weights=w_f, minlength=n + 1) / a_obj
        min_frac[:, i] = np.bincount(flat_r, weights=w_f, minlength=M + 1)[:M + 1] / a_min
        del w_raw, w_f

    px = am.pixel_um
    um2 = area * px * px
    diam = 2.0 * np.sqrt(um2 / np.pi)
    classe = np.digitize(diam, (LIM_ARGILA, LIM_AREIA)).astype(np.int8)   # 0 argila · 1 silte · 2 areia
    # minerais `matriz: true` (config) não são grãos: a área inteira conta como argila (relatorio_final.py)
    matriz = np.isin(mineral, [m.id for m in am.minerais if am.regra(m.id).get("matriz")])
    matriz[0] = False
    classe[matriz] = 0
    sub = area < am.area_min
    sub[0] = False
    n_mask = max(1, int(am.mascara.sum()))

    i_nkc = None
    if am.tem_na and "K" in am.elementos and "Ca" in am.elementos:
        i_nkc = (am.indice("Na"), am.indice("K"), am.indice("Ca"))

    prog(1.0, "pronto")
    return Objetos(
        objid=objid, rotulos=rot, n=n, mineral=mineral, area=area, bbox=bbox,
        frac=frac, raw=raw, um2=um2, diam=diam, classe=classe, sub=sub, matriz=matriz,
        min_npx=min_npx, min_frac=min_frac, min_raw=min_raw,
        min_pct=100.0 * min_npx / n_mask,
        n_obj_min=np.bincount(mineral[1:], minlength=M + 1),
        i_nkc=i_nkc, min_obj=min_obj,
    )


def classificar_feldspato(na, k, ca):
    if k >= 0.5:
        return "K-feldspato (ortoclásio)"
    if na >= 0.5:
        return "plagioclásio sódico (albita)"
    if ca >= 0.5:
        return "plagioclásio cálcico (anortita)"
    return "feldspato intermediário"
