"""Lista de minerais candidatos (determinística) para um conjunto EDS.

Agrega os clusters do k-means (estado/clusters.*) por NOME de mineral — cada
cluster já foi nomeado pela 1a regra do config que o centro satisfaz —, conta
grãos e % de área, resume a composição média e renderiza uma prévia em painel
sobre o mapa de Si. Salva estado/candidatos.json e saida/candidatos_previa.png.

O AGENTE deve EXIBIR a prévia aqui no chat e pedir ao usuário para escolher UM
mineral e o método (napari | pontos).
"""
import json
import warnings
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import ndimage as ndi
from skimage import morphology
from common import (carregar_config, carregar_mapas, fracao_cations,
                    mascara_amostra)

warnings.filterwarnings("ignore")
EST = Path("estado")
SAIDA = Path("saida")


def main():
    cfg = carregar_config()
    els = cfg["elementos"]
    area_min = cfg.get("area_min", 30)
    pixel_um = cfg.get("pixel_um")

    stack, overlay = carregar_mapas(cfg["pasta_dados"], els)
    frac, soma = fracao_cations(stack)
    fg = mascara_amostra(soma, overlay, cfg.get("corte_fundo"), stack, els)
    total = max(int(fg.sum()), 1)

    lab = np.load(EST / "clusters.npy")
    j = json.loads((EST / "clusters.json").read_text(encoding="utf-8"))
    nomes = j["nomes"]  # {"1": "quartzo", ...}

    # ordem do config (prioridade) para minerais presentes; "sem_classe" à parte
    presentes = [m["nome"] for m in cfg["minerais"] if m["nome"] in nomes.values()]
    cor_de = {m["nome"]: m.get("cor", "#888888") for m in cfg["minerais"]}
    feld = {m["nome"] for m in cfg["minerais"] if m.get("feldspato")}

    candidatos = []
    mascaras = {}
    for nome in presentes:
        ids = [int(cid) for cid, nm in nomes.items() if nm == nome]
        mask = np.isin(lab, ids) & fg
        mask = morphology.remove_small_holes(
            morphology.remove_small_objects(mask, area_min), area_min)
        mascaras[nome] = mask
        _, n = ndi.label(mask)
        px = int(mask.sum())
        comp = ({e: round(float(frac[mask, i].mean()), 3) for i, e in enumerate(els)}
                if px else {e: 0.0 for e in els})
        candidatos.append(dict(
            nome=nome, cor=cor_de[nome], feldspato=nome in feld, fonte="cluster",
            pct_area=round(px / total * 100, 1), n_graos=int(n), n_pixels=px,
            area_um2=(round(px * pixel_um ** 2, 1) if pixel_um else None),
            clusters=ids, composicao_media=comp))

    # ---- candidatos por MAPA: minerais com mapas_seg que nenhum cluster nomeou ----
    from segmentar import candidato_mapa, garantir_mapas
    for m in cfg["minerais"]:
        nome = m["nome"]
        if not m.get("mapas_seg") or nome in nomes.values():
            continue
        stk, el2 = garantir_mapas(stack, els, cfg["pasta_dados"], m["mapas_seg"])
        mask = candidato_mapa(stk, el2, m["mapas_seg"], fg,
                              metodo=m.get("mapas_limiar", "otsu"),
                              q=m.get("mapas_q", 0.65),
                              modo=m.get("mapas_modo", "interseccao"))
        mask = morphology.remove_small_holes(
            morphology.remove_small_objects(mask, area_min), area_min)
        mascaras[nome] = mask
        _, n = ndi.label(mask)
        px = int(mask.sum())
        comp = ({e: round(float(frac[mask, i].mean()), 3) for i, e in enumerate(els)}
                if px else {e: 0.0 for e in els})
        candidatos.append(dict(
            nome=nome, cor=cor_de[nome], feldspato=nome in feld, fonte="mapa",
            pct_area=round(px / total * 100, 1), n_graos=int(n), n_pixels=px,
            area_um2=(round(px * pixel_um ** 2, 1) if pixel_um else None),
            clusters=[], composicao_media=comp))

    candidatos.sort(key=lambda d: d["pct_area"], reverse=True)
    sem_classe_pct = round(
        (np.isin(lab, [int(c) for c, nm in nomes.items() if nm == "sem_classe"]) & fg).sum()
        / total * 100, 1)

    EST.mkdir(exist_ok=True)
    (EST / "candidatos.json").write_text(json.dumps(
        {"conjunto": cfg["pasta_dados"], "sem_classe_pct": sem_classe_pct,
         "candidatos": candidatos}, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- lista no console ----
    print(f"\n# Minerais candidatos — {cfg['pasta_dados']}")
    print(f"{'mineral':16s}{'%area':>7}{'graos':>7}   composição dominante")
    for c in candidatos:
        comp = c["composicao_media"]
        dom = ", ".join(f"{e}={comp[e]:.2f}" for e in sorted(comp, key=comp.get, reverse=True)[:3])
        flag = " [feldspato]" if c["feldspato"] else ""
        flag += "" if c.get("fonte") == "cluster" else "  (mapa)"
        print(f"{c['nome']:16s}{c['pct_area']:7.1f}{c['n_graos']:7d}   {dom}{flag}")
    print(f"{'(sem classe)':16s}{sem_classe_pct:7.1f}")

    # ---- prévia em painel ----
    base = stack[..., els.index("Si")]
    base = base / (base.max() or 1)
    cols = 3
    rows = int(np.ceil(len(candidatos) / cols))
    fig, axs = plt.subplots(rows, cols, figsize=(4.6 * cols, 4.6 * rows), squeeze=False)
    for ax, c in zip(axs.ravel(), candidatos):
        mask = mascaras[c["nome"]]
        col = np.array([int(c["cor"][k:k + 2], 16) / 255 for k in (1, 3, 5)])
        ax.imshow(base, cmap="gray")
        ov = np.zeros((*mask.shape, 4)); ov[mask] = [*col, 0.85]
        ax.imshow(ov)
        marca = "" if c.get("fonte") == "cluster" else " (mapa)"
        ax.set_title(f"{c['nome']}{marca} — {c['pct_area']:.1f}% | {c['n_graos']} grãos", fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
    for ax in axs.ravel()[len(candidatos):]:
        ax.axis("off")
    fig.suptitle(f"Candidatos — {cfg['pasta_dados']}", fontsize=13)
    SAIDA.mkdir(exist_ok=True)
    fig.savefig(SAIDA / "candidatos_previa.png", dpi=130, bbox_inches="tight")
    print("\nSalvos: estado/candidatos.json e saida/candidatos_previa.png")


if __name__ == "__main__":
    main()
