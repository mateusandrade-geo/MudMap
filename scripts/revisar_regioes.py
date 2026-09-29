"""Editor de REGIÕES por círculo (retângulo/elipse) no napari — para REMOVER e REATRIBUIR.

Motivação: quando a borracha/balde da camada Labels não está acessível, o operador
circunda regiões. Duas camadas de Shapes:
  - "remover"  (vermelho): dentro dela, os pixels do mineral-alvo viram 0 (removidos).
  - "pirita"   (ciano):    dentro dela, reatribui a outro mineral (default pirita):
                           pixels do mineral-alvo E/OU livres com Fe&S altos -> id da pirita.

Use RETÂNGULO ou ELIPSE (o polígono/lasso é bugado nesta versão). Ligue o mapa de S
(e Fe) para localizar a pirita. Ao FECHAR: backup em rotulos_prev.npy, grava rotulos.npy
(sem invadir outros minerais) e gera prévias PÓS. Encerrar o processo antes de fechar = cancela.

Uso: PYTHONPATH=scripts python scripts/revisar_regioes.py [--alvo sulfato_ca] [--reatribuir pirita]
     [--fe-min 0.12 --s-min 0.12]
"""
import argparse, json, warnings
from datetime import date
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")
from common import carregar_config, carregar_mapas, fracao_cations, mascara_amostra, id_e_regra

EST = Path("estado"); SAIDA = Path("saida"); ROT = EST / "rotulos.npy"; PROG = EST / "progresso.json"


def uniao_shapes(viewer, nome, shape):
    reg = np.zeros(shape, bool)
    try:
        masks = viewer.layers[nome].to_masks(mask_shape=shape)
    except Exception as e:
        print(f"[{nome}] sem formas legíveis ({e}).")
        return reg
    for m in masks:
        reg |= np.asarray(m, bool)
    return reg


def previa(caminho, base, titulo, mask, cor):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from scipy import ndimage as ndi
    b = base / (base.max() or 1)
    fig, ax = plt.subplots(figsize=(11, 11)); ax.imshow(b, cmap="gray")
    ov = np.zeros((*mask.shape, 4)); ov[mask] = [*cor, 0.6]; ax.imshow(ov)
    _, n = ndi.label(mask)
    ax.set_title(f"{titulo} — {n} objetos, {int(mask.sum())} px"); ax.set_xticks([]); ax.set_yticks([])
    SAIDA.mkdir(exist_ok=True); fig.savefig(caminho, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[prévia] {caminho}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alvo", default="sulfato_ca", help="mineral cujos objetos serão removidos/reatribuídos")
    ap.add_argument("--reatribuir", default="pirita", help="mineral que receberá a região da pirita")
    ap.add_argument("--fe-min", type=float, default=0.12)
    ap.add_argument("--s-min", type=float, default=0.12)
    args = ap.parse_args()

    cfg = carregar_config(); els = cfg["elementos"]
    id_alvo, _ = id_e_regra(cfg, args.alvo)
    id_re, _ = id_e_regra(cfg, args.reatribuir)
    stack, overlay = carregar_mapas(cfg["pasta_dados"], els)
    frac, soma = fracao_cations(stack)
    fe = frac[..., els.index("Fe")]; s = frac[..., els.index("S")]
    rot = np.load(ROT); shape = rot.shape

    import napari
    viewer = napari.Viewer(title=f"Regiões: remover {args.alvo} / pirita->{args.reatribuir}  (RETÂNGULO/ELIPSE; FECHE p/ salvar)")
    vis = {"S", "Fe", "Ca"}
    for e in els:
        viewer.add_image(stack[..., els.index(e)], name=e, blending="additive", visible=e in vis)
    viewer.add_labels((rot == id_alvo).astype(int) * id_alvo, name=f"{args.alvo} (ref)", opacity=0.4)
    viewer.add_shapes(name="remover", edge_color="#ff3030", face_color=[1, 0.1, 0.1, 0.25], edge_width=3)
    viewer.add_shapes(name="pirita", edge_color="#00e0ff", face_color=[0, 0.6, 1, 0.25], edge_width=3)
    print(__doc__)
    print(">> Desenhe ELIPSES/RETÂNGULOS na camada 'remover' (objetos a apagar) e na 'pirita'.")
    print(">> Ligue o mapa de S/Fe para achar a pirita. FECHE a janela para salvar.")
    napari.run()

    reg_rem = uniao_shapes(viewer, "remover", shape)
    reg_pir = uniao_shapes(viewer, "pirita", shape)
    print(f"remover: {int(reg_rem.sum())} px circundados | pirita: {int(reg_pir.sum())} px circundados")

    novo = rot.copy()
    # remover: apaga o mineral-alvo dentro das regiões marcadas
    rem_px = int(((novo == id_alvo) & reg_rem).sum())
    novo[(novo == id_alvo) & reg_rem] = 0
    # pirita: reatribui alvo->pirita e captura livres com Fe&S altos dentro do círculo
    pir_chem = (fe > args.fe_min) & (s > args.s_min)
    alvo_no_pir = (novo == id_alvo) & reg_pir
    livre_pir = (novo == 0) & reg_pir & pir_chem
    novo[alvo_no_pir] = id_re
    novo[livre_pir] = id_re
    pir_px = int((novo == id_re).sum())

    np.save(EST / "rotulos_prev.npy", rot)                 # backup (rule 8)
    np.save(ROT, novo)
    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else []
    prog = [p for p in prog if p.get("id") not in (id_alvo, id_re)]
    prog.append(dict(id=id_alvo, mineral=args.alvo, metodo="revisar_regioes", data=str(date.today())))
    if pir_px:
        prog.append(dict(id=id_re, mineral=args.reatribuir, metodo="revisar_regioes(circulo)", data=str(date.today())))
    prog.sort(key=lambda p: p["id"])
    PROG.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")

    ca = frac[..., els.index("Ca")]
    previa(SAIDA / f"previa_{args.alvo}_pos.png", (ca + s), f"PÓS {args.alvo}", novo == id_alvo, (1, 0.85, 0.2))
    print(f"{args.alvo}: removi {rem_px} px; agora {int((novo==id_alvo).sum())} px.")
    if pir_px:
        previa(SAIDA / f"previa_{args.reatribuir}_pos.png", np.minimum(fe, s), f"PÓS {args.reatribuir} (pirita)", novo == id_re, (0, 0.8, 1))
        print(f"{args.reatribuir} (pirita): {pir_px} px.")


if __name__ == "__main__":
    main()
