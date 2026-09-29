"""Reconhecimento por k-means: agrupa assinaturas químicas e nomeia cada cluster
pela primeira regra do config (prioridade) que o CENTRO satisfaz. Salva o estado
para a segmentação usar como candidato robusto (regiões contíguas, não speckle).

O mapa de rótulos é regularizado espacialmente (filtro de maioria) para virar
regiões contíguas — a classificação pixel-a-pixel é 'sal-e-pimenta' e sozinha
some na limpeza morfológica."""
import argparse
import json
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra, mascara_mineral)

EST = Path("estado")
CLU = EST / "clusters.npy"
CLUJ = EST / "clusters.json"


def nomear(centro, cfg, els):
    fr = centro.reshape(1, 1, -1)
    for m in cfg["minerais"]:
        if mascara_mineral(fr, els, m["condicoes"])[0, 0]:
            return m["nome"]
    return "sem_classe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=9)
    ap.add_argument("--pasta", default=None)
    ap.add_argument("--raio", type=int, default=4,
                    help="raio do filtro de maioria p/ regularizar rótulos (0=desliga)")
    args = ap.parse_args()

    cfg = carregar_config()
    els = cfg["elementos"]
    pasta = args.pasta or cfg["pasta_dados"]
    stack, overlay = carregar_mapas(pasta, els)
    frac, soma = fracao_cations(stack)
    fg = mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, els)

    from sklearn.cluster import KMeans
    px = frac[fg]
    km = KMeans(n_clusters=args.k, n_init=10, random_state=0).fit(px)
    nomes = [nomear(km.cluster_centers_[i], cfg, els) for i in range(args.k)]

    lab = np.zeros(fg.shape, np.uint16)
    lab[fg] = km.labels_ + 1
    if args.raio > 0:                        # regularização espacial (maioria)
        from skimage.filters.rank import modal
        from skimage.morphology import disk
        lab = modal(lab, disk(args.raio), mask=fg)
        lab[~fg] = 0
    lab = lab.astype(np.int32)
    EST.mkdir(exist_ok=True)
    np.save(CLU, lab)

    resumo = pd.DataFrame(km.cluster_centers_, columns=els).round(3)
    resumo["nome"] = nomes
    resumo["%area"] = [(km.labels_ == i).sum() / len(px) * 100 for i in range(args.k)]
    CLUJ.write_text(json.dumps(
        {"nomes": {str(i + 1): nomes[i] for i in range(args.k)},
         "centros": {str(i + 1): km.cluster_centers_[i].round(4).tolist() for i in range(args.k)},
         "elementos": els}, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.set_option("display.width", 200)
    print(resumo.sort_values("%area", ascending=False).to_string())
    print(f"\nSalvo: {CLU} e {CLUJ}. Use em segmentar.py (--fonte cluster).")


if __name__ == "__main__":
    main()
