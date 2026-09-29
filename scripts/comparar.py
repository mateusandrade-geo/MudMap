"""Compara a segmentação do OPERADOR (rotulos.npy) com o candidato automático e
calibra a REGRA (condicoes) a partir da química dos grãos do operador.

- Semelhança: IoU/Dice, precisão (acerto/auto), recall (acerto/operador), por grão.
- Overlay TP/FP/FN salvo em saida/comparar_<mineral>.png (EXIBIR no chat).
- Calibração: para cada elemento decide um corte '>' (mineral é mais rico que o resto)
  ou '<' (mais pobre) pela separação entre grãos do operador e o resto da amostra.
  Só PROPÕE (imprime); aplicação no config é feita à parte, com confirmação.

Uso: PYTHONPATH=scripts python scripts/comparar.py --mineral quartzo [--fonte mapa] [--calibrar]
"""
import argparse
import json
import warnings
from pathlib import Path
import numpy as np

warnings.filterwarnings("ignore")
from scipy import ndimage as ndi
from skimage import morphology

from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra, mascara_mineral, id_e_regra, canal, avaliar_expr)


def limpar(m, area_min):
    return morphology.remove_small_holes(morphology.remove_small_objects(m, area_min), area_min)


def metricas(oper, auto):
    inter = int((oper & auto).sum())
    uni = int((oper | auto).sum())
    o, a = int(oper.sum()), int(auto.sum())
    iou = inter / uni if uni else 0.0
    dice = 2 * inter / (o + a) if (o + a) else 0.0
    prec = inter / a if a else 0.0
    rec = inter / o if o else 0.0
    return dict(iou=round(iou, 3), dice=round(dice, 3), precisao=round(prec, 3),
                recall=round(rec, 3), px_oper=o, px_auto=a, px_acerto=inter)


def por_grao(oper, auto):
    lo, no = ndi.label(oper)
    la, na = ndi.label(auto)
    acertos = sum(1 for g in range(1, no + 1)
                  if (auto[lo == g]).mean() >= 0.5)          # grão do operador coberto >=50%
    fp = sum(1 for g in range(1, na + 1)
             if not (oper[la == g]).any())                   # grão auto sem sobreposição
    return dict(graos_oper=int(no), graos_oper_cobertos=int(acertos),
                graos_auto=int(na), graos_auto_falsos=int(fp))


def candidato_auto(cfg, mineral, args, stack, els, frac, fg, livre):
    """Recria o candidato automático como o segmentar.py (fonte cluster/regra/mapa)."""
    fonte = args.fonte or mineral.get("fonte_default") or (
        "mapa" if (mineral.get("mapas_seg") or mineral.get("mapas_grupos")) else "cluster")
    if fonte == "mapa":
        from segmentar import candidato_mapa, garantir_mapas, candidato_grupos
        if mineral.get("mapas_grupos"):
            m = candidato_grupos(stack, els, frac, fg, mineral["mapas_grupos"],
                                 mineral.get("suavizar", 15), mineral.get("forma"))
        else:
            stk, el2 = garantir_mapas(stack, els, cfg["pasta_dados"], mineral["mapas_seg"])
            m = candidato_mapa(stk, el2, mineral["mapas_seg"], fg,
                               metodo=mineral.get("mapas_limiar", "otsu"),
                               q=mineral.get("mapas_q", 0.65),
                               modo=mineral.get("mapas_modo", "interseccao"))
    elif fonte == "cluster":
        lab = np.load("estado/clusters.npy")
        j = json.loads(Path("estado/clusters.json").read_text(encoding="utf-8"))
        ids = [int(c) for c, nm in j["nomes"].items() if nm == mineral["nome"]]
        m = np.isin(lab, ids) & fg
    else:
        m = mascara_mineral(frac, els, mineral["condicoes"]) & fg
    # espelha o segmentar.py: sem forma -> limpar(area_min) (exceto disseminado);
    # com forma -> o forma faz a limpeza (grupos já aplicaram; regra/mapa aplicam aqui).
    m = m & livre
    if not mineral.get("disseminado") and not mineral.get("forma"):
        m = limpar(m, int(cfg.get("area_min", 30))) & livre
    if mineral.get("forma") and not mineral.get("mapas_grupos"):
        from segmentar import aplicar_forma
        m = aplicar_forma(m, fg, mineral["forma"]) & livre
    return m, fonte


