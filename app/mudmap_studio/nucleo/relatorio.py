"""Relatório da amostra — a mesma estatística do scripts/relatorio_final.py, sem matplotlib,
calculada a partir dos objetos (nucleo/objetos.py) -> refaz em milissegundos após cada edição.

Política (decisões do usuário, idênticas ao pipeline):
- grão = objeto (componente conexo por mineral) com área ≥ area_min; os menores são cimento/finos
  e ficam FORA do ternário;
- minerais `matriz: true` não são grãos: a área inteira entra na argila (fração fina não resolvida);
- ternário granulométrico por ÁREA (µm²), Wentworth: argila < 3,9 µm ≤ silte < 62,5 µm ≤ areia;
- D50 = mediana dos diâmetros equivalentes (por nº de grãos);
- composição média por mineral = fração de cátions de TODOS os pixels do mineral;
- Na-K-Ca por objeto de feldspato (≥ area_min), normalizado para Na+K+Ca = 1.
Extras do app: classe de Shepard (1954), D50 ponderado por área, finos por mineral, agregação de
vários .mudmap por campo ou por sítio (1.1 + 1.2 -> sítio 1, somando áreas) e exportação CSV/JSON.
"""
import csv
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np

from .objetos import CLASSES, LIM_ARGILA

VERSAO_CALC = 1          # sobe quando o cálculo muda (invalida o cache da comparação)

_ADJ = {("areia", "silte"): "areia siltosa", ("areia", "argila"): "areia argilosa",
        ("silte", "areia"): "silte arenoso", ("silte", "argila"): "silte argiloso",
        ("argila", "areia"): "argila arenosa", ("argila", "silte"): "argila siltosa"}


def classe_shepard(areia, silte, argila):
    """Shepard (1954): ≥ 75 % de um componente = nome puro; os três ≥ 20 % = areia-silte-argila;
    senão, o principal adjetivado pelo segundo (ex.: silte argiloso). Frações 0–1."""
    v = {"areia": float(areia), "silte": float(silte), "argila": float(argila)}
    if sum(v.values()) <= 0:
        return None
    for k, x in v.items():
        if x >= 0.75:
            return k
    if min(v.values()) >= 0.20:
        return "areia-silte-argila"
    a, b = sorted(v, key=lambda k: -v[k])[:2]
    return _ADJ[(a, b)]


def ids_matriz(am):
    return [m.id for m in am.minerais if am.regra(m.id).get("matriz")]


def _mediana_ponderada(x, w):
    if x.size == 0:
        return None
    o = np.argsort(x, kind="stable")
    c = np.cumsum(w[o])
    return float(x[o][np.searchsorted(c, 0.5 * c[-1])])


