"""Valida o núcleo do MudMap Studio contra o pipeline (scripts/), no SÍTIO ATIVO do projeto.

Checa (assert) — o que precisa bater exatamente:
  1. importação = pipeline: mapas e máscara idênticos a common.carregar_mapas/mascara_amostra
  2. canais derivados = common.canal + segmentar._suave_mascarado (erro relativo < 1e-6)
  3. k-means do app = estado/clusters.npy (se existir e o k/config não mudaram)
  4. config_texto: regravar cada mineral com os mesmos parâmetros não muda a config interpretada;
     alterar mantém todos os comentários
  5. Editor: operações + desfazer tudo = original; refazer tudo = final
  6. .mudmap: salvar/abrir preserva rótulos e guarda a versão anterior
Informa (sem assert): candidato de cada mineral rotulado × rotulado (IoU/Dice) e tempos.

Uso (raiz do projeto):  python app/testes/validar_nucleo.py
"""
import copy
import sys
import tempfile
import time
import warnings
from pathlib import Path

import numpy as np
import yaml

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ / "app"), str(RAIZ / "scripts")]
import common  # noqa: E402
import segmentar  # noqa: E402
from mudmap_studio.nucleo import config_texto, importar, objetos, pacote  # noqa: E402
from mudmap_studio.nucleo.amostra import elementos_da_expr  # noqa: E402
from mudmap_studio.nucleo import segmentacao as sg  # noqa: E402
from mudmap_studio.nucleo.edicao import Editor, capsula  # noqa: E402
from mudmap_studio.nucleo.render import Compositor, Visual, CamadaEl  # noqa: E402

falhas = []


