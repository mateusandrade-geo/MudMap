# Gera o executável do MudMap Studio (Windows, PyInstaller):
#   <Saida>\<Dist>\MudMapStudio\MudMapStudio.exe   (build intermediário em <Saida>\build)
# Uso (da raiz do projeto):
#   powershell -ExecutionPolicy Bypass -File app\build_exe.ps1 [-Python <python.exe>] [-Saida C:\MudMapStudio] [-Dist dist]
#   -Python: interpretador com o requirements.txt instalado (default: py -3 / python do PATH)
#   -Saida:  pasta de saída. Default C:\MudMapStudio = FORA do OneDrive (binários não precisam sincronizar)
#   -Dist:   subpasta do executável (ex.: com o app aberto, a pasta dist fica travada; gere em dist_nova,
#            teste, feche o app e troque as pastas — o atalho da Área de Trabalho aponta para dist\)
#   -Zip:    também empacota a pasta do executável em <Saida>\MudMapStudio-windows.zip
param([string]$Python = "", [string]$Saida = "C:\MudMapStudio", [string]$Dist = "dist", [switch]$Zip)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = (& py -3 -c "import sys; print(sys.executable)") }
    else { $Python = (Get-Command python).Source }
}
$app = Join-Path $raiz "app"
$rec = Join-Path $app "mudmap_studio\recursos"
New-Item -ItemType Directory -Force $Saida | Out-Null
Write-Output "Python: $Python"
# (sem redirecionar stderr: no Windows PowerShell 5.1 isso vira erro com ErrorActionPreference=Stop)
& $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) { & $Python -m pip install pyinstaller; if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller falhou" } }

& $Python (Join-Path $app "gerar_icone.py")
$versao = Join-Path $Saida "build\versao_exe.txt"         # Propriedades -> Detalhes do .exe
& $Python (Join-Path $app "versao_exe.py") $versao
if ($LASTEXITCODE -ne 0) { throw "versao_exe.py falhou" }
# caminhos ABSOLUTOS: com --specpath, relativos seriam resolvidos a partir da pasta do spec
& $Python -m PyInstaller --noconfirm --clean --windowed `
    --name MudMapStudio `
    --icon (Join-Path $rec "mudmap.ico") `
    --version-file $versao `
    --paths $app --paths (Join-Path $raiz "scripts") `
    --hidden-import common --hidden-import segmentar `
    --add-data "$rec;mudmap_studio\recursos" `
    --add-data "$(Join-Path $raiz 'scripts\inspetor_template.html');scripts" `
    --exclude-module matplotlib --exclude-module napari `
    --exclude-module vispy --exclude-module IPython --exclude-module tkinter `
    --exclude-module pandas --exclude-module PyQt5 --exclude-module PySide6 `
    --distpath (Join-Path $Saida $Dist) --workpath (Join-Path $Saida "build") `
    --specpath (Join-Path $Saida "build") `
    (Join-Path $app "run_studio.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou (app aberto? use -Dist dist_nova)" }
$exe = Join-Path $Saida "$Dist\MudMapStudio\MudMapStudio.exe"
$tam = (Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Output ("OK: {0}  ({1:N0} MB na pasta)" -f $exe, $tam)
if ($Zip) {
    $z = Join-Path $Saida "MudMapStudio-windows.zip"
    if (Test-Path $z) { Remove-Item $z }
    Compress-Archive -Path (Split-Path $exe) -DestinationPath $z
    Write-Output ("ZIP: {0}  ({1:N0} MB)" -f $z, ((Get-Item $z).Length / 1MB))
}
