"""Troca o sítio ATIVO do projeto (config/classificacao.yaml + estado/) por um sítio arquivado.

O sítio que sai é guardado ANTES em sitios/<ativo>/ (snapshot leve: arquivos de estado/, cópia da
config e info.json — sem regenerar prévias; para o arquivamento completo, com prévia final e
inspetor, rode antes scripts/arquivar_sitio.py). Nada é apagado: o sítio que sai volta com
`ativar_sitio.py <ele>`.

Uso (raiz do projeto):
  python scripts/ativar_sitio.py --listar     # sítios, pasta de dados e se os mapas existem
  python scripts/ativar_sitio.py 1.1          # ativa sitios/1.1/
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import yaml

CFG = Path("config/classificacao.yaml")
EST = Path("estado")
SITIOS = Path("sitios")


def _tem_mapas(pasta):
    p = Path(pasta)
    return p.is_dir() and any(p.glob("*.tif"))


def sitios():
    """[(sitio, pasta_dados, ativo, tem rotulos)] — o ativo primeiro."""
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    out = [(str(cfg.get("sitio")), cfg["pasta_dados"], True, (EST / "rotulos.npy").exists())]
    if SITIOS.is_dir():
        for d in sorted(p for p in SITIOS.iterdir() if (p / "info.json").exists()):
            info = json.loads((d / "info.json").read_text(encoding="utf-8"))
            s = str(info.get("sitio", d.name))
            if s != out[0][0]:
                out.append((s, info.get("pasta_dados", ""), False, (d / "estado" / "rotulos.npy").exists()))
    return out


def guardar_ativo():
    """Snapshot do ativo em sitios/<s>/ (estado/, classificacao_<s>.yaml, info.json)."""
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    s = str(cfg.get("sitio") or Path(cfg["pasta_dados"]).name)
    d = SITIOS / s
    (d / "estado").mkdir(parents=True, exist_ok=True)
    for f in EST.glob("*"):
        if f.is_file():
            shutil.copy2(f, d / "estado" / f.name)
    shutil.copy2(CFG, d / f"classificacao_{s}.yaml")
    info_p = d / "info.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    info.update({"sitio": s, "pasta_dados": cfg["pasta_dados"], "data_arquivo": date.today().isoformat()})
    if (EST / "rotulos.npy").exists():
        rot = np.load(EST / "rotulos.npy")
        nomes = {i: m["nome"] for i, m in enumerate(cfg["minerais"], start=1)}
        info["px_total"] = int((rot > 0).sum())
        info["por_mineral"] = {nomes.get(int(i), str(i)): int((rot == i).sum()) for i in np.unique(rot) if i > 0}
    info_p.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return s, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sitio", nargs="?", help="sítio a ativar (pasta sitios/<sitio>/)")
    ap.add_argument("--listar", action="store_true", help="só lista os sítios")
    args = ap.parse_args()
    if not CFG.exists():
        sys.exit("Rode na raiz do projeto (onde fica config/classificacao.yaml).")

    lista = sitios()
    if args.listar or not args.sitio:
        print(f"{'sítio':8s} {'situação':10s} {'rótulos':8s} {'mapas':6s} pasta de dados")
        for s, pasta, ativo, tem_rot in lista:
            print(f"{s:8s} {'ATIVO' if ativo else 'arquivado':10s} {'sim' if tem_rot else 'não':8s} "
                  f"{'sim' if _tem_mapas(pasta) else 'FALTA':6s} {pasta}")
        return

    ativo = lista[0][0]
    if args.sitio == ativo:
        print(f"O sítio {ativo} já é o ativo.")
        return
    d = SITIOS / args.sitio
    cfg_novo = d / f"classificacao_{args.sitio}.yaml"
    if not (d / "info.json").exists() or not cfg_novo.exists():
        sys.exit(f"sitios/{args.sitio}/ incompleto (precisa de info.json e classificacao_{args.sitio}.yaml).")

    s_old, d_old = guardar_ativo()
    print(f"sítio {s_old} guardado em {d_old}/")
    for f in EST.glob("*"):                      # já copiados p/ sitios/<s_old>/estado
        if f.is_file():
            f.unlink()
    EST.mkdir(exist_ok=True)
    for f in (d / "estado").glob("*"):
        if f.is_file():
            shutil.copy2(f, EST / f.name)
    shutil.copy2(cfg_novo, CFG)
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    print(f"ATIVO agora: sítio {args.sitio} (config/classificacao.yaml e estado/ vindos de {d}/)")
    if not _tem_mapas(cfg["pasta_dados"]):
        print(f"ATENÇÃO: os mapas EDS de {cfg['pasta_dados']} não estão nesta pasta — copie-os antes de "
              f"rodar os scripts.")


if __name__ == "__main__":
    main()
