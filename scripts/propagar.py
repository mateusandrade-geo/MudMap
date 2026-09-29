"""Propaga a segmentação a partir da SEMENTE do usuário (estado/seg_seed_<min>.npy).

Aprende a assinatura química (fração de cátions) das regiões demarcadas pelo
usuário e procura MAIS regiões com o mesmo padrão (distância de Mahalanobis),
com tamanho de grão compatível. Abre o napari com as regiões propostas + um PONTO
por região; o usuário APAGA os pontos das regiões falsas e FECHA. Só as regiões
cujo ponto sobreviveu (mais a semente) são commitadas em estado/rotulos.npy.

Sempre gera prévia PRÉ (propostas) e PÓS (commitado) para o chat.
"""
import argparse
import json
import warnings
from datetime import date
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi
from skimage import morphology
from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra, id_e_regra)

warnings.filterwarnings("ignore")
EST = Path("estado")
SAIDA = Path("saida")
ROT = EST / "rotulos.npy"
PROG = EST / "progresso.json"


def mahalanobis(frac, mu, inv):
    d = frac - mu
    return np.sqrt(np.einsum("...i,ij,...j->...", d, inv, d))


def previa_png(caminho, base, titulo, mask, centros=None, cor=(1, 0.3, 0.1)):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(b, cmap="gray")
    ov = np.zeros((*mask.shape, 4)); ov[mask] = [*cor, 0.75]
    ax.imshow(ov)
    if centros is not None and len(centros):
        c = np.asarray(centros)
        ax.plot(c[:, 1], c[:, 0], "o", mfc="yellow", mec="k", ms=6)
    _, n = ndi.label(mask)
    ax.set_title(f"{titulo} — {n} regiões, {int(mask.sum())} px")
    ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=130, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}  >> Agente: EXIBA este PNG aqui no chat.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineral", required=True)
    ap.add_argument("--thr", type=float, default=1.2,
                    help="fator sobre a distância de Mahalanobis da semente (p98). Maior = mais permissivo")
    ap.add_argument("--tam-fator", type=float, default=0.3,
                    help="mantém regiões com área entre tam-fator*min_semente e (2-tam-fator)-scaled*max")
    ap.add_argument("--area-frac", type=float, default=0.25,
                    help="piso de área das propostas = area-frac * área mediana dos grãos da semente")
    ap.add_argument("--gate-q", type=float, default=0.10,
                    help="portão: intensidade nos mapas_seg >= este quantil da semente (0 desliga)")
    ap.add_argument("--erode", type=int, default=2,
                    help="erode a semente N px antes de aprender a assinatura (exclui bordas mistas)")
    ap.add_argument("--limpar-semente", dest="limpar", action="store_true", default=True,
                    help="remove pixels soltos/ruído da semente antes de propagar (padrão: liga)")
    ap.add_argument("--sem-limpeza", dest="limpar", action="store_false",
                    help="não limpar a semente (usa como está, inclui speckle)")
    ap.add_argument("--base", default="Si")
    ap.add_argument("--podar", choices=["labels", "pontos"], default="labels",
                    help="labels: edita/remove grãos (balde/pincel); pontos: apaga marcadores")
    ap.add_argument("--previa", action="store_true", help="só gera a prévia PRÉ das propostas e sai")
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    area_min = cfg.get("area_min", 30)
    ident, mineral = id_e_regra(cfg, args.mineral)

    seed_path = EST / f"seg_seed_{args.mineral}.npy"
    if not seed_path.exists():
        raise SystemExit(f"Semente ausente: {seed_path}. Rode revisar_pontos.py antes.")
    seed = np.load(seed_path)

    stack, overlay = carregar_mapas(cfg["pasta_dados"], els)
    frac, soma = fracao_cations(stack)
    fg = mascara_amostra(soma, overlay, cfg.get("corte_fundo"))
    base = stack[..., els.index(args.base)]

    if args.limpar:                                    # remove pixels soltos (speckle)
        bruto = int(seed.sum())
        seed = morphology.binary_opening(seed & fg, morphology.disk(1))
        seed = morphology.remove_small_objects(seed, area_min)
        seed = morphology.remove_small_holes(seed, area_min)
        _, ng = ndi.label(seed)
        print(f"[limpeza] semente {bruto} -> {int(seed.sum())} px, {ng} grãos "
              f"(removido speckle < {area_min} px).")

    # assinatura química: aprende do NÚCLEO dos grãos (erode) p/ excluir bordas mistas
    nucleo = seed & fg
    if args.erode > 0:
        er = morphology.binary_erosion(seed, morphology.disk(args.erode)) & fg
        if er.sum() > 50:                          # só usa o núcleo se sobrar sinal
            nucleo = er
    print(f"assinatura de {int(nucleo.sum())} px de núcleo (erode={args.erode}).")
    px = frac[nucleo]
    mu = px.mean(0)
    cov = np.cov(px.T) + np.eye(len(els)) * 1e-6
    inv = np.linalg.inv(cov)
    seed_d = mahalanobis(px, mu, inv)
    thr = float(np.quantile(seed_d, 0.98)) * args.thr
    print(f"assinatura: mu={dict(zip(els, mu.round(3)))}")
    print(f"limiar Mahalanobis={thr:.2f} (p98 semente={np.quantile(seed_d,0.98):.2f} x{args.thr})")

    # faixa de tamanho dos grãos da semente
    lab_s, ns = ndi.label(seed)
    tam_s = np.bincount(lab_s.ravel())[1:] if ns else np.array([area_min])
    amin = max(area_min, int(np.median(tam_s) * args.area_frac))
    amax = int(tam_s.max() / args.tam_fator)
    print(f"grãos semente: {ns} | área mediana={int(np.median(tam_s))} | "
          f"faixa p/ propostas: {amin}..{amax} px")

    # portão POR REGIÃO: mediana de intensidade do grão nos mapas_seg (robusto a speckle).
    # Limiar = quantil das medianas dos GRÃOS da semente (não do pixel).
    mapas = mineral.get("mapas_seg") or [args.base]
    si_gate = {}
    for e in mapas:
        ch = stack[..., els.index(e)]
        med_graos = [np.median(ch[lab_s == k]) for k in range(1, ns + 1)] if ns else [0]
        si_gate[e] = float(np.quantile(med_graos, args.gate_q)) if args.gate_q > 0 else -np.inf
        print(f"  portão(região) {e}: mediana do grão >= {si_gate[e]:.1f} "
              f"(q{args.gate_q} das medianas de {ns} grãos da semente)")

    # candidatos por Mahalanobis no espaço livre (inclui os pixels do PRÓPRIO
    # mineral, p/ que reeditar reencontre as propostas já commitadas)
    rotulos = np.load(ROT) if ROT.exists() else np.zeros(fg.shape, np.int64)
    livre = fg & ((rotulos == 0) | (rotulos == ident))
    dist = mahalanobis(frac, mu, inv)
    cand = (dist <= thr) & livre
    cand = morphology.remove_small_holes(morphology.remove_small_objects(cand, amin), amin)

    # filtra por tamanho E pela mediana de Si da região; separa seed das NOVAS
    lab_c, nc = ndi.label(cand)
    novas = np.zeros_like(cand)
    centros = []
    for k in range(1, nc + 1):
        reg = lab_c == k
        a = int(reg.sum())
        if a < amin or a > amax:
            continue
        if (reg & seed).mean() > 0.5:      # já é a semente
            continue
        if any(np.median(stack[..., els.index(e)][reg]) < si_gate[e] for e in mapas):
            continue                        # grão pouco brilhante no mapa de segmentação
        novas[reg] = True
        r, c = ndi.center_of_mass(reg)
        centros.append((r, c))
    print(f"propostas NOVAS: {len(centros)} regiões (fora da semente).")

    propostas = novas | seed
    previa_png(SAIDA / f"previa_{args.mineral}_propostas.png", base,
               f"PROPOSTAS {args.mineral} (semente + novas)", propostas, centros)
    if args.previa:
        return

    import napari
    outros = rotulos.copy(); outros[rotulos == ident] = 0      # preserva os demais minerais
    if args.podar == "labels":
        # cada grão (semente + novas) com id único, camada editável.
        edit_lab, _ = ndi.label(propostas)
        edit_lab = edit_lab.astype(np.int32)
        viewer = napari.Viewer(
            title=f"Editar {args.mineral}: Balde+rótulo 0 remove grão | Pincel/Borracha redimensiona | FECHE p/ salvar")
        for e in els:
            viewer.add_image(stack[..., els.index(e)], name=e, blending="additive",
                             visible=e in ("Si", "Al", "K", "Fe"))
        camada = viewer.add_labels(edit_lab, name=f"{args.mineral} propostas (edite)")
        try:
            camada.brush_size = 12
        except Exception:
            pass
        # marcadores das NOVAS só como referência (camada não usada no commit)
        viewer.add_points(np.array(centros) if centros else np.empty((0, 2)),
                          name="novas (ref)", size=14, face_color="yellow", border_color="black")
        print("REMOVER grão: ferramenta Balde (fill), rótulo 0, clique no grão.")
        print("REDIMENSIONAR: Pincel cresce; Borracha encolhe (rótulo do grão).")
        print("FECHE a janela para salvar.")
        napari.run()
        final_mask = np.asarray(camada.data) > 0
    else:
        viewer = napari.Viewer(title=f"Propagação {args.mineral}: APAGUE os pontos das falsas e FECHE")
        for e in els:
            viewer.add_image(stack[..., els.index(e)], name=e, blending="additive",
                             visible=e in ("Si", "Al", "K", "Fe"))
        viewer.add_labels(seed.astype(int), name=f"semente ({int(seed.sum())} px)", opacity=0.4)
        viewer.add_labels((novas * 2).astype(int), name=f"propostas novas ({len(centros)})", opacity=0.5)
        pts_layer = viewer.add_points(np.array(centros) if centros else np.empty((0, 2)),
                                      name="marcadores (apague as falsas)", size=14,
                                      face_color="yellow", border_color="black")
        pts_layer.mode = "select"
        print("APAGUE os marcadores (pontos) das regiões que NÃO são reais e FECHE a janela.")
        napari.run()
        restantes = np.asarray(pts_layer.data)
        aceitas = np.zeros_like(novas)
        for k in range(1, nc + 1):
            reg = lab_c == k
            if not novas[reg].any():
                continue
            r, c = ndi.center_of_mass(reg)
            if len(restantes) and (np.hypot(restantes[:, 0] - r, restantes[:, 1] - c).min() < 15):
                aceitas |= reg
        final_mask = aceitas | seed

    novo = outros.copy()
    novo[final_mask & (novo == 0)] = ident                     # não sobrescreve outros minerais
    rotulos = novo
    np.save(ROT, rotulos)

    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else []
    prog = [p for p in prog if p.get("id") != ident]
    prog.append(dict(id=ident, mineral=args.mineral, metodo="pontos+propagacao",
                     data=str(date.today())))
    PROG.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    previa_png(SAIDA / f"previa_{args.mineral}_pos.png", base,
               f"PÓS {args.mineral} (commitado)", rotulos == ident)
    print(f"Commitado {args.mineral}: {int((rotulos==ident).sum())} px em {ROT}.")


if __name__ == "__main__":
    main()
