"""Segmentação por partes: um mineral por vez, com estado em disco e revisão no napari."""
import argparse
import json
import warnings
from datetime import date
from pathlib import Path
import numpy as np

warnings.filterwarnings("ignore")
from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra, mascara_mineral, id_e_regra, canal)

EST = Path("estado")
ROT = EST / "rotulos.npy"
PROG = EST / "progresso.json"
CLU = EST / "clusters.npy"
CLUJ = EST / "clusters.json"


def pontos_para_regioes(pts, shape, raio_grupo):
    """Pontos (N,2)=(row,col) -> máscara. Agrupa pontos próximos e preenche o
    fecho convexo de cada grupo, virando regiões contínuas."""
    h, w = shape
    final = np.zeros((h, w), bool)
    if len(pts) < 3:
        print(f"[AVISO] só {len(pts)} ponto(s); preciso de >=3 por grão.")
        return final
    from scipy.ndimage import binary_dilation, label
    from skimage.morphology import disk
    from skimage.draw import polygon as draw_polygon
    rr = np.clip(pts[:, 0].astype(int), 0, h - 1)
    cc = np.clip(pts[:, 1].astype(int), 0, w - 1)
    mp = np.zeros((h, w), bool); mp[rr, cc] = True
    grupos, ng = label(binary_dilation(mp, disk(raio_grupo)))
    gid = grupos[rr, cc]
    n_reg = 0
    for g in range(1, ng + 1):
        sel = gid == g
        if sel.sum() < 3:
            continue
        pr, pc = rr[sel], cc[sel]
        try:
            from scipy.spatial import ConvexHull
            hull = ConvexHull(np.column_stack([pc, pr]))
            vc = pc[hull.vertices]; vr = pr[hull.vertices]
        except Exception:
            vr, vc = pr, pc
        fr, fc = draw_polygon(vr, vc, shape=(h, w))
        final[fr, fc] = True
        n_reg += 1
    print(f"{len(pts)} pontos -> {n_reg} região(ões) -> {int(final.sum())} px.")
    return final


def candidato_cluster(mineral_nome):
    """União dos clusters (reconhecer.py) nomeados como este mineral."""
    lab = np.load(CLU)
    j = json.loads(CLUJ.read_text(encoding="utf-8"))
    ids = [int(cid) for cid, nm in j["nomes"].items() if nm == mineral_nome]
    m = np.isin(lab, ids)
    return m, ids


def _limiar(vals_fg, metodo, q):
    if metodo == "quantil":
        return float(np.quantile(vals_fg, q))
    from skimage.filters import threshold_otsu
    return float(threshold_otsu(vals_fg))


def candidato_mapa(stack, elementos, mapas, fg, metodo="otsu", q=0.65, modo="interseccao"):
    """Candidato guiado pelos MAPAS de elemento do mineral (config: mapas_seg).

    modo='interseccao' (default): limiar por mapa e exige brilho em TODOS (interseção).
    modo='soma': SOMA os mapas na mesma região e limiariza a soma (um limiar único).
    Limiar por Otsu (padrão) ou quantil (metodo='quantil', q em [0,1]), dentro da amostra.
    """
    if modo == "soma":
        soma = np.zeros(fg.shape, float)
        for e in mapas:
            soma += stack[..., elementos.index(e)]
        t = _limiar(soma[fg], metodo, q)
        m = fg & (soma > t)
        print(f"  mapas_seg(soma)={mapas} limiar={metodo}"
              f"{'('+str(q)+')' if metodo=='quantil' else ''} -> soma>{round(t,1)}")
        return m
    if modo == "convergencia":
        # convergência suave: normaliza cada mapa (p99 na amostra) e toma o MÍNIMO
        # por pixel = quão fortemente TODOS os elementos co-ocorrem. Limiariza o escore.
        conv = np.ones(fg.shape, float)
        for e in mapas:
            ch = stack[..., elementos.index(e)].astype(float)
            esc = float(np.quantile(ch[fg], 0.99)) or 1.0
            conv = np.minimum(conv, np.clip(ch / esc, 0, 1))
        t = _limiar(conv[fg], metodo, q)
        m = fg & (conv > t)
        print(f"  mapas_seg(convergencia)={mapas} limiar={metodo}"
              f"{'('+str(q)+')' if metodo=='quantil' else ''} -> min_norm>{round(t,3)}")
        return m
    m = fg.copy()
    detalhe = {}
    for e in mapas:
        ch = stack[..., elementos.index(e)]
        t = _limiar(ch[fg], metodo, q)
        m &= ch > t
        detalhe[e] = round(t, 1)
    print(f"  mapas_seg(interseccao)={mapas} limiar={metodo}"
          f"{'('+str(q)+')' if metodo=='quantil' else ''} -> {detalhe}")
    return m


