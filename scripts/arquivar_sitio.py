"""Arquiva os DELIVERABLES do sítio ATIVO (config['sitio']) — não-destrutivo.

Regenera e copia, por sítio, para:
  - saida/previas_finais/previa_<sitio>.png   (imagem final da sessão = mapa_atual)
  - saida/inspetores/<sitio>/                 (inspetor completo: index.html + png + json)
  - sitios/<sitio>/estado/                    (SNAPSHOT do estado/ — recuperável ao trocar de amostra)
  - sitios/<sitio>/info.json                  (sitio, pasta_dados, data, contagem por mineral, url do inspetor)

Rode ANTES de trocar de amostra: garante que o sítio atual fica 100% recuperável
(o estado/ é sobrescrito ao começar outro sítio). Ver "Trocar de sítio" no SKILL.md.

Uso: PYTHONPATH=scripts python scripts/arquivar_sitio.py [--url <artifact_url>]
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import common


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/classificacao.yaml")
    ap.add_argument("--url", default=None, help="URL do artefato publicado do inspetor (registro)")
    ap.add_argument("--sem-regenerar", action="store_true",
                    help="só copia as saídas existentes (não roda mapa_atual/exportar_graos)")
    args = ap.parse_args()

    cfg = common.carregar_config(args.config)
    sitio = str(cfg.get("sitio") or Path(cfg["pasta_dados"]).name)
    py = sys.executable

    prev_dir = Path("saida/previas_finais"); prev_dir.mkdir(parents=True, exist_ok=True)
    insp_dir = Path(f"saida/inspetores/{sitio}"); insp_dir.mkdir(parents=True, exist_ok=True)
    est_arch = Path(f"sitios/{sitio}/estado"); est_arch.mkdir(parents=True, exist_ok=True)
    prev_rel = f"previas_finais/previa_{sitio}.png"   # mapa_atual prefixa 'saida/'
    prev_png = Path("saida") / prev_rel

    if not args.sem_regenerar:
        aqui = Path(__file__).resolve().parent            # funciona rodando de qualquer raiz de projeto
        subprocess.run([py, str(aqui / "mapa_atual.py"), "--saida", prev_rel, "--config", args.config], check=True)
        subprocess.run([py, str(aqui / "exportar_graos.py"), "--config", args.config], check=True)
    elif Path("saida/previa_atual.png").exists():
        shutil.copy2("saida/previa_atual.png", prev_png)

    # inspetor completo
    for f in ("index.html", "graos_bse.png", "graos_idmap.png", "graos.json"):
        src = Path("saida/graos") / f
        if src.exists():
            shutil.copy2(src, insp_dir / f)

    # snapshot do estado/
    for f in Path("estado").glob("*"):
        if f.is_file():
            shutil.copy2(f, est_arch / f.name)

    # cópia da config do sítio (elementos/pixel_um/regras variam por sítio; o MudMap Studio
    # e a volta a um sítio arquivado leem sitios/<s>/classificacao_<s>.yaml)
    shutil.copy2(args.config, Path(f"sitios/{sitio}/classificacao_{sitio}.yaml"))

    # info por mineral (a partir de rotulos.npy)
    rot = np.load("estado/rotulos.npy")
    nomes = {i: m["nome"] for i, m in enumerate(cfg["minerais"], start=1)}
    por_min = {}
    for i in np.unique(rot):
        if i > 0:
            por_min[nomes[int(i)]] = int((rot == i).sum())

    info_path = Path(f"sitios/{sitio}/info.json")
    info = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            info = {}
    info.update({
        "sitio": sitio,
        "pasta_dados": cfg["pasta_dados"],
        "data_arquivo": date.today().isoformat(),
        "px_total": int((rot > 0).sum()),
        "por_mineral": por_min,
    })
    if args.url:
        info["inspetor_url"] = args.url
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ARQUIVADO sítio {sitio}:")
    print(f"  prévia final : {prev_png}")
    print(f"  inspetor     : {insp_dir}/  ({len(list(insp_dir.glob('*')))} arquivos)")
    print(f"  estado (bkp) : {est_arch}/")
    print(f"  info         : {info_path}")
    if args.url:
        print(f"  inspetor_url : {args.url}")


if __name__ == "__main__":
    main()
