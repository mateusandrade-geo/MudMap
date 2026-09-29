"""Inspetor HTML (scripts/inspetor_template.html) gerado a partir da amostra do app.

Mesmos dados do scripts/exportar_graos.py (graos.json + composto BSE + mapa de ids), mas num
ARQUIVO ÚNICO: as duas imagens vão embutidas como data URI (dá para mandar por e-mail).
"""
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .cores import hex_rgb
from .objetos import CLASSES

MAX_OBJ = 65535          # o mapa de ids guarda o objeto em R + G*256


def caminho_template():
    from . import pipeline
    cands = [pipeline._SCRIPTS / "inspetor_template.html"]
    if getattr(sys, "_MEIPASS", None):                         # .exe (PyInstaller --add-data)
        cands.insert(0, Path(sys._MEIPASS) / "scripts" / "inspetor_template.html")
    for c in cands:
        if c.exists():
            return c
    raise FileNotFoundError("inspetor_template.html não encontrado (scripts/ do projeto).")


def _png_uri(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", compress_level=6)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _composto(am, alfa=0.62):
    """BSE esticada (mín–máx) + TODOS os pixels classificados na cor do mineral."""
    g = (am.bse if am.bse is not None else np.clip(am.soma, 0, 255)).astype(np.float32)
    g -= g.min()
    g = 255.0 * g / (g.max() + 1e-9)
    vis = np.repeat(g[..., None], 3, axis=2)
    lut = np.zeros((max(am.max_id, int(am.rotulos.max(initial=0))) + 1, 3), np.float32)
    for m in am.minerais:
        lut[m.id] = hex_rgb(m.cor)
    sel = am.rotulos > 0
    vis[sel] = (1 - alfa) * vis[sel] + alfa * lut[am.rotulos[sel]]
    return np.clip(vis, 0, 255).astype(np.uint8)


def dados(am, ob):
    """{meta, graos} no formato do exportar_graos.py; ids > 65 535 -> mantém os maiores."""
    H, W = am.shape
    nome = {m.id: m.nome for m in am.minerais}
    ids = np.arange(1, ob.n + 1)
    omitidos = 0
    if ob.n > MAX_OBJ:
        ids = np.sort(ids[np.argsort(ob.area[1:], kind="stable")[::-1][:MAX_OBJ]])
        omitidos = ob.n - MAX_OBJ
    novo = np.zeros(ob.n + 1, np.int32)
    novo[ids] = np.arange(1, ids.size + 1, dtype=np.int32)
    flat = ob.objid.ravel()
    cx = np.bincount(flat, weights=np.tile(np.arange(W, dtype=np.float64), H), minlength=ob.n + 1)
    cy = np.bincount(flat, weights=np.repeat(np.arange(H, dtype=np.float64), W), minlength=ob.n + 1)
    a = np.maximum(ob.area, 1)
    cx, cy = cx / a, cy / a
    graos = []
    for i in ids:
        mid = int(ob.mineral[i])
        g = {"id": int(novo[i]), "m": nome.get(mid, str(mid)), "a": int(ob.area[i]),
             "um2": round(float(ob.um2[i]), 3), "d": round(float(ob.diam[i]), 3),
             "cl": "matriz" if ob.matriz[i] else CLASSES[int(ob.classe[i])],
             "cx": round(float(cx[i]), 1), "cy": round(float(cy[i]), 1),
             "bb": [int(v) for v in ob.bbox[i]],
             "c": [round(float(v), 4) for v in ob.frac[i]], "r": [round(float(v), 1) for v in ob.raw[i]],
             "sub": bool(ob.sub[i])}
        if mid == am.id_feldspato:
            nk = ob.nk(int(i))
            if nk:
                g["nk"] = [round(float(v), 3) for v in nk]
        graos.append(g)
    minerais = {}
    for m in am.minerais:
        if m.id < len(ob.min_npx) and ob.min_npx[m.id]:
            minerais[m.nome] = {"id": m.id, "cor": m.cor, "npx": int(ob.min_npx[m.id]),
                                "pct": round(float(ob.min_pct[m.id]), 2),
                                "c": [round(float(v), 4) for v in ob.min_frac[m.id]],
                                "r": [round(float(v), 1) for v in ob.min_raw[m.id]]}
    meta = {"sitio": am.titulo, "pixel_um": am.pixel_um, "shape": [H, W],
            "fov_um": [round(W * am.pixel_um, 1), round(H * am.pixel_um, 1)],
            "elementos": am.elementos, "area_min": am.area_min, "min_obj": ob.min_obj,
            "minerais": minerais, "n_obj": len(graos),
            "n_graos": int(sum(1 for g in graos if not g["sub"] and g["cl"] != "matriz")),
            "objetos_omitidos": omitidos}
    idmap = np.zeros((H, W, 3), np.uint8)
    oid = novo[ob.objid]
    idmap[..., 0] = (oid & 0xFF).astype(np.uint8)
    idmap[..., 1] = ((oid >> 8) & 0xFF).astype(np.uint8)
    idmap[..., 2] = np.clip(am.rotulos, 0, 255).astype(np.uint8)
    return {"meta": meta, "graos": graos}, idmap


def exportar(am, ob, destino, progresso=None):
    prog = progresso or (lambda f, m: None)
    tmpl = caminho_template().read_text(encoding="utf-8")
    prog(0.1, "grãos")
    d, idmap = dados(am, ob)
    prog(0.5, "imagens")
    html = tmpl.replace("__DATA__", json.dumps(d, ensure_ascii=False).replace("</", "<\\/"))
    for nome, arr in (("graos_bse.png", _composto(am)), ("graos_idmap.png", idmap)):
        if html.count(f"'{nome}'") != 1:
            raise ValueError(f"template do inspetor mudou: referência a {nome} não encontrada")
        html = html.replace(f"'{nome}'", f"'{_png_uri(arr)}'")
    destino = Path(destino)
    destino.write_text(html, encoding="utf-8")
    prog(1.0, "pronto")
    return destino