def _suave_mascarado(x, fg, r):
    """Média local (raio r) considerando SÓ pixels da amostra (ignora cabeçalho/overlay/epóxi)."""
    from scipy import ndimage as ndi
    num = ndi.uniform_filter(np.where(fg, x.astype(float), 0.0), size=r)
    den = ndi.uniform_filter(fg.astype(float), size=r)
    return num / np.maximum(den, 1e-6)


def _fecho_convexo_por_comp(mask, fg, amin):
    """Fecho convexo de CADA componente conexo (>= amin) -> objetos sólidos e convexos.
    Casa com o traçado do operador feito por pontos->fecho convexo (ex.: quartzo)."""
    from skimage import measure
    from scipy.spatial import ConvexHull
    from skimage.draw import polygon as draw_polygon
    out = np.zeros_like(mask); lab = measure.label(mask)
    for p in measure.regionprops(lab):
        if p.area < amin:
            continue
        rr, cc = np.where(lab == p.label)
        try:
            h = ConvexHull(np.column_stack([cc, rr]))
            fr, fc = draw_polygon(rr[h.vertices], cc[h.vertices], shape=mask.shape)
            out[fr, fc] = True
        except Exception:
            out[rr, cc] = True
    return out & fg


def aplicar_forma(mask, fg, forma):
    """Pós-filtro morfológico de FORMA, reaproveitado por todas as fontes.
    Ordem determinística: close -> filtro (area_min/ecc_min) -> convex -> maior -> &fg.
    Opções: close (raio do fechamento), area_min, ecc_min (excentricidade, ~0.9=alongado),
    convex (fecho convexo por grão), maior (mantém só o MAIOR componente, ex.: 1 grão)."""
    if not forma:
        return mask
    from skimage import morphology as _morph, measure as _measure
    m = mask
    if forma.get("close"):
        m = _morph.binary_closing(m, _morph.disk(int(forma["close"])))
    amin = int(forma.get("area_min", 0)); ecc = float(forma.get("ecc_min", 0.0))
    if amin or ecc:
        lab = _measure.label(m); keep = np.zeros_like(m)
        for p in _measure.regionprops(lab):
            if p.area >= amin and p.eccentricity >= ecc:
                keep[lab == p.label] = True
        m = keep
    if forma.get("convex"):
        m = _fecho_convexo_por_comp(m, fg, max(amin, 1))
    if forma.get("maior"):
        lab = _measure.label(m)
        if lab.max() > 0:
            top = max(_measure.regionprops(lab), key=lambda p: p.area)
            m = lab == top.label
    if forma.get("preencher"):                       # grão SÓLIDO (preenche buracos internos)
        from scipy import ndimage as _ndi
        m = _ndi.binary_fill_holes(m)
    m = m & fg
    print(f"  forma: {forma} -> {int(m.sum())} px")
    return m