class Relatorio:
    """resumo (dict, JSON) + arrays para os gráficos."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def compacto(self):
        """O mínimo para comparar/agregar vários .mudmap (vai para o cache da comparação)."""
        r = self.resumo
        return {
            "versao_calc": VERSAO_CALC, "amostra": r["amostra"], "sitio": r["sitio"],
            "arquivo": r.get("arquivo"), "pixel_um": r["params"]["pixel_um"],
            "area_min": r["params"]["area_min"], "shape": r["shape"],
            "areas_classe_um2": self.areas_classe, "area_total_um2": self.tot,
            "area_matriz_um2": float(sum(self.area_mat.values())),
            "area_mineral_um2": {n: s["area_um2"] for n, s in r["por_mineral"].items()},
            "cores": self.cores, "n_graos": r["n_graos"],
            "diametros_um": [round(float(d), 4) for d in self.diam],
            "resolucao": r["resolucao"],
        }


def calcular(am, ob):
    px = am.pixel_um
    M = am.max_id
    nome = {m.id: m.nome for m in am.minerais}
    mat = [i for i in ids_matriz(am) if i <= M]
    eh_mat = np.zeros(M + 1, bool)
    eh_mat[mat] = True
    mineral = ob.mineral.astype(np.int64)
    grao = ~ob.sub & ~eh_mat[mineral]
    grao[0] = False
    gid = np.nonzero(grao)[0]
    diam, um2 = ob.diam[gid], ob.um2[gid]
    cls, gmin = ob.classe[gid].astype(np.int64), mineral[gid]

    area_mat = {i: float(ob.min_npx[i]) * px * px for i in mat}
    a_mat = sum(area_mat.values())
    tot = float(um2.sum()) + a_mat
    areas_classe = {c: float(um2[cls == k].sum()) + (a_mat if c == "argila" else 0.0)
                    for k, c in enumerate(CLASSES)}
    fr = {c: (areas_classe[c] / tot if tot > 0 else 0.0) for c in ("areia", "silte", "argila")}
    pct = (lambda a: 100.0 * a / tot) if tot > 0 else (lambda a: 0.0)

    # por mineral (via grão; matriz = área inteira) + extras do app
    por_mineral = {}
    for i in np.unique(gmin):
        sel = gmin == i
        a = float(um2[sel].sum())
        por_mineral[nome.get(int(i), str(i))] = {"n_graos": int(sel.sum()), "area_um2": a, "pct_area": pct(a)}
    for i, a in area_mat.items():
        por_mineral[nome[i]] = {"matriz": True, "area_um2": a, "pct_area": pct(a)}
    for i in range(1, M + 1):
        if not ob.min_npx[i] or i not in nome:
            continue
        s = por_mineral.setdefault(nome[i], {"n_graos": 0, "area_um2": 0.0, "pct_area": 0.0})
        s["pct_amostra"] = float(ob.min_pct[i])
        s["area_mineral_um2"] = float(ob.min_npx[i]) * px * px
        if not s.get("matriz"):
            s["area_finos_um2"] = s["area_mineral_um2"] - s["area_um2"]    # objetos < area_min + speckle
            sel = gmin == i
            s["d50_um"] = float(np.median(diam[sel])) if sel.any() else None

    presentes = [i for i in range(1, M + 1) if ob.min_npx[i] and i in nome]
    comp = {nome[i]: {e: float(ob.min_frac[i, j]) for j, e in enumerate(am.elementos)} for i in presentes}

    # feldspato: Na-K-Ca por objeto ≥ area_min
    id_fsp = am.id_feldspato
    pts = []
    if (id_fsp and id_fsp <= M and ob.min_npx[id_fsp] and ob.i_nkc is not None):
        for oid in np.nonzero((mineral == id_fsp) & ~ob.sub)[0]:
            if oid == 0:
                continue
            v = ob.frac[oid, list(ob.i_nkc)].astype(np.float64)
            s = v.sum()
            if s > 0:
                pts.append((float(v[0] / s), float(v[1] / s), float(v[2] / s), int(ob.area[oid]), int(oid)))

    d_min = 2 * np.sqrt(am.area_min / np.pi) * px
    fr_pct = {k: round(100 * v, 1) for k, v in fr.items()}
    resumo = {
        "amostra": am.amostra, "sitio": am.sitio, "pasta_dados": am.origem.get("pasta_dados"),
        "arquivo": str(am.caminho) if am.caminho else None,
        "n_graos": int(gid.size),
        "d50_um": float(np.median(diam)) if diam.size else None,
        "d_medio_um": float(diam.mean()) if diam.size else None,
        "d50_area_um": _mediana_ponderada(diam, um2),
        "fracoes_area": fr_pct,
        "classe_shepard": classe_shepard(fr["areia"], fr["silte"], fr["argila"]) if tot > 0 else None,
        "matriz_na_argila": {"minerais": [nome[i] for i in mat], "pct_area": round(pct(a_mat), 1)},
        "por_mineral": por_mineral,
        "composicao_frac_cations": {n: {e: round(v, 4) for e, v in d.items()} for n, d in comp.items()},
        "feldspato_objetos_nakca": [{"na": round(p[0], 3), "k": round(p[1], 3), "ca": round(p[2], 3),
                                     "area_px": p[3], "objeto": p[4]} for p in pts],
        "params": {"area_min": am.area_min, "pixel_um": px, "min_obj": ob.min_obj},
        "resolucao": {"d_min_um": round(float(d_min), 3), "argila_medida": bool(d_min < LIM_ARGILA)},
        "shape": list(am.shape), "fov_um": [round(v, 3) for v in am.fov_um],
    }
    return Relatorio(
        resumo=resumo, gid=gid, diam=diam, um2=um2, classe=cls, mineral=gmin, fsp=pts, fr=fr,
        areas_classe=areas_classe, tot=tot, area_mat=area_mat, ids_matriz=mat, presentes=presentes,
        comp=np.array([[comp[nome[i]][e] for e in am.elementos] for i in presentes], np.float64).reshape(
            len(presentes), len(am.elementos)),
        cores={m.nome: m.cor for m in am.minerais}, id_fsp=id_fsp, d_min=float(d_min),
    )


# ============================ multi-sítio ============================
def grupo_sitio(sitio):
    """Campo 1.1 -> sítio 1 (parte antes do 1º ponto)."""
    return str(sitio).split(".")[0]


def _linha(rotulo, grupo, membros):
    """Soma as áreas dos campos (µm²) — agregação exata, não média de porcentagens."""
    areas = {c: sum(m["areas_classe_um2"][c] for m in membros) for c in CLASSES}
    tot = sum(m["area_total_um2"] for m in membros)
    fr = {c: (areas[c] / tot if tot > 0 else 0.0) for c in ("areia", "silte", "argila")}
    diam = np.concatenate([np.asarray(m["diametros_um"], np.float64) for m in membros]) if membros else np.zeros(0)
    am_min = {}
    for m in membros:
        for n, a in m["area_mineral_um2"].items():
            am_min[n] = am_min.get(n, 0.0) + a
    cores = {}
    for m in membros:
        cores.update(m.get("cores", {}))
    dmins = [m["resolucao"]["d_min_um"] for m in membros]
    return {
        "rotulo": rotulo, "grupo": grupo, "campos": [m["sitio"] for m in membros],
        "n_campos": len(membros), "n_graos": int(sum(m["n_graos"] for m in membros)),
        "d50_um": float(np.median(diam)) if diam.size else None,
        "fr": fr, "area_total_um2": tot,
        "matriz_pct": 100.0 * sum(m["area_matriz_um2"] for m in membros) / tot if tot > 0 else 0.0,
        "pct_mineral": {n: (100.0 * a / tot if tot > 0 else 0.0) for n, a in am_min.items()},
        "cores": cores, "d_min_um": (min(dmins), max(dmins)) if dmins else None,
        "argila_medida": all(m["resolucao"]["argila_medida"] for m in membros),
        "classe_shepard": classe_shepard(fr["areia"], fr["silte"], fr["argila"]) if tot > 0 else None,
    }


def agregar(compactos, por="campo"):
    """-> linhas (por campo = 1 por .mudmap; por sítio = campos do mesmo sítio somados), com o
    'grupo' (sítio) de cada uma para cor/forma consistentes nas duas visões."""
    varias = len({c["amostra"] for c in compactos}) > 1
    pref = (lambda c: f"{c['amostra']} · ") if varias else (lambda c: "")
    if por == "campo":
        return [_linha(f"{pref(c)}{c['sitio']}", (c["amostra"], grupo_sitio(c["sitio"])), [c])
                for c in sorted(compactos, key=lambda c: (c["amostra"], _chave_natural(c["sitio"])))]
    grupos = {}
    for c in compactos:
        grupos.setdefault((c["amostra"], grupo_sitio(c["sitio"])), []).append(c)
    return [_linha(f"{pref(ms[0])}sítio {g[1]}", g, sorted(ms, key=lambda c: _chave_natural(c["sitio"])))
            for g, ms in sorted(grupos.items(), key=lambda kv: (kv[0][0], _chave_natural(kv[0][1])))]


def _chave_natural(s):
    return [int(t) if t.isdigit() else t for t in str(s).replace("-", ".").split(".")]


def resumo_de_arquivo(caminho, progresso=None, cache_dir=None):
    """Compacto de um .mudmap no disco (abre, separa os grãos, calcula). Usa cache em JSON
    (chave = caminho + data + tamanho + VERSAO_CALC) para não recalcular 4096² a cada abertura."""
    from . import objetos, pacote
    prog = progresso or (lambda f, m: None)
    caminho = Path(caminho)
    st = caminho.stat()
    chave = f"{caminho.resolve()}|{st.st_mtime_ns}|{st.st_size}|{VERSAO_CALC}"
    arq_cache = Path(cache_dir) / "cache_relatorio.json" if cache_dir else None
    cache = {}
    if arq_cache and arq_cache.exists():
        try:
            cache = json.loads(arq_cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    if chave in cache:
        prog(1.0, "do cache")
        return cache[chave]
    am = pacote.abrir(caminho, lambda f, m: prog(0.4 * f, m))
    ob = objetos.calcular(am, 3, lambda f, m: prog(0.4 + 0.55 * f, m))
    c = calcular(am, ob).compacto()
    c["arquivo"] = str(caminho)
    if arq_cache:
        cache = {k: v for k, v in cache.items() if not k.startswith(f"{caminho.resolve()}|")}
        cache[chave] = c
        while len(cache) > 60:
            cache.pop(next(iter(cache)))
        arq_cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq_cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, arq_cache)
    prog(1.0, "pronto")
    return c


def sitio_do_arquivo(caminho):
    """(amostra, sítio) do manifest sem abrir os mapas."""
    with zipfile.ZipFile(caminho) as z:
        man = json.loads(z.read("manifest.json").decode("utf-8"))
    return man.get("amostra", "?"), man.get("sitio", "?")


# ============================ exportação ============================
def _num(v, d=6):
    if v is None:
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "sim" if v else "não"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    return f"{float(v):.{d}g}".replace(".", ",")


def _csv(linhas):
    """CSV no padrão do Excel pt-BR: ';' + vírgula decimal + BOM UTF-8."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    for l in linhas:
        w.writerow([x if isinstance(x, str) else _num(x) for x in l])
    return "﻿" + buf.getvalue()


