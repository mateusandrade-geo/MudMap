"""Gera o projeto de EXEMPLO sintético (mapas EDS no formato do AZtec + BSE + config + rótulos
de referência) para experimentar o pipeline e o MudMap Studio sem dados reais.

O exemplo é um projeto completo e separado (não mexe no projeto da raiz). Para usá-lo, rode os
scripts DE DENTRO da pasta dele:
    python scripts/gerar_exemplo.py                 # -> exemplo/
    cd exemplo
    python ../scripts/reconhecer.py
    python ../scripts/candidatos.py
    python ../scripts/segmentar.py --mineral ilita --previa

Uso: python scripts/gerar_exemplo.py [--destino exemplo] [--tamanho 640] [--semente 649] [--sem-rotulos]
  --sem-rotulos: estado/ vazio (começa a segmentação do zero); por padrão estado/rotulos.npy
                 traz os grãos da cena (a matriz argilosa fica livre para segmentar).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from mudmap_studio.nucleo import exemplo  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", default="exemplo")
    ap.add_argument("--tamanho", type=int, default=640, help="lado da imagem em px (0,1 µm/px)")
    ap.add_argument("--semente", type=int, default=649)
    ap.add_argument("--sem-rotulos", action="store_true")
    args = ap.parse_args()
    raiz = exemplo.gerar_projeto(args.destino, args.tamanho, args.semente, rotulos=not args.sem_rotulos,
                                 progresso=lambda f, msg: print(f"  [{f * 100:5.1f}%] {msg}", flush=True))
    print(f"Exemplo pronto em {raiz.resolve()}\n"
          f"  mapas: {raiz / exemplo.PASTA_DADOS}\n"
          f"  config: {raiz / 'config' / 'classificacao.yaml'}\n"
          f"  próximo passo: cd {args.destino} && python ../scripts/reconhecer.py")


if __name__ == "__main__":
    main()
