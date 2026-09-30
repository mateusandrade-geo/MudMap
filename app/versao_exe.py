"""Gera o arquivo de versão do Windows (Propriedades → Detalhes do .exe) a partir de
mudmap_studio.__version__, no formato do --version-file do PyInstaller.

Uso: python app/versao_exe.py <saida.txt>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mudmap_studio import __version__  # noqa: E402

MODELO = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'MudMap'),
      StringStruct('FileDescription', 'MudMap Studio - segmentação mineral por EDS'),
      StringStruct('FileVersion', '{s}'),
      StringStruct('InternalName', 'MudMapStudio'),
      StringStruct('OriginalFilename', 'MudMapStudio.exe'),
      StringStruct('ProductName', 'MudMap Studio'),
      StringStruct('ProductVersion', '{s}')])]),
    VarFileInfo([VarStruct('Translation', [0x0416, 1200])])
  ]
)
"""


def texto(versao=__version__):
    nums = [int(x) for x in versao.split(".")[:4] if x.isdigit()]
    v = tuple((nums + [0, 0, 0, 0])[:4])
    return MODELO.format(v=v, s=versao)


if __name__ == "__main__":
    destino = Path(sys.argv[1])
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto(), encoding="utf-8")
    print(f"versão {__version__} -> {destino}")
