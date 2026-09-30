#!/usr/bin/env bash
# MudMap Studio a partir do código-fonte (Linux/macOS):  ./mudmap_studio.sh [arquivo.mudmap | --exemplo]
# Na 1a vez cria o ambiente .venv com Python 3.12+ e instala as dependências fixadas (precisa de internet).
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/instalado.ok ]; then
    echo "Preparando o ambiente na primeira execução (alguns minutos)..."
    if [ ! -x .venv/bin/python ]; then
        PY=""
        for c in python3.13 python3.12 python3 python; do
            if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
                PY="$c"; break
            fi
        done
        if [ -z "$PY" ]; then
            echo "Não encontrei Python 3.12 ou mais novo. Instale em https://www.python.org/downloads/"
            echo "(macOS: instalador do python.org ou 'brew install python@3.12'; Ubuntu: 'sudo apt install python3.12-venv')."
            exit 1
        fi
        "$PY" -m venv .venv
    fi
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
    touch .venv/instalado.ok
fi
exec .venv/bin/python app/run_studio.py "$@"
