"""Edição dos rótulos (sem Qt): operações determinísticas + histórico desfazer/refazer.

Toda edição vira um PASSO do histórico = lista de trechos (janela, pixels alterados, valores
antes/depois). Só os pixels que mudaram são guardados -> desfazer ilimitado cabe em 4096².

Proteções (valem para pincel, formas, pontos, propagar, morfologia):
  nao_invadir   pintar só sobre pixel livre (0) ou do próprio mineral
  so_amostra    só dentro da máscara da amostra (fora = resina)
Balde, remover grão e reatribuir agem sobre um objeto/mineral escolhido explicitamente.

A matemática reaproveita o pipeline: propagar = algoritmo do propagar.py; morfologia =
segmentar.aplicar_forma; filtro químico = common.avaliar_expr sobre a fração de cátions.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy import ndimage as ndi

from .amostra import Vista
from .pipeline import common


def _agora():
    return datetime.now().isoformat(timespec="seconds")


# ======================= geometria (rasterização) =======================
def capsula(p0, p1, raio, shape):
    """Traço do pincel de p0 a p1 (coords da imagem, float) com raio r -> (máscara, y0, x0)."""
    H, W = shape
    r = max(0.5, float(raio))
    x0 = int(np.floor(min(p0[0], p1[0]) - r)); x1 = int(np.ceil(max(p0[0], p1[0]) + r)) + 1
    y0 = int(np.floor(min(p0[1], p1[1]) - r)); y1 = int(np.ceil(max(p0[1], p1[1]) + r)) + 1
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return None, 0, 0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    px, py = xx + 0.5, yy + 0.5
    ax, ay = p0
    bx, by = p1[0] - ax, p1[1] - ay
    L2 = bx * bx + by * by
    t = np.clip(((px - ax) * bx + (py - ay) * by) / L2, 0, 1) if L2 > 0 else 0.0
    dx, dy = px - (ax + t * bx), py - (ay + t * by)
    return dx * dx + dy * dy <= r * r, y0, x0


def poligono(pts, shape):
    from skimage.draw import polygon
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return None, 0, 0
    H, W = shape
    x0, y0 = max(0, int(np.floor(pts[:, 0].min()))), max(0, int(np.floor(pts[:, 1].min())))
    x1, y1 = min(W, int(np.ceil(pts[:, 0].max())) + 1), min(H, int(np.ceil(pts[:, 1].max())) + 1)
    if x1 <= x0 or y1 <= y0:
        return None, 0, 0
    m = np.zeros((y1 - y0, x1 - x0), bool)
    rr, cc = polygon(pts[:, 1] - y0, pts[:, 0] - x0, shape=m.shape)
    m[rr, cc] = True
    return m, y0, x0


def retangulo(p0, p1, shape):
    xs, ys = sorted((p0[0], p1[0])), sorted((p0[1], p1[1]))
    return poligono([(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1])], shape)


def rasterizar(tipo, pts, shape):
    """Forma do canvas (retangulo|elipse|poligono|laco) -> (máscara da janela, y0, x0) ou (None, 0, 0)."""
    if tipo == "retangulo":
        return retangulo(pts[0], pts[-1], shape)
    if tipo == "elipse":
        return elipse(pts[0], pts[-1], shape)
    return poligono(pts, shape)


def elipse(p0, p1, shape):
    from skimage.draw import ellipse
    H, W = shape
    cx, cy = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    rx, ry = abs(p1[0] - p0[0]) / 2, abs(p1[1] - p0[1]) / 2
    if rx < 0.5 or ry < 0.5:
        return None, 0, 0
    x0, y0 = max(0, int(np.floor(cx - rx))), max(0, int(np.floor(cy - ry)))
    x1, y1 = min(W, int(np.ceil(cx + rx)) + 1), min(H, int(np.ceil(cy + ry)) + 1)
    if x1 <= x0 or y1 <= y0:
        return None, 0, 0
    m = np.zeros((y1 - y0, x1 - x0), bool)
    rr, cc = ellipse(cy - y0 - 0.5, cx - x0 - 0.5, ry, rx, shape=m.shape)
    m[rr, cc] = True
    return m, y0, x0


def agrupar_pontos(pts, eps):
    """Agrupamento por proximidade (ligação simples com distância eps = DBSCAN min_samples=1,
    como no editor napari)."""
    pts = np.asarray(pts, float)
    if len(pts) == 1:
        return np.array([1])
    from scipy.cluster.hierarchy import fcluster, linkage
    return fcluster(linkage(pts, "single"), t=eps, criterion="distance")


def poligono_de_pontos(grupo, modo):
    g = np.asarray(grupo, float)
    if modo == "convexo" and len(g) >= 3:
        from scipy.spatial import ConvexHull
        try:
            return g[ConvexHull(g).vertices]
        except Exception:
            pass
    c = g.mean(0)                                   # angular: ordena pelo ângulo em torno do centro
    return g[np.argsort(np.arctan2(g[:, 1] - c[1], g[:, 0] - c[0]))]


# ======================= filtro químico =======================
_COND = re.compile(r"^\s*([A-Za-z0-9+\-/ ]+?)\s*([<>])\s*([0-9]*[.,]?[0-9]+)\s*$")


def interpretar_filtro(texto, elementos):
    """'Fe>0.12, S>0.12' -> [(canal, '>0.12'), ...] (fração de cátions). Vazio -> []."""
    conds = []
    for parte in re.split(r"[,;&]|\se\s", texto or ""):
        if not parte.strip():
            continue
        m = _COND.match(parte)
        if not m:
            raise ValueError(f"Condição inválida: '{parte.strip()}'. Use, ex.: Fe>0.12, S>0.12")
        canal, op, v = m.group(1).replace(" ", ""), m.group(2), m.group(3).replace(",", ".")
        for t in re.split(r"[+\-/]", canal):
            if t not in elementos:
                raise ValueError(f"Sem mapa para '{t}' nesta amostra.")
        conds.append((canal, op + v))
    return conds


def mascara_filtro(am, conds, ys, xs):
    if not conds:
        return None
    fr = Vista(lambda i: am.mapas[i][ys, xs] * am.inv_soma[ys, xs])      # fração só na janela
    m = None
    for canal, expr in conds:
        c = common.avaliar_expr(common.canal(fr, am.elementos, canal), expr)
        m = c if m is None else (m & c)
    return m


# ======================= histórico =======================
@dataclass
class Trecho:
    y0: int
    x0: int
    ys: np.ndarray
    xs: np.ndarray
    antes: np.ndarray
    depois: np.ndarray

    @property
    def nbytes(self):
        return self.ys.nbytes + self.xs.nbytes + self.antes.nbytes + self.depois.nbytes

    def caixa(self):
        return (self.x0 + int(self.xs.min()), self.y0 + int(self.ys.min()),
                self.x0 + int(self.xs.max()) + 1, self.y0 + int(self.ys.max()) + 1)


@dataclass
class Passo:
    desc: str
    trechos: list = field(default_factory=list)
    px: int = 0
    quando: str = field(default_factory=_agora)

    def caixa(self):
        cs = [t.caixa() for t in self.trechos]
        return (min(c[0] for c in cs), min(c[1] for c in cs), max(c[2] for c in cs), max(c[3] for c in cs))

    @property
    def nbytes(self):
        return sum(t.nbytes for t in self.trechos)


class Historico:
    def __init__(self, limite_bytes=768 * 2 ** 20, limite_passos=300):
        self.passos, self.pos = [], 0
        self.limite_bytes, self.limite_passos = limite_bytes, limite_passos

    def registrar(self, passo):
        del self.passos[self.pos:]
        self.passos.append(passo)
        while len(self.passos) > self.limite_passos or \
                (len(self.passos) > 1 and sum(p.nbytes for p in self.passos) > self.limite_bytes):
            self.passos.pop(0)
        self.pos = len(self.passos)

    @property
    def pode_desfazer(self):
        return self.pos > 0

    @property
    def pode_refazer(self):
        return self.pos < len(self.passos)


# ======================= editor =======================
class Editor:
    def __init__(self, am):
        self.am = am
        self.hist = Historico()
        self.versao = 0
        self.nao_invadir = True
        self.so_amostra = True
        self._grupo = None

    # ---------- primitiva ----------
    def aplicar(self, m, y0, x0, valor, alvo=None, forcar=False, filtro=None, fora_ok=False):
        """Pinta `valor` onde m (janela em y0,x0) vale, respeitando as proteções.
        alvo: só pixels com esse id (-1 = qualquer mineral). forcar: ignora nao_invadir.
        Retorna nº de pixels alterados."""
        if m is None:
            return 0
        rot = self.am.rotulos
        h, w = m.shape
        reg = rot[y0:y0 + h, x0:x0 + w]
        m = m.copy()
        if self.so_amostra and not fora_ok:
            m &= self.am.mascara[y0:y0 + h, x0:x0 + w]
        if filtro is not None:
            m &= filtro
        if valor != 0 and self.nao_invadir and not forcar:
            m &= (reg == 0) | (reg == valor)
        if alvo == -1:
            m &= reg > 0
        elif alvo is not None:
            m &= reg == alvo
        m &= reg != valor
        ys, xs = np.nonzero(m)
        if ys.size == 0:
            return 0
        antes = reg[ys, xs].copy()
        reg[ys, xs] = valor
        t = Trecho(y0, x0, ys.astype(np.int32), xs.astype(np.int32), antes,
                   np.full(ys.size, valor, rot.dtype))
        if self._grupo is not None:
            self._grupo.trechos.append(t)
            self._grupo.px += ys.size
        else:
            self.hist.registrar(Passo("edição", [t], ys.size))
        self.versao += 1
        return int(ys.size)

    def iniciar(self, desc):
        self._grupo = Passo(desc)

    def terminar(self):
        g, self._grupo = self._grupo, None
        if g is not None and g.px > 0:
            self.hist.registrar(g)
            self.am.log_edicoes.append({"quando": g.quando, "o_que": g.desc, "px": g.px})
            return g
        return None

    def _repor(self, trechos, depois):
        rot = self.am.rotulos
        for t in (trechos if depois else reversed(trechos)):
            rot[t.y0 + t.ys, t.x0 + t.xs] = t.depois if depois else t.antes

    def _passo(self, desc, fn):
        """Executa fn() como UM passo do histórico -> (passo|None). Se fn falhar, desfaz o
        que já tinha sido aplicado e repassa o erro."""
        self.iniciar(desc)
        try:
            fn()
        except Exception:
            g, self._grupo = self._grupo, None
            self._repor(g.trechos if g else [], depois=False)
            raise
        return self.terminar()

    # ---------- desfazer / refazer ----------
    def _mover(self, delta):
        h = self.hist
        if not (h.pode_desfazer if delta < 0 else h.pode_refazer):
            return None
        p = h.passos[h.pos - 1 if delta < 0 else h.pos]
        h.pos += delta
        self._repor(p.trechos, depois=delta > 0)
        self.versao += 1
        self.am.log_edicoes.append({"quando": _agora(), "o_que": f"{'refeito' if delta > 0 else 'desfeito'}: "
                                    f"{p.desc}", "px": p.px})
        return p

    def desfazer(self):
        return self._mover(-1)

    def refazer(self):
        return self._mover(+1)

    # ---------- ferramentas ----------
    def nome(self, mid):
        m = self.am.mineral(mid)
        return m.nome.replace("_", " ") if m else ("apagar" if mid == 0 else f"id {mid}")

    def _regiao_conexa(self, x, y):
        from skimage.segmentation import flood
        rot = self.am.rotulos
        v = int(rot[y, x])
        m = flood(rot, (y, x), connectivity=1)
        ys, xs = np.nonzero(m)
        y0, x0 = int(ys.min()), int(xs.min())
        return v, m[y0:int(ys.max()) + 1, x0:int(xs.max()) + 1], y0, x0

    def balde(self, x, y, valor):
        v, m, y0, x0 = self._regiao_conexa(x, y)
        if v == valor:
            return None
        de = self.nome(v) if v else "área livre"
        return self._passo(f"balde: {de} → {self.nome(valor)}",
                           lambda: self.aplicar(m, y0, x0, valor, forcar=True))

    def remover_grao(self, x, y):
        v = int(self.am.rotulos[y, x])
        if v == 0:
            return None
        _, m, y0, x0 = self._regiao_conexa(x, y)
        return self._passo(f"remover grão de {self.nome(v)} ({int(m.sum())} px)",
                           lambda: self.aplicar(m, y0, x0, 0, alvo=v, fora_ok=True))

    def forma(self, tipo, pts, acao, ativo, origem=None, filtro_txt="", incluir_livres=False):
        """tipo: retangulo|elipse|poligono|laco; acao: pintar|apagar|reatribuir."""
        m, y0, x0 = rasterizar(tipo, pts, self.am.shape)
        if m is None:
            return None
        conds = interpretar_filtro(filtro_txt, self.am.elementos)
        filtro = mascara_filtro(self.am, conds, slice(y0, y0 + m.shape[0]), slice(x0, x0 + m.shape[1]))
        nf = {"retangulo": "retângulo", "elipse": "elipse", "poligono": "polígono", "laco": "laço"}[tipo]
        suf = f" [{filtro_txt.strip()}]" if conds else ""
        if acao == "pintar":
            return self._passo(f"{nf}: pintar {self.nome(ativo)}{suf}",
                               lambda: self.aplicar(m, y0, x0, ativo, filtro=filtro))
        if acao == "apagar":
            alvo = ativo if origem is None else origem
            return self._passo(f"{nf}: apagar {self.nome(alvo) if alvo != -1 else 'todos'}{suf}",
                               lambda: self.aplicar(m, y0, x0, 0, alvo=alvo, filtro=filtro, fora_ok=True))

        def reat():
            self.aplicar(m, y0, x0, ativo, alvo=-1 if origem is None else origem, forcar=True, filtro=filtro)
            if incluir_livres:
                self.aplicar(m, y0, x0, ativo, alvo=0, filtro=filtro)
        de = "qualquer mineral" if origem is None else self.nome(origem)
        return self._passo(f"{nf}: reatribuir {de} → {self.nome(ativo)}{suf}", reat)

    def pontos(self, pts, ativo, eps, modo="angular", raio=6):
        """Pontos -> regiões (tecla G do editor napari). Retorna (passo, nº regiões, nº ignorados)."""
        pts = np.asarray(pts, float)
        if len(pts) == 0:
            return None, 0, 0
        shape = self.am.shape
        mascaras, ign = [], 0
        if modo == "semente":
            for p in pts:
                mascaras.append(capsula(p, p, raio, shape))
        else:
            rot = agrupar_pontos(pts, eps)
            for g in np.unique(rot):
                grupo = pts[rot == g]
                if len(grupo) < 3:
                    ign += len(grupo)
                    continue
                mascaras.append(poligono(poligono_de_pontos(grupo, modo), shape))

        def pintar():
            for m, y0, x0 in mascaras:
                self.aplicar(m, y0, x0, ativo)
        p = self._passo(f"pontos → {len(mascaras)} região(ões) de {self.nome(ativo)} ({modo})", pintar)
        return p, len(mascaras), ign

    def limpar_fora(self):
        rot = self.am.rotulos
        m = (rot > 0) & ~self.am.mascara
        return self._passo(f"remover rótulos fora da amostra ({int(m.sum())} px)",
                           lambda: self.aplicar(m, 0, 0, 0, alvo=-1, fora_ok=True))

    def fora_da_amostra(self):
        """{id: px} rotulados fora da máscara (prévia da limpeza)."""
        rot = self.am.rotulos
        f = (rot > 0) & ~self.am.mascara
        ids, n = np.unique(rot[f], return_counts=True)
        return f, {int(i): int(c) for i, c in zip(ids, n)}

    # ---------- morfologia (semântica de segmentar.aplicar_forma, vetorizada) ----------
    def morfologia(self, ativo, op, param=0):
        """fechar/abrir (raio), preencher buracos, fecho convexo por grão, manter o maior,
        limpar < área. Componentes em conectividade 8 (como measure.label do aplicar_forma);
        convexo/limpar vetorizados (o laço por objeto do pipeline não escala p/ 100 mil objetos)."""
        from skimage import measure, morphology as morph
        am = self.am
        atual = am.rotulos == ativo
        if not atual.any():
            raise ValueError(f"Não há pixels de {self.nome(ativo)} para aplicar a operação.")
        r = max(1, int(param or 1))
        if op == "fechar":
            novo = morph.binary_closing(atual, morph.disk(r))
        elif op == "abrir":
            novo = morph.binary_opening(atual, morph.disk(r))
        elif op == "preencher":
            novo = ndi.binary_fill_holes(atual)
        elif op == "limpar":
            novo = morph.remove_small_objects(atual, min_size=r, connectivity=2)
        elif op == "maior":
            lab = measure.label(atual, connectivity=2)
            area = np.bincount(lab.ravel())
            area[0] = 0
            novo = lab == int(np.argmax(area))
        elif op == "convexo":
            # fecho só dos grãos >= area_min (como _fecho_convexo_por_comp do pipeline); os menores
            # ficam como estão — calcular o fecho de ~10^5 specks de 1–2 px levaria minutos
            lab = measure.label(atual, connectivity=2)
            area = np.bincount(lab.ravel())
            amin = max(1, am.area_min)
            novo = atual.copy()
            for k, sl in enumerate(ndi.find_objects(lab), start=1):
                if sl is not None and area[k] >= amin:
                    novo[sl] |= morph.convex_hull_image(lab[sl] == k)
        else:
            raise ValueError(f"operação desconhecida: {op}")
        # crescimento só dentro da amostra; pixels já existentes fora dela não são tocados
        novo &= (am.mascara | atual) if self.so_amostra else True
        rotulo = {"fechar": f"fechar r={param}", "abrir": f"abrir r={param}", "preencher": "preencher buracos",
                  "convexo": f"fecho convexo por grão (≥ {am.area_min} px)", "maior": "manter o maior grão",
                  "limpar": f"limpar < {param} px"}[op]

        def fazer():
            self.aplicar(atual & ~novo, 0, 0, 0, alvo=ativo, fora_ok=True)
            self.aplicar(novo & ~atual, 0, 0, ativo)
        return self._passo(f"{rotulo}: {self.nome(ativo)}", fazer)

    # ---------- propagar por exemplo (algoritmo do propagar.py) ----------
    def propagar(self, ativo, thr=1.2, gate_q=0.10, erode=2, limpar=True, area_frac=0.25,
                 tam_fator=0.3, progresso=None):
        """Aprende a assinatura (fração) do NÚCLEO do mineral ativo e propõe regiões novas com a
        mesma química e tamanho compatível. Não altera nada: devolve (rótulos das propostas
        int32 — 0 = nenhuma, k = região k —, nº de regiões, info) para revisão do usuário."""
        from skimage import morphology as morph
        prog = progresso or (lambda f, m: None)
        am = self.am
        fg = am.mascara
        area_min = am.area_min
        seed = am.rotulos == ativo
        if seed.sum() < 30:
            raise ValueError(f"Pinte algumas regiões de {self.nome(ativo)} primeiro (mín. 30 px) "
                             "para eu aprender a assinatura química.")
        prog(0.05, "limpando a semente")
        if limpar:
            seed = morph.binary_opening(seed & fg, morph.disk(1))
            seed = morph.remove_small_objects(seed, area_min)
            seed = morph.remove_small_holes(seed, area_min)
            if seed.sum() < 30:
                raise ValueError("Depois de limpar o speckle sobrou pouca semente — desligue "
                                 "'limpar semente' ou pinte grãos maiores.")
        nucleo = seed & fg
        if erode > 0:
            er = morph.binary_erosion(seed, morph.disk(int(erode))) & fg
            if er.sum() > 50:
                nucleo = er
        N = len(am.elementos)
        px = np.stack([am.frac(i)[nucleo] for i in range(N)], 1).astype(np.float64)
        mu = px.mean(0)
        inv = np.linalg.inv(np.cov(px.T) + np.eye(N) * 1e-6)
        d = px - mu
        seed_d = np.sqrt(np.einsum("ij,jk,ik->i", d, inv, d))
        lim = float(np.quantile(seed_d, 0.98)) * thr
        lab_s, ns = ndi.label(seed)
        tam_s = np.bincount(lab_s.ravel())[1:] if ns else np.array([area_min])
        amin = max(area_min, int(np.median(tam_s) * area_frac))
        amax = int(tam_s.max() / tam_fator)
        mapas = [e for e in (am.regra(ativo).get("mapas_seg") or ["Si"]) if e in am.elementos] or [am.elementos[0]]
        gate = {}
        for e in mapas:
            med = ndi.median(am.mapas[am.indice(e)], lab_s, index=np.arange(1, ns + 1)) if ns else [0]
            gate[e] = float(np.quantile(med, gate_q)) if gate_q > 0 else -np.inf
        livre = fg & ((am.rotulos == 0) | (am.rotulos == ativo))
        H, W = am.shape
        cand = np.zeros((H, W), bool)
        for y0 in range(0, H, 256):
            prog(0.15 + 0.6 * y0 / H, "distância de Mahalanobis")
            y1 = min(H, y0 + 256)
            bl = np.stack([am.mapas[i][y0:y1] * am.inv_soma[y0:y1] for i in range(N)], -1) - mu
            dist = np.sqrt(np.einsum("...i,ij,...j->...", bl, inv, bl))
            cand[y0:y1] = (dist <= lim) & livre[y0:y1]
        prog(0.8, "regiões candidatas")
        cand = morph.remove_small_holes(morph.remove_small_objects(cand, amin), amin)
        lab_c, nc = ndi.label(cand)
        if nc == 0:
            return np.zeros((H, W), np.int32), 0, dict(lim=lim, amin=amin, amax=amax, mapas=mapas)
        idx = np.arange(1, nc + 1)
        area = np.bincount(lab_c.ravel(), minlength=nc + 1)[1:]
        na_semente = np.bincount(lab_c.ravel(), weights=seed.ravel(), minlength=nc + 1)[1:]
        ok = (area >= amin) & (area <= amax) & (na_semente / np.maximum(area, 1) <= 0.5)
        for e in mapas:
            med = np.asarray(ndi.median(am.mapas[am.indice(e)], lab_c, index=idx))
            ok &= med >= gate[e]
        novas = np.isin(lab_c, idx[ok]) & ~seed
        prog(1.0, "pronto")
        return np.where(novas, lab_c, 0).astype(np.int32), int(ok.sum()), \
            dict(lim=lim, amin=amin, amax=amax, mapas=mapas)

    def aceitar_propagacao(self, novas, ativo, n):
        """novas = máscara bool (regiões mantidas após a revisão)."""
        return self._passo(f"propagar {self.nome(ativo)} (+{n} regiões)",
                           lambda: self.aplicar(novas, 0, 0, ativo))
