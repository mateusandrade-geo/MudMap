"""Estresse 4096²: amplia o sítio ativo 4× (vizinho mais próximo) e mede os tempos críticos.

Referência (2026-09-25, 1.2 ampliado, 111 mil objetos): grãos 5,6 s · prévia 0,15–0,33 s ·
composição cheia 1,1–2,8 s · canal suavizado 1ª vez ~1,4 s · salvar 1,7 s · abrir 0,4 s.

Uso (raiz do repositório):  python app/testes/estresse_4096.py [pasta_do_projeto]
"""
import sys
import tempfile
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[2]
RAIZ = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO     # projeto usado
sys.path.insert(0, str(REPO / "app"))
from mudmap_studio.nucleo import exportar_html, importar, objetos, pacote, relatorio  # noqa: E402
from mudmap_studio.nucleo.amostra import Amostra  # noqa: E402
from mudmap_studio.nucleo.edicao import Editor  # noqa: E402
from mudmap_studio.nucleo.render import CamadaEl, Compositor, Visual  # noqa: E402


def cronometro(nome, fn):
    t = time.time()
    r = fn()
    print(f"{nome:34s} {time.time() - t:6.2f} s", flush=True)
    return r


a = importar.importar_sitio(next(f for f in importar.listar_sitios(RAIZ) if f.ativo))
up = lambda x: None if x is None else np.repeat(np.repeat(x, 4, 0), 4, 1)
am = Amostra(amostra=a.amostra, sitio=f"{a.sitio}x4", pixel_um=a.pixel_um / 4, elementos=a.elementos,
             minerais=a.minerais, area_min=a.area_min * 16, mapas=[up(m) for m in a.mapas], bse=up(a.bse),
             mascara=up(a.mascara), rotulos=up(a.rotulos), clusters=up(a.clusters),
             clusters_info=a.clusters_info, config_yaml=a.config_yaml)
del a
print(f"amostra {am.shape}")
ob = cronometro("grãos (objetos.calcular)", lambda: objetos.calcular(am))
print(f"{'':34s} {ob.n} objetos")
R = cronometro("relatório (relatorio.calcular)", lambda: relatorio.calcular(am, ob))
lut = np.zeros(ob.n + 1, bool)
lut[R.gid[R.classe == 1]] = True
cronometro("destaque de uma classe (máscara)", lambda: lut[ob.objid])
cronometro("CSV de todos os grãos", lambda: relatorio.csv_graos(ob, am))
cronometro("dados do inspetor HTML", lambda: exportar_html.dados(am, ob))
comp = Compositor(am, ob, ("#6b9de8", "#e8c36b", "#e8846b"))
casos = [("bse", Visual()),
         ("bse + contorno + clusters + fora", Visual(estilo="contorno", clusters=am.clusters is not None,
                                                     escurecer_fora=True)),
         ("4 elementos brutos", Visual(fundo="aditivo", camadas=[CamadaEl(e, "#ff0000", 0, 200)
                                                                 for e in am.elementos[:4]])),
         ("canal Si-Mg r=27", Visual(fundo="canal", canal_expr="Si-Mg", canal_raio=27))]
for nome, v in casos:
    cronometro(f"prévia  {nome}", lambda v=v: comp.compor(v, passo=3))
    cronometro(f"cheia   {nome}", lambda v=v: comp.compor(v))
ed = Editor(am)
mid = int(np.bincount(am.rotulos[am.rotulos > 0]).argmax())
cronometro("morfologia convexo (mineral maior)", lambda: ed.morfologia(mid, "convexo"))
cronometro("propagar (mineral maior)", lambda: ed.propagar(mid))
with tempfile.TemporaryDirectory() as d:
    arq = Path(d) / "x4.mudmap"
    cronometro("salvar .mudmap", lambda: pacote.salvar(am, arq))
    print(f"{'':34s} {arq.stat().st_size / 1e6:.1f} MB")
    cronometro("abrir .mudmap", lambda: pacote.abrir(arq))
