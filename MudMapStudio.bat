@echo off
rem MudMap Studio a partir do código-fonte (Windows). Duplo clique para abrir
rem (ou arraste um arquivo .mudmap para cima deste arquivo).
rem Na 1a vez cria o ambiente .venv com Python 3.12+ e instala as dependências fixadas (precisa de internet).
setlocal
cd /d "%~dp0"
if not exist ".venv\instalado.ok" (
    echo Preparando o ambiente na primeira execucao ^(alguns minutos^)...
    if not exist ".venv\Scripts\python.exe" (
        where py >nul 2>nul && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" && py -3 -m venv .venv)
        if not exist ".venv\Scripts\python.exe" (
            python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>nul && python -m venv .venv
        )
    )
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Nao encontrei o Python 3.12 ou mais novo. Instale em https://www.python.org/downloads/
        echo marcando "Add python.exe to PATH", e rode este arquivo de novo.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo. & echo A instalacao falhou; veja a mensagem acima. & pause & exit /b 1)
    echo ok> ".venv\instalado.ok"
)
start "" ".venv\Scripts\pythonw.exe" app\run_studio.py %*
