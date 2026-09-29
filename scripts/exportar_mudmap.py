"""Exporta um sítio para um pacote .mudmap (abre no MudMap Studio).

Sem --sitio exporta o sítio ATIVO (config + estado/). Com --sitio <s> usa o sítio
arquivado em sitios/<s>/ (se <s> for o ativo, o estado/ tem prioridade).

Uso: PYTHONPATH=scripts python scripts/exportar_mudmap.py [--sitio 1.1] [--todos] [--saida <arq>]
O projeto é a pasta atual (se tiver config/classificacao.yaml), senão a raiz do repositório.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
RAIZ = Path.cwd() if (Path.cwd() / "config" / "classificacao.yaml").exists() else REPO

from mudmap_studio.nucleo import importar, pacote  # noqa: E402


def _progresso(f, msg):
    print(f"  [{f * 100:5.1f}%] {msg}", flush=True)


def exportar(fonte, saida=None):
    print(f"sítio {fonte.sitio} ({fonte.rotulo})")
    am = importar.importar_sitio(fonte, _progresso)
    destino = Path(saida) if saida else RAIZ / "saida" / "mudmap" / f"{am.amostra}_{am.sitio}{pacote.EXT}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    pacote.salvar(am, destino, _progresso)
    tam = destino.stat().st_size / 1e6
    print(f"-> {destino}  ({tam:.1f} MB, {am.shape[1]}x{am.shape[0]} px, "
          f"{len(am.elementos)} elementos, {int((am.rotulos > 0).sum())} px rotulados)")
    return destino


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitio", default=None, help="sítio a exportar (default: o ativo)")
    ap.add_argument("--todos", action="store_true", help="exporta o ativo e todos os arquivados")
    ap.add_argument("--saida", default=None, help="arquivo .mudmap de destino")
    args = ap.parse_args()

    fontes = importar.listar_sitios(RAIZ)
    if args.todos:
        vistos = set()
        for f in fontes:                       # o ativo vem primeiro e tem prioridade
            if f.sitio not in vistos:
                vistos.add(f.sitio)
                exportar(f)
        return
    if args.sitio is None:
        escolhida = next(f for f in fontes if f.ativo)
    else:
        cands = [f for f in fontes if f.sitio == args.sitio]
        if not cands:
            sys.exit(f"Sítio '{args.sitio}' não encontrado (ativo nem em sitios/).")
        escolhida = next((f for f in cands if f.ativo), cands[0])
    exportar(escolhida, args.saida)


if __name__ == "__main__":
    main()