def json_resumo(rel, versao_app=""):
    r = dict(rel.resumo)
    r["gerado_em"] = datetime.now().isoformat(timespec="seconds")
    r["app"] = f"MudMap Studio {versao_app}".strip()
    return json.dumps(r, ensure_ascii=False, indent=2)


def csv_minerais(rel, am):
    els = am.elementos
    cab = ["mineral", "matriz", "n_graos", "area_graos_um2", "pct_area_relatorio", "d50_um",
           "area_finos_um2", "area_mineral_um2", "pct_amostra"] + [f"frac_{e}" for e in els]
    linhas = [cab]
    comp = rel.resumo["composicao_frac_cations"]
    for n, s in sorted(rel.resumo["por_mineral"].items(), key=lambda kv: -kv[1]["pct_area"]):
        linhas.append([n, bool(s.get("matriz")), s.get("n_graos"), s["area_um2"], s["pct_area"], s.get("d50_um"),
                       s.get("area_finos_um2"), s.get("area_mineral_um2"), s.get("pct_amostra")] +
                      [comp.get(n, {}).get(e) for e in els])
    return _csv(linhas)


def csv_graos(ob, am):
    """Todos os objetos (≥ min_obj px): grão = ≥ area_min e não matriz."""
    els = am.elementos
    nome = {m.id: m.nome for m in am.minerais}
    linhas = [["objeto", "mineral", "classe", "grao", "area_px", "area_um2", "diametro_um",
               "x0", "y0", "x1", "y1"] + [f"frac_{e}" for e in els] + [f"bruto_{e}" for e in els]]
    for i in range(1, ob.n + 1):
        cl = "matriz" if ob.matriz[i] else CLASSES[int(ob.classe[i])]
        linhas.append([int(i), nome.get(int(ob.mineral[i]), "?"), cl, not (ob.sub[i] or ob.matriz[i]),
                       int(ob.area[i]), float(ob.um2[i]), float(ob.diam[i]), *[int(v) for v in ob.bbox[i]]] +
                      [float(v) for v in ob.frac[i]] + [float(v) for v in ob.raw[i]])
    return _csv(linhas)


