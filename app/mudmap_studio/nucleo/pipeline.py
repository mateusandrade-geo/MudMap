"""Acesso ao código do pipeline (scripts/common.py e scripts/segmentar.py).

O app usa as MESMAS funções das regras (decodificação, máscara, canal composto, média
suavizada com máscara) -> o que se vê no app é exatamente o que as regras enxergam.
No .exe esses módulos vão embutidos (PyInstaller: --paths scripts + --hidden-import).
"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if _SCRIPTS.is_dir() and str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import common  # noqa: E402,F401
import segmentar  # noqa: E402,F401  (só numpy + common no import)
