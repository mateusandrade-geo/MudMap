#!/usr/bin/env bash
# MudMap Studio a partir do código-fonte (Linux/macOS):  ./mudmap_studio.sh [arquivo.mudmap | --exemplo]
# Na 1a vez cria o ambiente .venv e instala as dependências (precisa de internet e do Python 3.10+).
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/instalado.ok ]; then
    echo "Preparando o ambiente na primeira execução (alguns minutos)..."
    [ -x .venv/bin/python ] || python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
    touch .venv/instalado.ok
fi
exec .venv/bin/python app/run_studio.py "$@"
