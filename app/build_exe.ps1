# Gera o executável do MudMap Studio FORA do OneDrive (binários não precisam sincronizar):
#   C:\MudMapStudio\dist\MudMapStudio\MudMapStudio.exe   (build intermediário em C:\MudMapStudio\build)
# Uso (da raiz do projeto):  powershell -ExecutionPolicy Bypass -File app\build_exe.ps1 [-Dist dist_nova]
#   -Dist: outra pasta de saída (ex.: com o app aberto, a pasta dist fica travada; gere em dist_nova,
#          teste, feche o app e troque as pastas — o atalho da Área de Trabalho aponta para dist\)
param([string]$Dist = "dist")
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$py = "C:\Users\faria\AppData\Local\Programs\Python\Python312\python.exe"
$app = Join-Path $raiz "app"
$rec = Join-Path $app "mudmap_studio\recursos"
$saida = "C:\MudMapStudio"
New-Item -ItemType Directory -Force $saida | Out-Null

& $py (Join-Path $app "gerar_icone.py")
# caminhos ABSOLUTOS: com --specpath, relativos seriam resolvidos a partir da pasta do spec
& $py -m PyInstaller --noconfirm --clean --windowed `
    --name MudMapStudio `
    --icon (Join-Path $rec "mudmap.ico") `
    --paths $app --paths (Join-Path $raiz "scripts") `
    --hidden-import common --hidden-import segmentar `
    --add-data "$rec;mudmap_studio\recursos" `
    --add-data "$(Join-Path $raiz 'scripts\inspetor_template.html');scripts" `
    --exclude-module matplotlib --exclude-module napari `
    --exclude-module vispy --exclude-module IPython --exclude-module tkinter `
    --exclude-module pandas --exclude-module PyQt5 --exclude-module PySide6 `
    --distpath (Join-Path $saida $Dist) --workpath (Join-Path $saida "build") `
    --specpath (Join-Path $saida "build") `
    (Join-Path $app "run_studio.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou (app aberto? use -Dist dist_nova)" }
$exe = Join-Path $saida "$Dist\MudMapStudio\MudMapStudio.exe"
$tam = (Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Output ("OK: {0}  ({1:N0} MB na pasta)" -f $exe, $tam)
