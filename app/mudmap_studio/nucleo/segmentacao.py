"""Segmentação por regra da config dentro do app (sem Qt) — MESMA matemática do pipeline.

candidato() recria o segmentar.py chamando as próprias funções dele (candidato_grupos,
candidato_mapa, aplicar_forma, limpar) e common.mascara_mineral, sobre as pilhas virtuais
float64 da amostra (am.vista(..., exata=True): stack/frac do pipeline canal a canal).
comparar()/calibrar() têm a definição do comparar.py (métricas por pixel e por grão, proposta
de regra por separação), vetorizadas (o laço por grão do script não escala p/ 10^5 objetos).
kmeans() = reconhecer.py (KMeans n_init=10, random_state=0 + filtro de maioria).

params = dict no formato do bloco do mineral na config:
  fonte ('regra'|'mapa'|'cluster'), condicoes, disseminado, mapas_seg, mapas_modo,
  mapas_limiar, mapas_q, mapas_grupos, suavizar, forma, clusters (ids — só no app)
"""
import copy

import numpy as np
from scipy import ndimage as ndi

from .amostra import elementos_da_expr
from .pipeline import common, segmentar

CHAVES_REGRA = ["fonte_default", "disseminado", "suavizar", "suavizar_um", "mapas_seg", "mapas_modo",
                "mapas_limiar", "mapas_q", "mapas_grupos", "forma", "condicoes"]


# ---------------------------------------------------------------- parâmetros
def fonte_padrao(regra):
    return regra.get("fonte_default") or (
        "mapa" if (regra.get("mapas_seg") or regra.get("mapas_grupos")) else "cluster")


def clusters_do_mineral(am, nome):
    info = am.clusters_info or {}
    return [int(k) for k, n in info.get("nomes", {}).items() if n == nome]


def params_da_regra(am, mid):
    """Parâmetros editáveis a partir da config (cópia profunda) + fonte resolvida."""
    regra = copy.deepcopy(am.regra(mid))
    p = {k: regra[k] for k in CHAVES_REGRA if k in regra}
    p["fonte"] = fonte_padrao(regra)
    p.setdefault("condicoes", {})
    m = am.mineral(mid)
    p["clusters"] = clusters_do_mineral(am, m.nome) if m else []
    return p


def resumo(params):
    f = params.get("fonte")
    if f == "regra":
        s = "regra por fração: " + (", ".join(f"{k}{v}" for k, v in params.get("condicoes", {}).items()) or "—")
    elif f == "mapa" and params.get("mapas_grupos"):
        s = f"mapa por região ({len(params['mapas_grupos'])} grupo(s))"
    elif f == "mapa":
        s = f"mapa por pixel {params.get('mapas_seg')} ({params.get('mapas_modo', 'interseccao')}, " \
            f"{params.get('mapas_limiar', 'otsu')})"
    else:
        s = f"clusters {params.get('clusters')}"
    if params.get("forma"):
        s += " · forma " + ", ".join(f"{k}={v}" for k, v in params["forma"].items())
    if params.get("disseminado"):
        s += " · disseminado"
    return s


# ---------------------------------------------------------------- candidato
def candidato(am, mid, params, substituir=False, grupo=None):
    """-> (máscara bool, info). Espelha segmentar.py:main (fonte, livre, limpeza, forma).
    substituir=False: só pixels livres (commit aditivo do script); True: livres + do próprio
    mineral (re-segmentar), como o 'livre' do comparar.py."""
    rot = am.rotulos
    fg = am.mascara
    livre = fg & ((rot == 0) | (rot == mid)) if substituir else fg & (rot == 0)
    els = am.elementos
    fonte = params.get("fonte", "regra")
    faltam = []
    if fonte == "mapa":
        if params.get("mapas_grupos"):
            grupos = params["mapas_grupos"]
            if grupo:
                grupos = [g for g in grupos if g.get("nome") == grupo]
            for g in grupos:
                for c in g.get("cond", []):
                    faltam += [t for t in elementos_da_expr(c.get("canal", "")) if t not in els]
            _checar(faltam, els)
            cand = segmentar.candidato_grupos(am.vista("raw", True), els, am.vista("frac", True), fg, grupos,
                                              params.get("suavizar", 15), params.get("forma")) & livre
        else:
            mapas = params.get("mapas_seg") or []
            if not mapas:
                raise ValueError("Escolha pelo menos um mapa (mapas_seg) ou use grupos por região.")
            _checar([e for e in mapas if e not in els], els)
            cand = segmentar.candidato_mapa(am.vista("raw", True), els, mapas, fg,
                                            metodo=params.get("mapas_limiar", "otsu"),
                                            q=params.get("mapas_q", 0.65),
                                            modo=params.get("mapas_modo", "interseccao")) & livre
    elif fonte == "cluster":
        if am.clusters is None:
            raise ValueError("Esta amostra não tem clusters — recalcule o k-means.")
        ids = params.get("clusters") or []
        if not ids:
            raise ValueError("Nenhum cluster escolhido para este mineral.")
        cand = np.isin(am.clusters, ids) & livre
    else:
        cond = params.get("condicoes") or {}
        if not cond:
            raise ValueError("A regra não tem condições.")
        for k in cond:
            faltam += [t for t in elementos_da_expr(k) if t not in els]
        _checar(faltam, els)
        cand = common.mascara_mineral(am.vista("frac", True), els, cond) & livre
    if not params.get("disseminado") and not params.get("forma"):
        cand = segmentar.limpar(cand, am.area_min) & livre
    if params.get("forma") and not params.get("mapas_grupos"):
        cand = segmentar.aplicar_forma(cand, fg, params["forma"]) & livre
    n = int(cand.sum())
    _, ng = ndi.label(cand)
    return cand, {"px": n, "graos": int(ng), "livres": int(livre.sum()), "fonte": fonte}


