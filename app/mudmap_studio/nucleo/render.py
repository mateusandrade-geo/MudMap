"""Composição da imagem exibida (sem Qt; roda numa thread de fundo).

Fundo, um de:
  bse      Electron Image com contraste (lo, hi)
  aditivo  camadas de elementos somadas (blending aditivo estilo napari), cada uma com cor e
           contraste próprios, em intensidade BRUTA (0–255) ou FRAÇÃO de cátions — o composto
           RGB é o caso de 3 camadas em vermelho/verde/azul puros
  canal    canal derivado das regras ('Si-Mg', 'Al/Si', 'Fe+Mg', ou um elemento) em fração ou
           bruto, opcionalmente SUAVIZADO com a média mascarada do segmentar.py, num mapa de cores
Sobreposições: escurecer fora da amostra, clusters k-means, minerais (preenchidos ou contorno).

Minerais: cada pixel recebe um índice numa LUT calculada UMA vez (1..n objetos; n+m pixel fino
do mineral m; 0 sem classe) -> trocar visibilidade/solo/cor/opacidade só refaz a LUT.
Tudo em blocos de 512 linhas: memória limitada mesmo em 4096².
"""
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from . import cores
from .amostra import elementos_da_expr
from .pipeline import common, segmentar

BLOCO = 512
hex_rgb = cores.hex_rgb


@dataclass
class CamadaEl:
    el: str
    cor: str
    lo: float
    hi: float


@dataclass
class Visual:
    fundo: str = "bse"                 # "bse" | "aditivo" | "canal"
    bse_lim: tuple = None              # (lo, hi) 0–255; None = automático
    tipo_el: str = "raw"               # camadas aditivas: "raw" | "frac"
    camadas: list = field(default_factory=list)
    canal_expr: str = "Si-Mg"
    canal_tipo: str = "frac"
    canal_raio: int = 0
    canal_cmap: str = "viridis"
    canal_lim: tuple = None            # None = automático (percentis)
    minerais: bool = True
    estilo: str = "preenchido"         # "preenchido" | "contorno"
    colorir: str = "mineral"           # "mineral" | "tamanho"
    ocultos: set = field(default_factory=set)
    solo: int = None
    opacidade: float = 0.62
    graos: bool = True
    finos: bool = True
    clusters: bool = False
    clusters_opac: float = 0.5
    clusters_ocultos: set = field(default_factory=set)
    escurecer_fora: bool = False
    por_rotulo: bool = False           # edição: cor direto de rotulos (objetos podem estar desatualizados)
    versao: int = 0                    # versão da edição no pedido (descarta resultados velhos)