def csv_comparacao(linhas_ag, por):
    minerais = sorted({n for l in linhas_ag for n in l["pct_mineral"]})
    cab = ["campo" if por == "campo" else "sitio", "campos", "n_graos", "d50_um", "areia_pct", "silte_pct",
           "argila_pct", "matriz_pct", "classe_shepard", "d_min_um", "argila_medida", "area_total_um2"] + \
          [f"pct_{n}" for n in minerais]
    out = [cab]
    for l in linhas_ag:
        dm = l["d_min_um"]
        out.append([l["rotulo"], " + ".join(l["campos"]), l["n_graos"], l["d50_um"],
                    100 * l["fr"]["areia"], 100 * l["fr"]["silte"], 100 * l["fr"]["argila"], l["matriz_pct"],
                    l["classe_shepard"] or "", (dm[0] if dm and dm[0] == dm[1] else
                                                (f"{_num(dm[0], 3)}–{_num(dm[1], 3)}" if dm else None)),
                    l["argila_medida"], l["area_total_um2"]] + [l["pct_mineral"].get(n, 0.0) for n in minerais])
    return _csv(out)


def json_comparacao(linhas_ag, por, versao_app=""):
    return json.dumps({"agregacao": por, "gerado_em": datetime.now().isoformat(timespec="seconds"),
                       "app": f"MudMap Studio {versao_app}".strip(),
                       "linhas": [{**l, "d_min_um": list(l["d_min_um"]) if l["d_min_um"] else None,
                                   "grupo": list(l["grupo"])} for l in linhas_ag]},
                      ensure_ascii=False, indent=2)