def calibrar_regra(frac, els, oper, fg, sep_min=0.15, pos=0.05, neg=0.95):
    """Propõe condicoes a partir da separação grãos-operador vs resto da amostra."""
    fora = fg & ~oper
    regra = {}
    diag = []
    for i, e in enumerate(els):
        vin = frac[oper, i]; vout = frac[fora, i]
        mi, mo = float(np.median(vin)), float(np.median(vout))
        sep = (mi - mo) / (mi + mo + 1e-9)                    # >0 mineral mais rico
        linha = f"{e}: in={mi:.3f} out={mo:.3f} sep={sep:+.2f}"
        if sep >= sep_min:
            regra[e] = f">{np.quantile(vin, pos):.2f}"; linha += f"  -> {regra[e]}"
        elif sep <= -sep_min:
            regra[e] = f"<{np.quantile(vin, neg):.2f}"; linha += f"  -> {regra[e]}"
        diag.append(linha)
    return regra, diag


def render(caminho, base, oper, auto, titulo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(b, cmap="gray")
    ov = np.zeros((*oper.shape, 4))
    ov[oper & auto] = [0.1, 0.9, 0.1, 0.85]      # TP verde
    ov[auto & ~oper] = [0.95, 0.15, 0.15, 0.85]  # FP vermelho
    ov[oper & ~auto] = [0.2, 0.4, 1.0, 0.85]     # FN azul
    ax.imshow(ov)
    ax.set_title(titulo, fontsize=12); ax.set_xticks([]); ax.set_yticks([])
    Path("saida").mkdir(exist_ok=True)
    fig.savefig(caminho, dpi=130, bbox_inches="tight"); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineral", required=True)
    ap.add_argument("--fonte", choices=["cluster", "regra", "mapa"], default=None)
    ap.add_argument("--calibrar", action="store_true")
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    stack, overlay = carregar_mapas(cfg["pasta_dados"], els)
    frac, soma = fracao_cations(stack)
    fg = mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, els)
    ident, mineral = id_e_regra(cfg, args.mineral)

    rotulos = np.load("estado/rotulos.npy")
    oper = (rotulos == ident)
    if not oper.any():
        raise SystemExit(f"'{args.mineral}' não está commitado em rotulos.npy — nada a comparar.")
    livre = fg & ((rotulos == 0) | oper)         # não penaliza áreas de outros minerais

    auto, fonte = candidato_auto(cfg, mineral, args, stack, els, frac, fg, livre)
    m = metricas(oper, auto); g = por_grao(oper, auto)
    print(f"\n# Comparação {args.mineral} — operador vs auto(fonte={fonte})")
    print(f"  IoU={m['iou']}  Dice={m['dice']}  precisão={m['precisao']}  recall={m['recall']}")
    print(f"  px: operador={m['px_oper']} auto={m['px_auto']} acerto={m['px_acerto']}")
    print(f"  grãos: operador={g['graos_oper']} (cobertos>=50% {g['graos_oper_cobertos']}) | "
          f"auto={g['graos_auto']} (falsos {g['graos_auto_falsos']})")

    # regra atual
    regra_atual = limpar(mascara_mineral(frac, els, mineral["condicoes"]) & fg, int(cfg.get("area_min", 30)))
    ma = metricas(oper, regra_atual)
    print(f"  regra ATUAL {mineral['condicoes']}\n    -> IoU={ma['iou']} precisão={ma['precisao']} recall={ma['recall']}")

    if args.calibrar:
        regra, diag = calibrar_regra(frac, els, oper, fg)
        prop = limpar(mascara_mineral(frac, els, regra) & fg, int(cfg.get("area_min", 30)))
        mp = metricas(oper, prop)
        print("  separação por elemento (in=grãos do operador, out=resto):")
        for d in diag:
            print("    " + d)
        print(f"  regra PROPOSTA: {regra}")
        print(f"    -> IoU={mp['iou']} precisão={mp['precisao']} recall={mp['recall']}  "
              f"(atual IoU={ma['iou']})")
        Path("saida").mkdir(exist_ok=True)
        Path(f"saida/calibra_{args.mineral}.json").write_text(
            json.dumps({"mineral": args.mineral, "regra_atual": mineral["condicoes"],
                        "regra_proposta": regra, "iou_atual": ma["iou"], "iou_proposta": mp["iou"]},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    base_el = (mineral.get("mapas_seg") or ["Si"])[0]
    render(f"saida/comparar_{args.mineral}.png", stack[..., els.index(base_el)], oper, auto,
           f"{args.mineral}: TP verde / FP vermelho / FN azul  (fonte={fonte}, IoU={m['iou']})")
    print(f"[prévia] saida/comparar_{args.mineral}.png  >> Agente: EXIBA no chat.")


if __name__ == "__main__":
    main()