def candidato_grupos(stack, elementos, frac, fg, grupos, r_default=15, forma=None):
    """OU de sub-modelos; cada grupo = E de condições sobre mapas SUAVIZADOS (masked).
    Usado p/ minerais cujo sinal só emerge por REGIÃO: feldspato (Na/Al/Si×Al/K),
    biotita (lâminas Mg), quartzo (pureza Si) e clorita (matriz Mg/Si).

    Condição: {canal, tipo: raw|frac, op: '>'|'<', q|v}. `canal` = elemento ('Si') ou
    composto ('Si-Mg','A+B','A/B', via canal()). Limiar = quantil `q` na amostra OU
    valor absoluto `v`. `forma` (opcional) = pós-filtro; ver aplicar_forma()."""
    total = np.zeros(fg.shape, bool)
    for g in grupos:
        r = int(g.get("suavizar", r_default))
        m = fg.copy()
        for c in g["cond"]:
            arr = frac if c.get("tipo") == "frac" else stack
            base = canal(arr, elementos, c["canal"])     # 'Si', 'Si-Mg', 'A+B', 'A/B'
            s = _suave_mascarado(base, fg, r)
            # limiar ABSOLUTO (v) quando dado — estável entre sítios; senão quantil (q) na amostra
            t = float(c["v"]) if "v" in c else float(np.quantile(s[fg], c["q"]))
            m &= (s > t) if c["op"] == ">" else (s < t)
        print(f"  grupo {g.get('nome')} (r={r}): {int(m.sum())} px")
        total |= m
    return aplicar_forma(total, fg, forma)


def garantir_mapas(stack, elementos, pasta, mapas):
    """Carrega sob demanda os elementos de 'mapas' que não estão em 'elementos'
    (ex.: Na, usado só na segmentação do feldspato). Retorna (stack, elementos)
    aumentados — NÃO altera a fração de cátions (que usa só 'elementos' original)."""
    from common import _achar_arquivo, _decodificar
    faltantes = [e for e in (mapas or []) if e not in elementos]
    if not faltantes:
        return stack, elementos
    canais = [stack]
    els = list(elementos)
    for e in faltantes:
        inten, _ = _decodificar(str(_achar_arquivo(pasta, e)))
        if inten.shape != stack.shape[:2]:            # alinha se a barra recortou diferente
            r = min(inten.shape[0], stack.shape[0]); c = min(inten.shape[1], stack.shape[1])
            inten = inten[:r, :c]
        canais.append(inten[..., None])
        els.append(e)
    print(f"  [mapa extra carregado: {faltantes}]")
    return np.concatenate(canais, axis=-1), els


