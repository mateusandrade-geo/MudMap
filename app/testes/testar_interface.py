"""Teste da interface SEM TELA (offscreen) — todos os modos, em CÓPIAS temporárias.

Gera um .mudmap do sítio ativo numa pasta temporária (nada do projeto é alterado: config,
estado/ e pacotes ficam intactos) e exercita: Inspetor (seleção, comparação, tabela), Camadas
(BSE contorno, Elementos, RGB, Canal + erro), Edição (pincel, polígono c/ filtro, balde, pontos,
propagar c/ revisão, limpeza fora, morfologia, desfazer/refazer), Segmentar (candidato,
parâmetro ao vivo, comparar, commit+desfazer, calibrar, gravar config numa CÓPIA, k-means),
Relatório (recalculado após as edições, destaques, clique no grão, painel cheio, exportações,
comparação por campo/sítio com um 2º .mudmap), volta ao Inspetor (recalcula grãos), salvar com
versão e exportar p/ um estado/ falso.
Capturas PNG em <saida> (default: pasta temporária impressa no fim).

Uso (raiz do repositório):  python app/testes/testar_interface.py [pasta_saida] [--raiz <pasta_do_projeto>]
  --raiz: default = a raiz do repositório; ex.: exemplo (python scripts/gerar_exemplo.py)
"""
import os
import shutil
import sys
import tempfile
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if sys.platform == "win32":
    os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"      # offscreen não acha fontes sozinho no Windows
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app"))
_args = sys.argv[1:]
RAIZ = REPO
if "--raiz" in _args:
    i = _args.index("--raiz")
    RAIZ = Path(_args[i + 1]).resolve()
    del _args[i:i + 2]
OUT = Path(_args[0]) if _args else Path(tempfile.mkdtemp(prefix="mudmap_ui_"))
OUT.mkdir(parents=True, exist_ok=True)

import numpy as np  # noqa: E402
from PyQt6.QtCore import Qt, qInstallMessageHandler  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from mudmap_studio.nucleo import importar, objetos, pacote  # noqa: E402
from mudmap_studio.ui import segmentar as useg, tema  # noqa: E402
from mudmap_studio.ui.comum import fmt  # noqa: E402
from mudmap_studio.ui.janela import JanelaPrincipal  # noqa: E402

qInstallMessageHandler(lambda t, c, m: None if "propagateSizeHints" in m else print("QT:", m, flush=True))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)       # confirma diálogos
useg._DialogoConfig.exec = lambda self: (self.chk.setChecked(self.chk.isEnabled()), QDialog.DialogCode.Accepted)[1]
falhas = []


def checar(cond, msg):
    print(("  OK   " if cond else "  FALHA ") + msg, flush=True)
    if not cond:
        falhas.append(msg)


app = QApplication(sys.argv)
tema.aplicar(app)
j = JanelaPrincipal()
j.resize(1500, 950)
j.show()


def foto(nome):
    j.aguardar_render()
    app.processEvents()
    j.grab().save(str(OUT / f"{nome}.png"))


t0 = time.time()
fonte = next(f for f in importar.listar_sitios(RAIZ) if f.ativo)
arq = OUT / f"teste_{fonte.sitio}.mudmap"
pacote.salvar(importar.importar_sitio(fonte), arq)
am = pacote.abrir(arq)
cfg_copia = OUT / "config_copia.yaml"
shutil.copy(fonte.config, cfg_copia)
am.origem["config"] = str(cfg_copia)
j._carregado((am, objetos.calcular(am)), arq)
j.aguardar_render()
orig = am.rotulos.copy()
ids = {m.nome: m.id for m in am.minerais}
presentes = [int(v) for v in np.unique(am.rotulos) if v]
print(f"sítio {fonte.sitio}: {j.ob.n} objetos, minerais {[am.mineral(i).nome for i in presentes]}")

print("Inspetor")
checar(j.fixado and j.sel_a is not None, "maior grão fixado ao abrir")
oid = int(np.argsort(j.ob.area[1:])[-2]) + 1
x0, y0, x1, y1 = j.ob.bbox[oid]
yy, xx = np.nonzero(j.ob.objid[y0:y1, x0:x1] == oid)
j._clique(int(xx[0] + x0), int(yy[0] + y0), Qt.KeyboardModifier.ShiftModifier)
checar(j.sel_b == ("obj", oid), "⇧clique = grão B (comparação)")
j.b_tab.setChecked(True)
checar(j.tabela.modelo.rowCount() == j.ob.n, "tabela com todos os grãos")
foto("1_inspetor")

print("Camadas")
C = j.camadas
C.seg_estilo.set("contorno"); C._mudou(); foto("2_bse_contorno")
C.set_modo_fundo("elementos"); foto("3_elementos")
C.set_modo_fundo("rgb"); foto("4_rgb")
C.set_modo_fundo("canal"); C.sl_raio.setValue(27); foto("5_canal")
checar(j._visual.fundo == "canal" and not C.erro_canal.isVisible(), "canal suavizado composto")
C.cb_expr.setCurrentText("Mg/Xx"); C._canal_mudou(); j.aguardar_render()
checar(C.erro_canal.isVisible(), "expressão inválida mostra erro")
C.cb_expr.setCurrentText("Si-Mg"); C._canal_mudou(); C.set_modo_fundo("bse"); C.seg_estilo.set("preenchido"); C._mudou()

