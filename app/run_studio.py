"""Ponto de entrada do executável (PyInstaller) e atalho para rodar do código-fonte:
    python app/run_studio.py [arquivo.mudmap | --exemplo]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mudmap_studio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