def render_previa(caminho, base, titulo, mask):
    """Salva PNG de conferência (mapa base em cinza + candidato realçado)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy import ndimage as ndi
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(b, cmap="gray")
    ov = np.zeros((*mask.shape, 4)); ov[mask] = [1, 0.2, 0.2, 0.85]
    ax.imshow(ov)
    _, n = ndi.label(mask)
    ax.set_title(f"{titulo} — {n} grãos, {int(mask.sum())} px", fontsize=12)
    ax.set_xticks([]); ax.set_yticks([])
    Path("saida").mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=130, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}  >> Agente: EXIBA este PNG aqui no chat.")


def limpar(mask, area_min):
    from skimage import morphology
    mask = morphology.remove_small_objects(mask, area_min)
    mask = morphology.remove_small_holes(mask, area_min)
    return mask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineral", required=True, help="nome do mineral a segmentar agora")
    ap.add_argument("--pasta", default=None)
    ap.add_argument("--fonte", choices=["cluster", "regra", "mapa"], default=None,
                    help="candidato via clusters (reconhecer.py), regras do config, ou "
                         "mapas de elemento do mineral (mapas_seg). Default: mapa se o "
                         "mineral tiver mapas_seg, senão cluster")
    ap.add_argument("--previa", action="store_true",
                    help="só renderiza a prévia PRÉ do candidato (headless) e sai")
    ap.add_argument("--limiar", choices=["otsu", "quantil"], default=None,
                    help="fonte=mapa: tipo de limiar (default: mapas_limiar do config, senão otsu)")
    ap.add_argument("--q-mapa", type=float, default=None,
                    help="fonte=mapa, limiar=quantil: quantil por mapa (default: mapas_q do config, senão 0.65)")
    ap.add_argument("--modo", choices=["pincel", "pontos"], default="pincel",
                    help="pincel: edita a máscara; pontos: você clica pontos ao redor "
                         "de cada grão e o interior (fecho convexo) vira região contínua")
    ap.add_argument("--raio-grupo", type=int, default=40,
                    help="modo pontos: pontos a até ~2x este raio (px) contam como o MESMO grão")
    ap.add_argument("--com-candidato", action="store_true",
                    help="modo pontos: une as regiões desenhadas ao candidato automático")
    ap.add_argument("--so-amostra", action="store_true",
                    help="recorta o resultado à máscara de amostra (exclui epóxi/overlay)")
    ap.add_argument("--grupo", default=None,
                    help="fonte=mapa com mapas_grupos: rodar só um sub-modelo (ex.: sodico|potassico)")
    ap.add_argument("--auto", action="store_true", help="commita sem revisar no napari")
    ap.add_argument("--substituir", action="store_true",
                    help="RE-segmenta: os pixels já commitados deste mineral voltam a ser livres e "
                         "o resultado os substitui (sem a flag o commit só soma pixels livres)")
    args = ap.parse_args()

    cfg = carregar_config()
    elementos = cfg["elementos"]
    area_min = cfg.get("area_min", 20)
    pasta = args.pasta or cfg["pasta_dados"]
    stack, overlay = carregar_mapas(pasta, elementos)
    frac, soma = fracao_cations(stack)
    fg = mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, elementos)

    ident, mineral = id_e_regra(cfg, args.mineral)
    # mapas extras (ex.: Na) só p/ segmentação por mapa; NÃO entram em frac/elementos
    stack_seg, els_seg = garantir_mapas(stack, elementos, pasta, mineral.get("mapas_seg"))

    EST.mkdir(exist_ok=True)
    rotulos = np.load(ROT) if ROT.exists() else np.zeros(frac.shape[:2], dtype=np.int64)
    progresso = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else []

    fonte = args.fonte or mineral.get("fonte_default") or (
        "mapa" if (mineral.get("mapas_seg") or mineral.get("mapas_grupos")) else "cluster")
    ident_livre = (rotulos == 0) | (rotulos == ident) if args.substituir else (rotulos == 0)
    livre = fg & ident_livre                           # só pixels ainda não atribuídos (+ o próprio)
    if fonte == "mapa":
        if mineral.get("mapas_grupos"):
            grupos = mineral["mapas_grupos"]
            if args.grupo:                               # rodar/inspecionar UM sub-modelo
                grupos = [g for g in grupos if g.get("nome") == args.grupo]
                if not grupos:
                    raise SystemExit(f"grupo '{args.grupo}' não existe em {args.mineral}.")
            candidato = candidato_grupos(stack, elementos, frac, fg, grupos,
                                         mineral.get("suavizar", 15),
                                         mineral.get("forma")) & livre
        else:
            mapas = mineral.get("mapas_seg")
            if not mapas:
                raise SystemExit(f"'{args.mineral}' não tem 'mapas_seg' nem 'mapas_grupos' no config.")
            metodo = args.limiar or mineral.get("mapas_limiar", "otsu")
            q = args.q_mapa if args.q_mapa is not None else mineral.get("mapas_q", 0.65)
            candidato = candidato_mapa(stack_seg, els_seg, mapas, fg,
                                       metodo=metodo, q=q,
                                       modo=mineral.get("mapas_modo", "interseccao")) & livre
    elif fonte == "cluster":
        if not CLU.exists():
            raise SystemExit("Rode primeiro: python scripts/reconhecer.py")
        bruto, ids = candidato_cluster(args.mineral)
        print(f"{args.mineral}: clusters {ids} -> {int(bruto.sum())} px brutos.")
        candidato = bruto & livre
    else:
        candidato = mascara_mineral(frac, elementos, mineral["condicoes"]) & livre
    # limpeza genérica (area_min) só quando NÃO há forma: o forma faz a própria limpeza
    # (fecha ANTES de filtrar por área — senão o grão fragmentado é apagado antes de reconectar).
    if not mineral.get("disseminado") and not mineral.get("forma"):
        # disseminado=cimento fino: NÃO limpar (some). & livre: remove_small_holes preenche
        # buracos com pixels FORA da amostra/de outros minerais (origem dos 13.807 px do 1.1)
        candidato = limpar(candidato, area_min) & livre
    # forma p/ fontes não-grupos (regra/mapa/cluster); grupos já aplicam forma internamente
    if mineral.get("forma") and not mineral.get("mapas_grupos"):
        candidato = aplicar_forma(candidato, fg, mineral["forma"]) & livre
    print(f"{args.mineral}: {candidato.sum()} pixels candidatos (de {livre.sum()} livres) "
          f"[fonte={fonte}{', disseminado' if mineral.get('disseminado') else ''}].")

    if args.previa:
        base_el = (mineral.get("mapas_seg") or ["Si"])[0]
        render_previa(Path("saida") / f"previa_{args.mineral}_pre.png",
                      stack_seg[..., els_seg.index(base_el)],
                      f"PRÉ candidato {args.mineral} (mapa {base_el})", candidato)
        return

    if args.auto:
        final = candidato
    elif args.modo == "pontos":
        import napari
        viewer = napari.Viewer(title=f"Pontos: {args.mineral}  (clique ao redor dos grãos; FECHE p/ commitar)")
        for e in elementos:
            viewer.add_image(stack[..., elementos.index(e)], name=e,
                             blending="additive", visible=e in ("Si", "Al", "K", "Fe"))
        viewer.add_labels(candidato.astype(int), name=f"{args.mineral} candidato (ref)",
                          opacity=0.35)
        ja = (rotulos == ident)
        if ja.any():
            viewer.add_labels((ja * 2).astype(int),
                              name=f"{args.mineral} JA commitado ({int(ja.sum())} px)",
                              opacity=0.5)
            print(f"Já commitado: {int(ja.sum())} px. Esta passada SOMA a isso (aditivo).")
        pts_layer = viewer.add_points(np.empty((0, 2)), name="pontos",
                                      size=12, face_color="yellow", border_color="black")
        pts_layer.mode = "add"
        print("Ferramenta Adicionar Pontos ativa. Clique pontos espaçados ao redor de CADA grão.")
        print("Pontos próximos (mesmo grão) são unidos; grupos distantes viram grãos separados.")
        print("FECHE a janela para commitar.")
        napari.run()
        final = pontos_para_regioes(np.asarray(pts_layer.data), frac.shape[:2], args.raio_grupo)
        if args.com_candidato:
            final |= candidato
        if args.so_amostra:
            final &= fg
    else:
        import napari
        viewer = napari.Viewer(title=f"Segmentar: {args.mineral}  (edite e FECHE p/ commitar)")
        for e in elementos:
            viewer.add_image(stack[..., elementos.index(e)], name=e,
                             blending="additive", visible=e in ("Si", "Al", "K", "Fe"))
        camada = viewer.add_labels(candidato.astype(int),
                                   name=f"{args.mineral} (pincel/borracha)")
        print("Edite a máscara (pincel, borracha) e FECHE a janela para commitar.")
        napari.run()
        final = np.asarray(camada.data) > 0

    np.save(EST / "rotulos_prev.npy", rotulos)         # backup de 1 passo (desfazer)
    permitido = (rotulos == 0) | (rotulos == ident)    # não sobrescreve outros minerais
    if args.substituir:
        rotulos[rotulos == ident] = 0
    rotulos[final & permitido] = ident
    np.save(ROT, rotulos)

    progresso = [p for p in progresso if p["id"] != ident]
    progresso.append(dict(id=ident, mineral=args.mineral,
                          condicoes=mineral["condicoes"], data=str(date.today())))
    PROG.write_text(json.dumps(progresso, ensure_ascii=False, indent=2), encoding="utf-8")
    n = int((rotulos == ident).sum())
    print(f"Commitado id={ident} ({args.mineral}): {n} pixels. Estado salvo em {ROT} e {PROG}.")


if __name__ == "__main__":
    main()