def _checar(faltam, els):
    if faltam:
        raise ValueError(f"Sem mapa para {', '.join(sorted(set(faltam)))} nesta amostra "
                         f"(disponíveis: {', '.join(els)}).")


# ---------------------------------------------------------------- comparação / calibração
def comparar(oper, auto):
    """Métricas do comparar.py (IoU, Dice, precisão, recall; grãos do operador cobertos ≥50%,
    grãos automáticos sem sobreposição) — por pixel e por grão, vetorizadas."""
    inter = int((oper & auto).sum())
    uni = int((oper | auto).sum())
    o, a = int(oper.sum()), int(auto.sum())
    lo, no = ndi.label(oper)
    la, na = ndi.label(auto)
    if no:
        cob = np.bincount(lo.ravel(), weights=auto.ravel(), minlength=no + 1)[1:] / \
            np.maximum(np.bincount(lo.ravel(), minlength=no + 1)[1:], 1)
        cobertos = int((cob >= 0.5).sum())
    else:
        cobertos = 0
    falsos = int((np.bincount(la.ravel(), weights=oper.ravel(), minlength=na + 1)[1:] == 0).sum()) if na else 0
    return {"iou": inter / uni if uni else 0.0, "dice": 2 * inter / (o + a) if (o + a) else 0.0,
            "precisao": inter / a if a else 0.0, "recall": inter / o if o else 0.0,
            "px_oper": o, "px_auto": a, "px_acerto": inter,
            "graos_oper": int(no), "graos_oper_cobertos": cobertos,
            "graos_auto": int(na), "graos_auto_falsos": falsos}


def calibrar(am, oper, sep_min=0.15, pos=0.05, neg=0.95):
    """comparar.calibrar_regra: para cada elemento, '>' se o mineral é mais rico que o resto da
    amostra (sep ≥ sep_min) ou '<' se mais pobre; corte = quantil dos grãos do operador.
    -> (regra proposta, linhas de diagnóstico, métricas da regra proposta e da atual)."""
    fg = am.mascara
    fora = fg & ~oper
    fr = am.vista("frac", True)
    regra, diag = {}, []
    for i, e in enumerate(am.elementos):
        f = fr[..., i]
        vin, vout = f[oper], f[fora]
        mi, mo = float(np.median(vin)), float(np.median(vout))
        sep = (mi - mo) / (mi + mo + 1e-9)
        linha = f"{e}: operador {mi:.3f} · resto {mo:.3f} · sep {sep:+.2f}"
        if sep >= sep_min:
            regra[e] = f">{np.quantile(vin, pos):.2f}"
            linha += f"  →  {regra[e]}"
        elif sep <= -sep_min:
            regra[e] = f"<{np.quantile(vin, neg):.2f}"
            linha += f"  →  {regra[e]}"
        diag.append(linha)
    prop = segmentar.limpar(common.mascara_mineral(fr, am.elementos, regra) & fg, am.area_min) if regra \
        else np.zeros_like(oper)
    return regra, diag, comparar(oper, prop)


def metricas_regra(am, oper, condicoes):
    """Como o comparar.py avalia a 'regra ATUAL': limpar(regra & amostra) vs operador."""
    if not condicoes:
        return None
    m = segmentar.limpar(common.mascara_mineral(am.vista("frac", True), am.elementos, condicoes) & am.mascara, am.area_min)
    return comparar(oper, m)


# ---------------------------------------------------------------- k-means (reconhecer.py)
def kmeans(am, k=9, raio=4, progresso=None):
    prog = progresso or (lambda f, m: None)
    from sklearn.cluster import KMeans
    fg = am.mascara
    fr = am.vista("frac", True)
    prog(0.05, "montando os pixels da amostra")
    px = np.stack([fr[..., i][fg] for i in range(len(am.elementos))], 1)
    prog(0.15, f"k-means (k={k}, n_init=10) em {len(px):,} pixels".replace(",", "."))
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(px)
    prog(0.8, "nomeando pelos minerais da config")
    nomes = []
    for c in km.cluster_centers_:
        fr1 = c.reshape(1, 1, -1)
        nome = "sem_classe"
        for m in am.config.get("minerais", []):
            if m.get("condicoes") and common.mascara_mineral(fr1, am.elementos, m["condicoes"])[0, 0]:
                nome = m["nome"]
                break
        nomes.append(nome)
    lab = np.zeros(fg.shape, np.uint16)
    lab[fg] = km.labels_ + 1
    if raio > 0:
        prog(0.9, "regularização espacial (maioria)")
        from skimage.filters.rank import modal
        from skimage.morphology import disk
        lab = modal(lab, disk(raio), mask=fg)
        lab[~fg] = 0
    info = {"nomes": {str(i + 1): nomes[i] for i in range(k)},
            "centros": {str(i + 1): km.cluster_centers_[i].round(4).tolist() for i in range(k)},
            "elementos": list(am.elementos), "k": k, "raio": raio}
    prog(1.0, "pronto")
    return lab, info
