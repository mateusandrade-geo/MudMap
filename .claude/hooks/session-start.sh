#!/bin/bash
# SessionStart do Claude Code NA WEB: prepara .venv/ com Python 3.12+ e as dependências fixadas
# (requirements.txt + pytest) e as bibliotecas do Qt sem tela, para os scripts, o diagnóstico, os testes e
# o app offscreen rodarem. No PC do operador não faz nada (lá o .venv é criado pelo MudMapStudio.bat /
# mudmap_studio.sh ou à mão — ver README).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"
VENV="$PWD/.venv"

python_ok() {   # $1 = interpretador; sucesso se for Python 3.12+
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null
}

# 1. .venv com Python 3.12+ (o container costuma trazer só o 3.11 -> uv baixa o 3.12)
if [ ! -x "$VENV/bin/python" ] || ! python_ok "$VENV/bin/python"; then
  rm -rf "$VENV"
  if command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv "$VENV"
  elif command -v python3 >/dev/null 2>&1 && python_ok python3; then
    python3 -m venv "$VENV"
  else
    UV_BOOT="$HOME/.cache/mudmap-uv"
    [ -x "$UV_BOOT/bin/uv" ] || { python3 -m venv "$UV_BOOT" && "$UV_BOOT/bin/pip" install --quiet uv; }
    "$UV_BOOT/bin/uv" python install 3.12
    "$UV_BOOT/bin/uv" venv --python 3.12 "$VENV"
    "$UV_BOOT/bin/uv" pip install --python "$VENV/bin/python" --quiet pip
  fi
fi

# 2. dependências (idempotente: com tudo instalado o pip só confere as versões)
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements.txt "pytest>=8"

# 3. bibliotecas do sistema para o Qt sem tela (testes da interface e --autoteste)
LDCONFIG="$(command -v ldconfig || echo /sbin/ldconfig)"
if command -v apt-get >/dev/null 2>&1 && ! "$LDCONFIG" -p 2>/dev/null | grep -q 'libEGL.so.1'; then
  SUDO=""
  if [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi
  if ! ($SUDO apt-get update -qq && $SUDO apt-get install -y -qq libegl1 libgl1 libxkbcommon0 \
        libfontconfig1 libdbus-1-3) >/dev/null 2>&1; then
    echo "MudMap: aviso — não consegui instalar as bibliotecas do Qt; os testes da interface podem falhar" >&2
  fi
fi

# 4. ambiente da sessão: `python` = o do .venv; Qt sem tela
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export VIRTUAL_ENV=\"$VENV\""
    echo "export PATH=\"$VENV/bin:\$PATH\""
    echo "export QT_QPA_PLATFORM=offscreen"
  } >> "$CLAUDE_ENV_FILE"
fi
echo "MudMap: ambiente pronto ($("$VENV/bin/python" --version)) — rode: python scripts/diagnostico.py"