def checar(cond, msg):
    print(("  OK   " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


t0 = time.time()
fonte = next(f for f in importar.listar_sitios(RAIZ) if f.ativo)
am = importar.importar_sitio(fonte)
print(f"sítio ativo {fonte.sitio}: {am.shape}, elementos {am.elementos} ({time.time() - t0:.1f}s)")

print("1. importação × pipeline")
cfg = yaml.safe_load(Path(fonte.config).read_text(encoding="utf-8"))
stack, ov = common.carregar_mapas(RAIZ / cfg["pasta_dados"], cfg["elementos"])
frac, soma = common.fracao_cations(stack)
fg = common.mascara_amostra(soma, ov, cfg.get("corte_fundo"), stack, cfg["elementos"])
checar(bool((fg == am.mascara).all()), f"máscara idêntica ({int(fg.sum())} px)")
checar(all((np.rint(stack[..., i]).astype(np.uint8)[fg] == am.mapas[i][fg]).all() for i in range(len(am.mapas))),
       "mapas idênticos dentro da amostra")

print("2. canais derivados × pipeline")
ob = objetos.calcular(am)
comp = Compositor(am, ob, ("#6b9de8", "#e8c36b", "#e8846b"))
for expr, tipo, r in [("Si-Mg", "frac", 27), ("Mg", "raw", 27), ("Al/Si", "frac", 0), ("Fe+Mg", "raw", 15)]:
    if any(t not in am.elementos for t in elementos_da_expr(expr)):
        continue
    base = common.canal(frac if tipo == "frac" else stack, cfg["elementos"], expr)
    ref = segmentar._suave_mascarado(base, fg, r) if r > 1 else base
    arr, _st = comp.canal(expr, tipo, r)
    rel = np.abs(arr[fg] - ref[fg]).max() / max(1e-9, np.abs(ref[fg]).max())
    checar(rel < 1e-6, f"{expr} {tipo} r={r}: erro relativo {rel:.1e}")
for v in (Visual(estilo="contorno", clusters=am.clusters is not None, escurecer_fora=True),
          Visual(fundo="aditivo", camadas=[CamadaEl(am.elementos[0], "#ff0000", 0, 200)]),
          Visual(fundo="canal", canal_expr=am.elementos[0], canal_raio=15)):
    rgb, _i = comp.compor(v)
    checar(rgb.shape == (*am.shape, 3), f"compor fundo={v.fundo}")

print("candidatos (informativo): candidato do mineral × rotulado, 'livres + o próprio'")
for mid in sorted(int(v) for v in np.unique(am.rotulos) if v):
    try:
        cand, info = sg.candidato(am, mid, sg.params_da_regra(am, mid), substituir=True)
    except ValueError as e:
        print(f"     {am.mineral(mid).nome:12s} — {e}")
        continue
    c = sg.comparar(am.rotulos == mid, cand)
    print(f"     {am.mineral(mid).nome:12s} {info['fonte']:7s} IoU {c['iou']:.3f} Dice {c['dice']:.3f} "
          f"({info['px']} px auto × {c['px_oper']} rotulados)")

print("3. k-means × estado/clusters.npy")
ref_cl = RAIZ / "estado" / "clusters.npy"
if ref_cl.exists() and am.clusters is not None:
    lab, info = sg.kmeans(am, int(am.clusters.max()), 4)
    checar(bool((lab == np.load(ref_cl)).all()), f"k-means idêntico ({(lab != np.load(ref_cl)).sum()} px diferentes)")
else:
    print("     (sem estado/clusters.npy — pulado)")

print("4. gravação textual da config")
texto = Path(fonte.config).read_text(encoding="utf-8")
cfgt = yaml.safe_load(texto)
ok = True
for m in cfgt["minerais"]:
    p = {k: m[k] for k in sg.CHAVES_REGRA if k in m}
    ok &= yaml.safe_load(config_texto.substituir(texto, m["nome"], p)[0]) == cfgt
checar(ok, f"regravar os {len(cfgt['minerais'])} minerais sem mudança = config idêntica")
m = next((x for x in cfgt["minerais"] if x.get("mapas_grupos")), None)
if m:
    p = {k: copy.deepcopy(m[k]) for k in sg.CHAVES_REGRA if k in m}
    c0 = p["mapas_grupos"][0]["cond"][0]
    c0["q" if "q" in c0 else "v"] = round(c0.get("q", c0.get("v", 0.5)) + 0.05, 3)
    novo = config_texto.substituir(texto, m["nome"], p)[0]
    checar(novo.count("#") == texto.count("#"), f"alterar {m['nome']} preserva os {texto.count('#')} comentários")

print("5. editor: desfazer/refazer")
orig = am.rotulos.copy()
ed = Editor(am)
h, w = am.shape
mid = int(np.bincount(am.rotulos[am.rotulos > 0]).argmax())
ed.iniciar("pincel")
ed.aplicar(*capsula((w * .3, h * .3), (w * .4, h * .35), 8, am.shape), mid)
ed.terminar()
ed.forma("poligono", [(w * .1, h * .1), (w * .3, h * .12), (w * .25, h * .3)], "pintar", mid)
ed.forma("elipse", [(w * .5, h * .5), (w * .6, h * .58)], "apagar", mid, filtro_txt=f"{am.elementos[0]}>0.1")
ys, xs = np.nonzero(am.rotulos == mid)
ed.balde(int(xs[0]), int(ys[0]), mid)
ed.pontos([(w * .7, h * .7), (w * .72, h * .7), (w * .71, h * .73)], mid, eps=w * .05)
for op, prm in [("fechar", 2), ("preencher", 0), ("convexo", 0), ("limpar", am.area_min)]:
    ed.morfologia(mid, op, prm)
lab_p, n_p, _i = ed.propagar(mid)
if n_p:
    ed.aceitar_propagacao(lab_p > 0, mid, n_p)
ed.limpar_fora()
final = am.rotulos.copy()
k = 0
while ed.desfazer():
    k += 1
checar(bool((am.rotulos == orig).all()), f"desfazer {k} passos = original")
while ed.refazer():
    pass
checar(bool((am.rotulos == final).all()), "refazer tudo = final")
while ed.desfazer():
    pass

print("6. pacote .mudmap")
with tempfile.TemporaryDirectory() as d:
    arq = Path(d) / "t.mudmap"
    pacote.salvar(am, arq)
    am.rotulos[:10, :10] = mid
    pacote.salvar(am, arq)
    b = pacote.abrir(arq)
    checar(bool((b.rotulos == am.rotulos).all()) and len(b.versoes) == 1, "salvar/abrir + 1 versão anterior guardada")
    am.rotulos[:] = orig

print("7. relatório × relatorio_final.py (mesmos rótulos e config)")
import json  # noqa: E402

import relatorio_final as rf  # noqa: E402
from mudmap_studio.nucleo import exportar_html, relatorio  # noqa: E402

ob = objetos.calcular(am)
t = time.time()
R = relatorio.calcular(am, ob)
r = R.resumo
print(f"     relatório do app em {1000 * (time.time() - t):.0f} ms (a partir dos grãos já separados)")
px = am.pixel_um
cfg_px = common.resolver_escala(cfg, px)
graos = rf.graos_de_rotulos(am.rotulos, cfg_px, am.area_min)
diam = np.array([2 * np.sqrt(a * px * px / np.pi) for _i, a, _c in graos])
cls = np.array([rf.classe_wentworth(d) for d in diam])
um2 = np.array([a * px * px for _i, a, _c in graos])
mdom = np.array([i for i, _a, _c in graos])
nomes = {i: m["nome"] for i, m in enumerate(cfg_px["minerais"], start=1)}
a_mat = {nomes[i]: float((am.rotulos == i).sum() * px * px)
         for i, m in enumerate(cfg_px["minerais"], start=1) if m.get("matriz")}
tot = um2.sum() + sum(a_mat.values())
fr = {c: (um2[cls == c].sum() + (sum(a_mat.values()) if c == "argila" else 0)) / tot
      for c in ("areia", "silte", "argila")}
checar(r["n_graos"] == len(graos), f"nº de grãos = pipeline ({len(graos)})")
checar(max(abs(R.fr[c] - fr[c]) for c in fr) < 1e-9,
       "frações areia/silte/argila = pipeline " + " ".join(f"{c} {100 * fr[c]:.1f}%" for c in fr))
checar((r["d50_um"] is None and not len(diam)) or abs(r["d50_um"] - float(np.median(diam))) < 1e-9,
       f"D50 = pipeline ({r['d50_um']})")
ok = all(r["por_mineral"][nomes[i]]["n_graos"] == int((mdom == i).sum()) and
         abs(r["por_mineral"][nomes[i]]["area_um2"] - um2[mdom == i].sum()) < 1e-6 for i in np.unique(mdom))
ok &= all(abs(r["por_mineral"][n]["area_um2"] - a) < 1e-6 and r["por_mineral"][n].get("matriz") for n, a in a_mat.items())
checar(ok, f"por mineral (nº e área de grãos; matriz inteira: {list(a_mat)}) = pipeline")
ids_p = [i for i in np.unique(am.rotulos) if i > 0]
comp_p = rf.composicao_por_mineral(frac, am.rotulos, cfg["elementos"], ids_p, nomes)
dif = max(abs(r["composicao_frac_cations"][n][e] - round(v, 4)) for n, d in comp_p.items() for e, v in d.items())
checar(dif <= 1.01e-4, f"composição média por mineral = pipeline (dif. máx {dif:.1e})")
id_fsp = next((i for i, m in enumerate(cfg_px["minerais"], start=1)
               if m.get("feldspato") or m["nome"] == "feldspato"), None)
if id_fsp and "Na" in cfg["elementos"] and (am.rotulos == id_fsp).any():
    pts = rf.feldspato_objetos(frac, am.rotulos, cfg["elementos"], id_fsp, am.area_min)
    checar(len(pts) == len(R.fsp) and all(max(abs(a[k] - b[k]) for k in range(3)) < 1e-4 and a[3] == b[3]
                                          for a, b in zip(pts, R.fsp)),
           f"feldspato Na-K-Ca por objeto = pipeline ({len(pts)} objetos)")
else:
    print("     (sem feldspato com Na neste sítio — ternário Na-K-Ca não comparado)")
checar(relatorio.classe_shepard(.8, .1, .1) == "areia" and relatorio.classe_shepard(.3, .3, .4) == "areia-silte-argila"
       and relatorio.classe_shepard(.1, .55, .35) == "silte argiloso" and
       relatorio.classe_shepard(.15, .25, .6) == "argila siltosa", "classes de Shepard (4 casos)")
c1 = R.compacto()
c2 = dict(c1, sitio=f"{relatorio.grupo_sitio(am.sitio)}.9")
ag = relatorio.agregar([c1, c2], "sitio")
checar(len(ag) == 1 and ag[0]["n_campos"] == 2 and ag[0]["n_graos"] == 2 * r["n_graos"] and
       max(abs(ag[0]["fr"][c] - R.fr[c]) for c in fr) < 1e-12, "agregação por sítio soma as áreas (2 campos)")
checar(len(relatorio.agregar([c1, c2], "campo")) == 2, "agregação por campo = 1 linha por .mudmap")
with tempfile.TemporaryDirectory() as d:
    js = json.loads(relatorio.json_resumo(R))
    txt = relatorio.csv_minerais(R, am)
    checar(js["n_graos"] == r["n_graos"] and txt.count("\n") == len(r["por_mineral"]) + 1, "JSON e CSV (minerais)")
    dd, idm = exportar_html.dados(am, ob)
    html = exportar_html.exportar(am, ob, Path(d) / "i.html").read_text(encoding="utf-8")
    checar(dd["meta"]["n_obj"] == ob.n and "__DATA__" not in html and "'graos_bse.png'" not in html and
           int((idm[..., 0].astype(int) + 256 * idm[..., 1].astype(int)).max()) == min(ob.n, 65535),
           f"inspetor HTML único ({len(html) / 1e6:.1f} MB, {dd['meta']['n_obj']} objetos)")
# Na-K-Ca num pacote com Na e feldspato (o sítio ativo pode não ter): mesmas entradas nos dois lados
for arq in sorted((RAIZ / "saida" / "mudmap").glob("*.mudmap")):
    b = pacote.abrir(arq)
    if not (b.tem_na and b.id_feldspato and (b.rotulos == b.id_feldspato).any()):
        continue
    Rb = relatorio.calcular(b, objetos.calcular(b))
    fb = np.dstack(b.mapas).astype(np.float64)
    s = fb.sum(-1, keepdims=True)
    fb = np.divide(fb, s, out=np.zeros_like(fb), where=s > 0)
    pts = rf.feldspato_objetos(fb, b.rotulos, b.elementos, b.id_feldspato, b.area_min)
    checar(len(pts) == len(Rb.fsp) and all(max(abs(p[k] - q[k]) for k in range(3)) < 1e-4 and p[3] == q[3]
                                           for p, q in zip(pts, Rb.fsp)),
           f"feldspato Na-K-Ca por objeto = pipeline ({arq.name}: {len(pts)} objetos)")
    break

print(f"\nRESULTADO: {'OK' if not falhas else 'FALHOU'} ({time.time() - t0:.0f}s)" +
      ("" if not falhas else "\n  - " + "\n  - ".join(falhas)))
sys.exit(1 if falhas else 0)