print("Edição")
j.set_modo("edicao")
Ct, P = j.controle, j.painel_ed
h, w = am.shape
mid = max(presentes, key=lambda i: int((am.rotulos == i).sum()))
P.set_ativo(mid)
j.ferramenta_edicao("pincel")
fy, fx = np.nonzero((am.rotulos == 0) & am.mascara)              # começa num pixel livre
fx0, fy0 = float(fx[len(fx) // 2]), float(fy[len(fy) // 2])
Ct._traco_inicio(fx0, fy0, Qt.KeyboardModifier.NoModifier)
for k in range(20):
    Ct._traco_ponto(fx0 + k * 3, fy0 + k)
Ct._traco_fim()
checar("pincel" in P.msg.text(), "pincel: " + P.msg.text()[:50])
P.seg_acao.set("pintar"); P._acao("pintar"); P.ed_filtro.setText(f"{am.elementos[0]}>0.05")
Ct._forma("poligono", [(w * .6, h * .15), (w * .75, h * .17), (w * .72, h * .32), (w * .58, h * .3)])
checar("polígono" in P.msg.text(), "polígono c/ filtro: " + P.msg.text()[:60])
P.ed_filtro.setText("")
j.ferramenta_edicao("balde")
ys, xs = np.nonzero(am.rotulos == presentes[0])
Ct._clique_ferramenta(int(xs[0]), int(ys[0]), Qt.KeyboardModifier.NoModifier)
j.canvas.pontos = [(w * .85, h * .8), (w * .88, h * .8), (w * .86, h * .84)]
Ct.converter_pontos()
checar("pontos" in P.msg.text(), "pontos → regiões: " + P.msg.text()[:50])
lab, n, info = Ct.editor.propagar(mid)
Ct._proposta_pronta((lab, n, info), mid)
if n:
    Ct._excluir_na_forma("retangulo", [(0, 0), (w * .5, h * .5)])
    foto("6_edicao_proposta")
    Ct.aceitar()
print(f"     propagar: {n} regiões propostas")
Ct.limpar_fora()
Ct.morf("fechar", 2); j.aguardar_render()
Ct.desfazer(); Ct.refazer()
checar(Ct.editor.hist.pos == len(Ct.editor.hist.passos), f"histórico: {P.l_hist.text()}")
foto("7_edicao")

print("Segmentar")
j.set_modo("segmentar")
S, PS = j.seg, j.painel_seg
PS.set_mineral(mid, emitir=True); j.aguardar_render()
checar(S.res is not None and S.res["comp"] is not None, "candidato + comparação: " +
       PS.l_res.text().split("<br>")[1][:60] if "<br>" in PS.l_res.text() else PS.l_res.text()[:80])
PS.seg_visao.set("comparar"); S._desenhar(); foto("8_segmentar_comparar")
antes = am.rotulos.copy()
S.commitar(); j.aguardar_render()
checar("PÓS" in PS.msg.text(), "commit: " + PS.msg.text()[:60])
Ct.desfazer(); j.aguardar_render()
checar(bool((am.rotulos == antes).all()), "desfazer o commit volta ao anterior")
S.calibrar(); j.aguardar_render()
checar(PS.t_cal.isVisible(), "calibrar mostra a regra proposta")
txt0 = cfg_copia.read_text(encoding="utf-8")
S.salvar_config()
txt1 = cfg_copia.read_text(encoding="utf-8")
checar(txt1.count("#") == txt0.count("#") and len(list(OUT.glob("config_copia.yaml.bak_*"))) >= 1,
       "gravar config (cópia): comentários preservados + backup")
if am.clusters is not None:
    ref = am.clusters.copy()
    S.kmeans(); j.aguardar_render(180)
    checar(bool((am.clusters == ref).all()), "k-means pela interface = clusters do pacote")

print("Relatório (vindo de edições: os grãos têm de ser recalculados)")
from PyQt6.QtCore import QSettings  # noqa: E402

from mudmap_studio.nucleo import relatorio  # noqa: E402

lista_antes = QSettings("MudMap", "Studio").value("comparar/arquivos", [])   # restaurada no fim
j.set_modo("relatorio"); j.aguardar_render(120)
R = j.rel.R
ref = relatorio.calcular(am, objetos.calcular(am)).resumo
checar(j.versao_stats == Ct.editor.versao and R is not None and R.resumo["n_graos"] == ref["n_graos"] and
       R.resumo["fracoes_area"] == ref["fracoes_area"],
       f"relatório em dia com as edições: {R.resumo['n_graos']} grãos, {R.resumo['fracoes_area']}, "
       f"{R.resumo['classe_shepard']}")
foto("10_relatorio")
Pr = j.painel_rel
j.rel.destacar(("classe", 1 if (R.classe == 1).any() else 0))
checar("grãos" in j.lbl_destaque.text() and "rel" in j.canvas._camadas, "destaque por classe: " + j.lbl_destaque.text()[:50])
H = Pr.g["hist"]
if H.bordas.size:
    j.rel.destacar(("bins", float(H.bordas[0]), float(H.bordas[-1])))
    checar(f"{fmt(R.resumo['n_graos'])} grãos" in j.lbl_destaque.text(), "destaque de todas as barras = todos os grãos")
j.rel.destacar(("mineral", mid)); j.aguardar_render()
checar(Pr.g["tab"].sel == ("mineral", mid) and "rel" in j.canvas._camadas, "linha da tabela destaca o mineral")
oid = int(R.gid[np.argmax(R.um2)]) if R.gid.size else 0
if oid:
    yy, xx = np.nonzero(j.ob.objid == oid)
    j._clique(int(xx[0]), int(yy[0]), Qt.KeyboardModifier.NoModifier)
    checar(H.marca is not None and abs(H.marca - float(j.ob.diam[oid])) < 1e-9, "clique no grão marca o histograma")
foto("11_relatorio_destaque")
Pr.b_cheio.setChecked(True); app.processEvents()
checar(not j.meio.isVisible(), "painel cheio esconde o canvas"); foto("12_relatorio_cheio")
exp = {}
for k, ext in (("png", "png"), ("svg", "svg"), ("json", "json"), ("csv_minerais", "csv"), ("csv_graos", "csv"),
               ("html", "html")):
    c = j.rel.exportar(k, OUT / f"rel_{k}.{ext}")
    j.aguardar_render()                                   # CSV de grãos e HTML rodam em segundo plano
    exp[k] = c is not None and c.exists() and c.stat().st_size > 0
checar(all(exp.values()), "exportar " + " ".join(f"{k}={'ok' if v else 'FALHA'}" for k, v in exp.items()))
b2 = pacote.abrir(arq)
b2.sitio = f"{relatorio.grupo_sitio(am.sitio)}.9"
arq2 = OUT / f"teste_{b2.sitio}.mudmap"
pacote.salvar(b2, arq2)
j.rel.adicionar([str(arq), str(arq2)])
t1 = time.time()
while j.rel.ocupado() and time.time() - t1 < 120:
    app.processEvents(); time.sleep(0.02)
Pr.abas.botoes["comparar"].click(); Pr.seg_por.botoes["sitio"].click(); app.processEvents()
tab = Pr.gc["tab"].linhas
ag = relatorio.agregar(j.rel._compactos(), "sitio")
checar(len(tab) == 1 and len(ag) == 1 and ag[0]["n_campos"] == 2 and
       ag[0]["n_graos"] == sum(c["n_graos"] for c in j.rel._compactos()),
       f"comparação por sítio: 1 linha ({tab[0][0][0] if tab else '—'}) com 2 campos (aberto ao vivo + arquivo)")
foto("13_comparar_sitio")
Pr.seg_por.botoes["campo"].click(); app.processEvents()
checar(len(Pr.gc["tab"].linhas) == 2, "comparação por campo: 2 linhas")
for k, ext in (("cmp_png", "png"), ("cmp_csv", "csv"), ("cmp_json", "json")):
    c = j.rel.exportar(k, OUT / f"{k}.{ext}")
    checar(c is not None and c.stat().st_size > 0, f"exportar {k}")
Pr.abas.botoes["amostra"].click()
QSettings("MudMap", "Studio").setValue("comparar/arquivos", lista_antes or [])
j.rel.arquivos = [c for c in j.rel.arquivos if c in (lista_antes or [])]

print("Volta ao Inspetor, salvar e exportar")
j.set_modo("inspetor"); j.aguardar_render()
checar(j.meio.isVisible() and j.camadas.isVisible(), "sair do Relatório devolve o canvas")
checar(j.versao_stats == Ct.editor.versao, f"grãos recalculados ({j.ob.n} objetos)")
foto("9_inspetor_recalc")
j._salvar_sincrono()
b = pacote.abrir(arq)
checar(bool((b.rotulos == am.rotulos).all()) and len(b.versoes) >= 1 and len(b.log_edicoes) > 0,
       f"salvo: rótulos iguais, {len(b.versoes)} versão(ões), {len(b.log_edicoes)} edições registradas")
est = OUT / "estado_falso"
est.mkdir(exist_ok=True)
np.save(est / "rotulos.npy", orig.astype(np.int64))
(est / "progresso.json").write_text("[]", encoding="utf-8")
am.origem["estado"] = str(est)
j.exportar_estado()
checar(bool((np.load(est / "rotulos.npy") == am.rotulos).all()) and
       bool((np.load(est / "rotulos_prev.npy") == orig).all()), "exportar: rótulos gravados + backup = original")

print(f"\nRESULTADO: {'OK' if not falhas else 'FALHOU'} ({time.time() - t0:.0f}s) · capturas em {OUT}" +
      ("" if not falhas else "\n  - " + "\n  - ".join(falhas)))
sys.exit(1 if falhas else 0)