def _lut_contraste(lo, hi):
    x = np.arange(256, dtype=np.float32)
    return np.clip((x - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint16)


def _hist_amostra(v, x0, x1, bins=160):
    h, _ = np.histogram(v, bins=bins, range=(x0, x1))
    return h


class Compositor:
    def __init__(self, am, ob, cores_tamanho):
        self.am, self.ob = am, ob
        self.cores_tamanho = [hex_rgb(c) for c in cores_tamanho]
        n = ob.n
        idx = ob.objid.copy()
        fino = (idx == 0) & (am.rotulos > 0)
        idx[fino] = n + am.rotulos[fino].astype(np.int32)
        self.idx = idx
        self._lock = threading.Lock()
        self._canais = OrderedDict()
        self._hist = {}
        self._sub = am.mascara[::2, ::2]

    # ---------- dados ----------
    def borda(self, y0, y1, x0, x1):
        """Borda interna de 2 px das regiões minerais na janela (estilo contorno). Calculada
        por janela (com margem) -> sempre em dia com as edições, sem cache global."""
        r = self.am.rotulos
        H, W = r.shape
        a0, a1, b0, b1 = max(0, y0 - 2), min(H, y1 + 2), max(0, x0 - 2), min(W, x1 + 2)
        w = r[a0:a1, b0:b1]
        b = np.zeros(w.shape, bool)
        for d in (1, 2):
            b[d:, :] |= w[d:, :] != w[:-d, :]
            b[:-d, :] |= w[:-d, :] != w[d:, :]
            b[:, d:] |= w[:, d:] != w[:, :-d]
            b[:, :-d] |= w[:, :-d] != w[:, d:]
        b &= w > 0
        return b[y0 - a0:y0 - a0 + (y1 - y0), x0 - b0:x0 - b0 + (x1 - x0)]

    def validar_expr(self, expr):
        toks = elementos_da_expr(expr)
        if not toks:
            raise ValueError("Escreva um elemento ou uma expressão, ex.: Si-Mg, Al/Si, Fe+Mg.")
        falta = [t for t in toks if t not in self.am.elementos]
        if falta:
            raise ValueError(f"Sem mapa para {', '.join(falta)} nesta amostra "
                             f"(disponíveis: {', '.join(self.am.elementos)}).")
        if sum(expr.count(s) for s in "+-/") > 1 and ("/" in expr or "-" in expr):
            raise ValueError("Use uma operação por vez: A-B, A/B ou soma A+B+C.")

    def canal(self, expr, tipo, raio):
        """(array float32, estatística) do canal derivado — cache LRU de 3 (64 MB cada em 4096²)."""
        chave = (expr.replace(" ", ""), tipo, int(raio))
        with self._lock:
            if chave in self._canais:
                self._canais.move_to_end(chave)
                return self._canais[chave]
        self.validar_expr(chave[0])
        am = self.am
        base = common.canal(am.vista(tipo), am.elementos, chave[0])
        if chave[2] > 1:
            base = segmentar._suave_mascarado(base, am.mascara, chave[2])
        arr = np.ascontiguousarray(base, dtype=np.float32)
        arr[~am.mascara] = np.nan                     # fora da amostra: sem valor (desenhado escuro)
        v = arr[::2, ::2][self._sub]
        v = v[np.isfinite(v)]
        if v.size == 0:
            v = np.zeros(1, np.float32)
        a0, a1, p0, p1 = np.percentile(v, [0.05, 99.95, 0.5, 99.5])
        if a1 <= a0:
            a1 = a0 + 1e-3
        pad = 0.04 * (a1 - a0)
        x0, x1 = float(a0 - pad), float(a1 + pad)
        st = {"hist": _hist_amostra(v, x0, x1), "x0": x0, "x1": x1,
              "auto": (float(p0), float(p1) if p1 > p0 else float(p0) + 1e-3),
              "min": float(v.min()), "max": float(v.max())}
        with self._lock:
            self._canais[chave] = (arr, st)
            while len(self._canais) > 3:
                self._canais.popitem(last=False)
        return arr, st

    def canal_em_cache(self, expr, tipo, raio):
        with self._lock:
            return self._canais.get((expr.replace(" ", ""), tipo, int(raio)))

    def histograma(self, fonte):
        """fonte: ("bse",) | ("raw", i) | ("frac", i). -> {hist, x0, x1, auto}"""
        with self._lock:
            if fonte in self._hist:
                return self._hist[fonte]
        am = self.am
        if fonte[0] in ("bse", "raw"):
            src = (am.bse if am.bse is not None else am.mapas[0]) if fonte[0] == "bse" else am.mapas[fonte[1]]
            h = np.bincount(src[::2, ::2][self._sub], minlength=256)[:256]
            c = np.cumsum(h) / max(1, h.sum())
            lo = float(np.searchsorted(c, 0.005))
            hi = float(np.searchsorted(c, 0.997))
            st = {"hist": h, "x0": 0.0, "x1": 255.0, "auto": (lo, max(hi, lo + 1))}
        else:
            v = am.frac(fonte[1])[::2, ::2][self._sub]
            p0, p1, p9 = np.percentile(v, [0.5, 99.7, 99.9]) if v.size else (0, 1, 1)
            x1 = float(min(1.0, max(0.05, p9 * 1.15)))
            st = {"hist": _hist_amostra(v, 0.0, x1), "x0": 0.0, "x1": x1,
                  "auto": (float(p0), float(max(p1, p0 + 1e-3)))}
        with self._lock:
            self._hist[fonte] = st
        return st

    # ---------- LUTs das sobreposições ----------
    def luts(self, v):
        am, ob = self.am, self.ob
        n, M = ob.n, am.max_id
        cor_min = np.zeros((M + 1, 3), np.uint16)
        alfa_min = np.zeros(M + 1, np.float32)
        for m in am.minerais:
            cor_min[m.id] = hex_rgb(m.cor)
            vis = v.minerais and m.id not in v.ocultos and (v.solo is None or v.solo == m.id)
            alfa_min[m.id] = v.opacidade if vis else 0.0
        L = n + M + 1
        cor = np.zeros((L, 3), np.uint16)
        alfa = np.zeros(L, np.float32)
        mo = ob.mineral[1:].astype(np.int64)
        if v.colorir == "tamanho":
            ct = np.array(self.cores_tamanho, np.uint16)
            cor[1:n + 1] = ct[ob.classe[1:]]
            cor[n + 1:] = ct[0]
        else:
            cor[1:n + 1] = cor_min[mo]
            cor[n + 1:] = cor_min[1:]
        filtro = np.where(ob.sub[1:], v.finos, v.graos).astype(np.float32)
        alfa[1:n + 1] = alfa_min[mo] * filtro
        alfa[n + 1:] = alfa_min[1:] * float(v.finos)
        return cor, np.rint(alfa * 256).astype(np.uint16)

    def luts_rotulo(self, v):
        """LUT por id de mineral (modo edição)."""
        am = self.am
        M = max(am.max_id, 255 if am.rotulos.dtype == np.uint8 else am.max_id)   # LUT cobre todo id possível
        cor = np.zeros((M + 1, 3), np.uint16)
        alfa = np.zeros(M + 1, np.float32)
        for m in am.minerais:
            cor[m.id] = hex_rgb(m.cor)
            vis = v.minerais and m.id not in v.ocultos and (v.solo is None or v.solo == m.id)
            alfa[m.id] = v.opacidade if vis else 0.0
        return cor, np.rint(alfa * 256).astype(np.uint16)

    def luts_clusters(self, v):
        K = int(self.am.clusters.max())
        cor = np.zeros((K + 1, 3), np.uint16)
        alfa = np.zeros(K + 1, np.uint16)
        a = int(round(v.clusters_opac * 256))
        for k in range(1, K + 1):
            cor[k] = hex_rgb(cores.CORES_CLUSTER[(k - 1) % len(cores.CORES_CLUSTER)])
            alfa[k] = 0 if k in v.clusters_ocultos else a
        return cor, alfa

    # ---------- composição ----------
    def _preparar(self, v):
        """LUTs e dados do visual (uma vez por composição)."""
        am = self.am
        c = {"info": {}}
        if v.fundo == "canal":
            arr, st = self.canal(v.canal_expr, v.canal_tipo, v.canal_raio)
            lo, hi = v.canal_lim or st["auto"]
            c["info"].update(canal_lim=(lo, hi), canal_stats=st)
            c.update(arr=arr, lo=lo, cmap=cores.lut(v.canal_cmap).astype(np.uint16),
                     esc=255.0 / max(hi - lo, 1e-12))
        elif v.fundo == "aditivo":
            c["prep"] = [(am.indice(k.el), _lut_contraste(k.lo, k.hi) if v.tipo_el == "raw" else None,
                          k.lo, k.hi, np.array(hex_rgb(k.cor), np.uint16)) for k in v.camadas]
        else:
            lo, hi = v.bse_lim or self.histograma(("bse",))["auto"]
            c.update(src=am.bse if am.bse is not None else am.mapas[0], lut_bse=_lut_contraste(lo, hi))
        if v.minerais:
            c["mins"] = self.luts_rotulo(v) if v.por_rotulo else self.luts(v)
            c["fonte_min"] = am.rotulos if v.por_rotulo else self.idx
        c["clus"] = self.luts_clusters(v) if (v.clusters and am.clusters is not None) else None
        return c

    def _bloco(self, v, c, y0, y1, x0, x1, p):
        """Composição (uint16 h×w×3) da janela [y0:y1, x0:x1] amostrada a cada p px."""
        am = self.am
        fat = lambda a: a[y0:y1:p, x0:x1:p]
        if v.fundo == "canal":
            x = fat(c["arr"])
            t = np.nan_to_num((x - c["lo"]) * c["esc"], nan=0.0)
            b = c["cmap"][np.clip(t, 0, 255).astype(np.uint8)]
            nan = np.isnan(x)
            if nan.any():
                b[nan] = (18, 20, 23)
        elif v.fundo == "aditivo":
            b = np.zeros((len(range(y0, y1, p)), len(range(x0, x1, p)), 3), np.uint32)
            for i, lut, clo, chi, rgb in c["prep"]:
                if lut is not None:
                    g = lut[fat(am.mapas[i])]
                else:
                    f = fat(am.mapas[i]) * fat(am.inv_soma)
                    g = np.clip((f - clo) * (255.0 / max(chi - clo, 1e-6)), 0, 255).astype(np.uint16)
                b += (g[..., None].astype(np.uint32) * rgb) >> 8
            b = np.minimum(b, 255).astype(np.uint16)
        else:
            g = c["lut_bse"][fat(c["src"])]
            b = np.repeat(g[..., None], 3, axis=2)
        if v.escurecer_fora:
            fora = ~fat(am.mascara)
            b[fora] = (b[fora] * 80) >> 8
        if c["clus"] is not None:
            cid = fat(am.clusters)
            a = c["clus"][1][cid][..., None]
            b = (b * (256 - a) + c["clus"][0][cid] * a) >> 8
        if "mins" in c:
            ii = fat(c["fonte_min"])
            cor, alfa = c["mins"]
            a = alfa[ii]
            if v.estilo == "contorno":
                a = a * self.borda(y0, y1, x0, x1)[::p, ::p]
            a = a[..., None]
            b = (b * (256 - a) + cor[ii] * a) >> 8
        return b

    def compor(self, v, passo=1, cancelar=None):
        """-> (rgb uint8, info). passo>1 = prévia subamostrada (1 a cada `passo` px);
        cancelar() é consultado entre blocos (retorna (None, {}) se cancelado)."""
        H, W = self.am.shape
        p = max(1, int(passo))
        out = np.empty(((H + p - 1) // p, (W + p - 1) // p, 3), np.uint8)
        c = self._preparar(v)
        for y0 in range(0, H, BLOCO * p):
            if cancelar is not None and cancelar():
                return None, {}
            y1 = min(H, y0 + BLOCO * p)
            o0 = y0 // p
            out[o0:o0 + len(range(y0, y1, p))] = self._bloco(v, c, y0, y1, 0, W, p)
        c["info"]["passo"] = p
        return out, c["info"]

    def compor_regiao(self, v, x0, y0, x1, y1, ctx=None):
        """Recomposição local (resolução cheia) após uma edição -> (rgb uint8, (x0, y0)).
        ctx = resultado de _preparar(v) reaproveitado entre segmentos do mesmo traço."""
        H, W = self.am.shape
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        c = ctx if ctx is not None else self._preparar(v)
        return np.ascontiguousarray(self._bloco(v, c, y0, y1, x0, x1, 1).astype(np.uint8)), (x0, y0)
