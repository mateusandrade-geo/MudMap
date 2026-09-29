"""Modo Relatório: painel (abas Amostra | Comparar), cálculo após cada edição, destaque no canvas,
exportações (PNG/SVG/JSON/CSV/inspetor HTML) e comparação de vários .mudmap por campo ou por sítio.

O relatório sai de nucleo/relatorio.py (= scripts/relatorio_final.py) e é refeito sempre que os
grãos são recalculados (a janela chama atualizar() ao voltar de uma edição).
"""
import traceback
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QSettings, QStandardPaths, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QImage
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QStackedWidget,
                             QToolButton, QVBoxLayout, QWidget)

from .. import __version__
from ..nucleo import exportar_html, relatorio
from ..nucleo.render import hex_rgb
from . import icones, tema
from .comum import Segmentado, botao, fmt, mudo, rolagem, sobreposicao
from .dialogos import Servico
from .graficos import (PAL, Blocos, HistogramaDiametros, Imagem, MapaCalor, Tabela, TernarioNaKCa,
                       TernarioShepard, exportar_png, exportar_svg)

LARGURA_FIG = 1400
COLS_MIN = [("Mineral", 2.2, "e"), ("Grãos", 1.0, "d"), ("% área", 1.0, "d"), ("D50 µm", 1.0, "d"),
            ("Finos µm²", 1.2, "d"), ("% amostra", 1.1, "d")]
COLS_CMP = [("Campo", 1.6, "e"), ("Grãos", 1.0, "d"), ("D50 µm", 1.0, "d"), ("Areia %", 0.9, "d"),
            ("Silte %", 0.9, "d"), ("Argila %", 0.9, "d"), ("Matriz %", 0.9, "d"), ("Shepard", 1.9, "e")]


def _n(x, d=2):
    return "—" if x is None else fmt(x, d)


# ======================================= construção dos gráficos =======================================
def graficos_amostra():
    return {"blocos": Blocos(), "shep": TernarioShepard(), "fsp": TernarioNaKCa(), "hist": HistogramaDiametros(),
            "comp": MapaCalor(), "tab": Tabela(COLS_MIN)}


def ordem_minerais(am, ob):
    return sorted((m for m in am.minerais if m.id < len(ob.min_npx) and ob.min_npx[m.id]),
                  key=lambda m: -int(ob.min_npx[m.id]))


def preencher_amostra(g, am, ob, R):
    r = R.resumo
    res = r["resolucao"]
    itens = [("Grãos ≥ area_min", fmt(r["n_graos"])),
             ("D50 · por nº de grãos", f"{_n(r['d50_um'])} µm" if r["d50_um"] else "—"),
             ("Classe de Shepard", r["classe_shepard"] or "—")]
    if R.ids_matriz:
        itens.append(("Matriz → argila", f"{fmt(r['matriz_na_argila']['pct_area'], 1)} %"))
    else:
        itens.append(("Área de grãos", f"{fmt(R.tot, 0)} µm²"))
    aviso = "" if res["argila_medida"] else (f"Argila não resolvida: d_min {fmt(res['d_min_um'], 2)} µm ≥ 3,9 µm "
                                             "— o ponto fica enviesado para silte.")
    g["blocos"].definir(itens, aviso)
    g["shep"].definir([{"rotulo": am.titulo, "fr": (R.fr["areia"], R.fr["silte"], R.fr["argila"])}],
                      leitura=(R.fr["areia"], R.fr["silte"], R.fr["argila"]))
    fsp_m = am.mineral(R.id_fsp) if R.id_fsp else None
    vazio = ("sem mapa de Na nesta amostra — ternário indisponível" if not am.tem_na else
             "sem feldspato na config" if fsp_m is None else "sem objetos de feldspato ≥ area_min")
    g["fsp"].definir(R.fsp, fsp_m.cor if fsp_m else "#e8846b", vazio)
    g["hist"].definir(R.diam, R.um2, R.d_min, r["d50_um"])
    ms = ordem_minerais(am, ob)
    nome = lambda m: m.nome.replace("_", " ")
    g["comp"].definir([(nome(m), m.cor, ("mineral", m.id)) for m in ms], am.elementos,
                      np.array([ob.min_frac[m.id] for m in ms], np.float64).reshape(len(ms), len(am.elementos)))
    linhas = []
    for m in ms:
        s = r["por_mineral"].get(m.nome, {})
        mat = bool(s.get("matriz"))
        linhas.append(([nome(m) + (" (matriz)" if mat else ""), "matriz" if mat else fmt(s.get("n_graos", 0)),
                        fmt(s.get("pct_area", 0), 1), _n(s.get("d50_um")),
                        "—" if mat else fmt(s.get("area_finos_um2", 0), 1), fmt(s.get("pct_amostra", 0), 1)],
                       m.cor, ("mineral", m.id)))
    g["tab"].definir(linhas, "% área = grãos ≥ area_min + matriz inteira (base do ternário) · "
                             "finos = objetos < area_min (cimento)")


def graficos_comparacao():
    return {"shep": TernarioShepard(), "tab": Tabela(COLS_CMP),
            "min": MapaCalor(unidade="% da área (grãos + matriz)", limiar=10, casas=0)}


def preencher_comparacao(g, linhas, por, campos=None):
    """linhas = relatorio.agregar(...); campos = agregar(..., 'campo') p/ os satélites na visão por sítio."""
    grupos = []
    varias = len({l["grupo"][0] for l in linhas}) > 1
    for l in linhas:
        if l["grupo"] not in [k for k, _r in grupos]:
            grupos.append((l["grupo"], (f"{l['grupo'][0]} · " if varias else "") + f"sítio {l['grupo'][1]}"))
    grupos.sort(key=lambda kv: (kv[0][0], relatorio._chave_natural(kv[0][1])))
    pts = []
    for l in linhas:
        pts.append({"rotulo": l["rotulo"], "fr": (l["fr"]["areia"], l["fr"]["silte"], l["fr"]["argila"]),
                    "grupo": l["grupo"], "dado": None,
                    "extra": f"{fmt(l['n_graos'])} grãos · D50 {_n(l['d50_um'])} µm"
                             + (f"<br>campos: {' + '.join(l['campos'])}" if por == "sitio" else "")})
    if por == "sitio" and campos:
        pais = {l["grupo"]: i for i, l in enumerate(linhas)}
        for c in campos:
            if linhas[pais[c["grupo"]]]["n_campos"] > 1:
                pts.append({"rotulo": c["rotulo"], "fr": (c["fr"]["areia"], c["fr"]["silte"], c["fr"]["argila"]),
                            "grupo": c["grupo"], "sat": True, "pai": pais[c["grupo"]]})
    g["shep"].definir(pts, grupos)
    g["tab"].colunas[0] = ("Sítio" if por == "sitio" else "Campo", 1.6, "e")
    g["tab"].definir([([l["rotulo"], fmt(l["n_graos"]), _n(l["d50_um"]), fmt(100 * l["fr"]["areia"], 1),
                        fmt(100 * l["fr"]["silte"], 1), fmt(100 * l["fr"]["argila"], 1), fmt(l["matriz_pct"], 1),
                        l["classe_shepard"] or "—"], None, None) for l in linhas],
                     "; ".join(f"{l['rotulo']} = {' + '.join(l['campos'])}" for l in linhas if l["n_campos"] > 1)
                     if por == "sitio" else "")
    tot = {}
    for l in linhas:
        for n, v in l["pct_mineral"].items():
            tot[n] = tot.get(n, 0.0) + v
    mins = [n for n in sorted(tot, key=lambda n: -tot[n]) if tot[n] > 0]
    g["min"].definir([(l["rotulo"], None, None) for l in linhas], [n.replace("_", " ") for n in mins],
                     np.array([[l["pct_mineral"].get(n, 0.0) for n in mins] for l in linhas], np.float64).reshape(
                         len(linhas), len(mins)))


# ======================================= painel =======================================
class _Cartao(QFrame):
    def __init__(self, titulo, grafico, sub=""):
        super().__init__()
        self.setObjectName("cartao")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(4)
        t = QLabel(titulo.upper())
        t.setObjectName("secao")
        t.setStyleSheet("padding-top: 0;")
        v.addWidget(t)
        self.sub = mudo(sub, 8)
        self.sub.setVisible(bool(sub))
        v.addWidget(self.sub)
        v.addSpacing(4)
        v.addWidget(grafico)
        v.addStretch(1)                  # cartão esticado pela linha da grade: conteúdo fica no alto
        self.grafico = grafico

    def set_sub(self, s):
        self.sub.setText(s)
        self.sub.setVisible(bool(s))


class _Grade(QWidget):
    """Cartões em 1 coluna (painel estreito) ou 2 (painel cheio); span 2 ocupa a linha."""

    def __init__(self):
        super().__init__()
        self.itens = []
        self.g = QGridLayout(self)
        self.g.setContentsMargins(12, 10, 12, 14)
        self.g.setSpacing(10)
        self._cols = None

    def add(self, w, span=1):
        self.itens.append((w, span))
        self._cols = None
        self._arrumar()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrumar()

    def _arrumar(self):
        cols = 2 if self.width() >= 940 else 1
        if cols == self._cols:
            return
        self._cols = cols
        for w, _s in self.itens:
            self.g.removeWidget(w)
        for k in range(self.g.rowCount()):
            self.g.setRowStretch(k, 0)
        r = c = 0
        for w, s in self.itens:
            s = min(s, cols)
            if c + s > cols:
                r, c = r + 1, 0
            self.g.addWidget(w, r, c, 1, s)
            c += s
            if c >= cols:
                r, c = r + 1, 0
        for k in range(2):
            self.g.setColumnStretch(k, 1 if k < cols else 0)
        self.g.setRowStretch(r + 1, 1)


class PainelRelatorio(QWidget):
    destacar = pyqtSignal(object)
    exportar = pyqtSignal(str)
    cheio = pyqtSignal(bool)
    comparar = pyqtSignal(str)          # adicionar | pasta | remover | limpar
    porMudou = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("painel")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        cab = QWidget()
        cab.setObjectName("painel")
        h = QHBoxLayout(cab)
        h.setContentsMargins(12, 7, 8, 7)
        h.setSpacing(8)
        self.abas = Segmentado([("amostra", "Amostra"), ("comparar", "Comparar")])
        self.abas.layout().takeAt(self.abas.layout().count() - 1)     # sem o stretch interno
        for b in self.abas.botoes.values():
            b.setMinimumWidth(b.sizeHint().width())                  # nunca espremer o texto das abas
        self.abas.escolhido.connect(self._aba)
        h.addWidget(self.abas)
        self.pill = QLabel()
        self.pill.setObjectName("pillAcento")
        h.addWidget(self.pill)
        h.addStretch()
        self.b_exp = QToolButton()
        self.b_exp.setIcon(icones.icone("exportar", tam=18))
        self.b_exp.setText(" Exportar")
        self.b_exp.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_exp.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self)
        self.menu.aboutToShow.connect(self._montar_menu)
        self.b_exp.setMenu(self.menu)
        h.addWidget(self.b_exp)
        self.b_cheio = QToolButton()
        self.b_cheio.setIcon(icones.icone("ajustar", tam=18))
        self.b_cheio.setCheckable(True)
        self.b_cheio.setToolTip("Painel cheio: esconde o canvas (os gráficos passam a 2 colunas)")
        self.b_cheio.toggled.connect(self.cheio.emit)
        h.addWidget(self.b_cheio)
        v.addWidget(cab)
        linha = QFrame()
        linha.setObjectName("linha")
        v.addWidget(linha)
        self.pilha = QStackedWidget()
        v.addWidget(self.pilha, 1)
        self.fundo_escuro = QSettings("MudMap", "Studio").value("relatorio/fundo_escuro", False, type=bool)
        self._montar_amostra()
        self._montar_comparar()

    # ---------- aba Amostra ----------
    def _montar_amostra(self):
        self.g = graficos_amostra()
        grade = _Grade()
        self.c_blocos = _Cartao("Resumo", self.g["blocos"])
        self.c_shep = _Cartao("Ternário granulométrico (Shepard)", self.g["shep"],
                              "por área de grão · matriz inteira na argila · cimento (< area_min) fora · "
                              "clique numa classe destaca os grãos")
        self.c_fsp = _Cartao("Feldspato — ternário Na-K-Ca", self.g["fsp"],
                             "por objeto ≥ area_min · raio ∝ √área · clique seleciona o grão")
        self.c_hist = _Cartao("Diâmetros (ponderados pela área)", self.g["hist"],
                              "% da área de grãos por classe de diâmetro · clique ou arraste sobre as barras "
                              "para destacar esses grãos · clique fora limpa")
        self.c_comp = _Cartao("Composição média por mineral", self.g["comp"],
                              "fração de cátions de todos os pixels do mineral · clique na linha destaca")
        self.c_tab = _Cartao("Por mineral", self.g["tab"])
        for c, s in ((self.c_blocos, 2), (self.c_shep, 1), (self.c_fsp, 1), (self.c_hist, 2),
                     (self.c_comp, 1), (self.c_tab, 1)):
            grade.add(c, s)
        for k in ("shep", "fsp", "hist", "comp", "tab"):
            self.g[k].ativado.connect(self.destacar.emit)
        self.pilha.addWidget(rolagem(grade))

    def mostrar(self, am, ob, R):
        preencher_amostra(self.g, am, ob, R)
        fov = min(am.fov_um)
        self.c_shep.set_sub(self.c_shep.sub.text().split(" · FOV")[0] +
                            (f" · FOV {fmt(fov, 0)} µm: grãos de areia (≥ 62,5 µm) podem não caber inteiros"
                             if fov < 625 else ""))
        self.limpar_selecao()
        self.set_estado("em dia")

    def set_estado(self, s):
        self.pill.setText(s)

    def limpar_selecao(self):
        for k in ("shep", "fsp", "hist", "comp", "tab"):
            g = self.g[k]
            g.sel = None
            if k == "hist":
                g.marca = None
            g.update()

    def marcar(self, am, ob, sel):
        """Reverso: grão clicado no canvas -> marca no histograma, na tabela, no mapa e no Na-K-Ca."""
        self.limpar_selecao()
        if sel is None:
            return
        tipo, i = sel
        mid = int(ob.mineral[i]) if tipo == "obj" else int(i)
        self.g["tab"].sel = self.g["comp"].sel = ("mineral", mid)
        if tipo == "obj":
            self.g["hist"].marca = float(ob.diam[i]) if not (ob.sub[i] or ob.matriz[i]) else None
            self.g["fsp"].sel = int(i)
        for k in ("hist", "fsp", "comp", "tab"):
            self.g[k].update()

    # ---------- aba Comparar ----------
    def _montar_comparar(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        topo = QWidget()
        tv = QVBoxLayout(topo)
        tv.setContentsMargins(14, 10, 14, 4)
        tv.setSpacing(6)
        tv.addWidget(mudo("Cada .mudmap é um campo (ex.: 1.1). Por sítio, os campos do mesmo sítio "
                          "(1.1 + 1.2 → sítio 1) são somados pela área real em µm², sem média de porcentagens. "
                          "A amostra aberta entra com as edições atuais.", 8.5))
        hb = QHBoxLayout()
        hb.setSpacing(6)
        for rot, dica, ic, acao in (("Adicionar .mudmap", "Escolher arquivos .mudmap", "abrir", "adicionar"),
                                    ("Pasta", "Todos os .mudmap de uma pasta (e subpastas)", "importar", "pasta"),
                                    ("Remover", "Remover os selecionados da lista", "remover", "remover"),
                                    ("Limpar", "Esvaziar a lista", "limpar", "limpar")):
            b = botao(" " + rot, dica, ic)
            b.clicked.connect(lambda _c, a=acao: self.comparar.emit(a))
            hb.addWidget(b)
        hb.addStretch()
        tv.addLayout(hb)
        hp = QHBoxLayout()
        hp.addWidget(mudo("Agrupar", 8.5))
        self.seg_por = Segmentado([("campo", "por campo"), ("sitio", "por sítio")],
                                  QSettings("MudMap", "Studio").value("comparar/por", "sitio"))
        self.seg_por.escolhido.connect(self.porMudou.emit)
        hp.addWidget(self.seg_por, 1)
        tv.addLayout(hp)
        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lista.setMaximumHeight(150)
        self.lista.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tv.addWidget(self.lista)
        v.addWidget(topo)
        self.gc = graficos_comparacao()
        grade = _Grade()
        self.cc_shep = _Cartao("Ternário granulométrico — comparação", self.gc["shep"],
                               "cor e forma = sítio · rótulo = campo/sítio · passe o mouse para os valores")
        self.cc_tab = _Cartao("Tabela comparativa", self.gc["tab"])
        self.cc_min = _Cartao("% da área por mineral", self.gc["min"],
                              "grãos ≥ area_min + matriz inteira (a mesma base do ternário)")
        grade.add(self.cc_shep, 1)
        grade.add(self.cc_min, 1)
        grade.add(self.cc_tab, 2)
        v.addWidget(grade, 1)
        self.pilha.addWidget(rolagem(w))

    def mostrar_comparacao(self, linhas, por, campos):
        preencher_comparacao(self.gc, linhas, por, campos)
        n = len(linhas)
        self.cc_shep.set_sub("cor e forma = sítio · rótulo = " + ("sítio (pontos pequenos = campos)" if por == "sitio"
                                                                 else "campo") +
                             ("" if n else " · adicione .mudmap à lista") +
                             (" · mais de 3 sítios: a cor não distingue, use forma e rótulo"
                              if len({l['grupo'] for l in linhas}) > 3 else ""))

    def set_lista(self, entradas):
        """entradas: [(texto, dica, chave)]"""
        sel = {it.data(256) for it in self.lista.selectedItems()}
        self.lista.clear()
        for txt, dica, chave in entradas:
            it = QListWidgetItem(txt)
            it.setToolTip(dica)
            it.setData(256, chave)
            self.lista.addItem(it)
            it.setSelected(chave in sel)

    def selecionados(self):
        return [it.data(256) for it in self.lista.selectedItems()]

    # ---------- abas e menu ----------
    def _aba(self, a):
        self.pilha.setCurrentIndex(0 if a == "amostra" else 1)

    def aba(self):
        return self.abas.valor()

    def _montar_menu(self):
        m = self.menu
        m.clear()
        if self.aba() == "amostra":
            itens = [("png", "Painel da amostra (PNG)…"), ("svg", "Painel da amostra (SVG vetorial)…"), None,
                     ("json", "Resumo (JSON)…"), ("csv_minerais", "Tabela por mineral (CSV)…"),
                     ("csv_graos", "Todos os grãos (CSV)…"), None, ("html", "Inspetor HTML (arquivo único)…")]
        else:
            itens = [("cmp_png", "Comparação (PNG)…"), ("cmp_svg", "Comparação (SVG vetorial)…"), None,
                     ("cmp_csv", "Comparação (CSV)…"), ("cmp_json", "Comparação (JSON)…")]
        for it in itens:
            if it is None:
                m.addSeparator()
                continue
            a = QAction(it[1], m)
            a.triggered.connect(lambda _c, k=it[0]: self.exportar.emit(k))
            m.addAction(a)
        m.addSeparator()
        a = QAction("Figuras com fundo escuro", m)
        a.setCheckable(True)
        a.setChecked(self.fundo_escuro)
        a.toggled.connect(self._fundo)
        m.addAction(a)

    def _fundo(self, on):
        self.fundo_escuro = bool(on)
        QSettings("MudMap", "Studio").setValue("relatorio/fundo_escuro", self.fundo_escuro)


# ======================================= controle =======================================
class ControleRelatorio(QObject):
    def __init__(self, janela):
        super().__init__(janela)
        self.j = janela
        self.p = janela.painel_rel
        self.R = None
        self._chave = None
        self._destaque = None
        self.cfg = QSettings("MudMap", "Studio")
        lst = self.cfg.value("comparar/arquivos", []) or []
        self.arquivos = [lst] if isinstance(lst, str) else list(lst)
        self.info = {}              # caminho -> {"estado", "compacto", "msg", "sitio", "prog"}
        self.cache_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        self.servico = Servico(self)            # resume os .mudmap da lista, um por vez (fila)
        self.p.destacar.connect(self.destacar)
        self.p.exportar.connect(lambda k: self.exportar(k))
        self.p.comparar.connect(self._acao_comparar)
        self.p.porMudou.connect(self._por)
        self.p.cheio.connect(self.j.painel_cheio)
        for c in self.arquivos:
            self._enfileirar(c)
        self._lista()

    def parar(self):
        self.servico.parar()

    @property
    def am(self):
        return self.j.am

    @property
    def ob(self):
        return self.j.ob

    # ---------- ciclo ----------
    def definir(self, am):
        self.R, self._chave, self._destaque = None, None, None
        self._lista()

    def entrar(self):
        """Janela garante que os grãos estão em dia antes de chamar."""
        chave = (id(self.am), id(self.ob))
        if self.R is None or chave != self._chave:
            self.atualizar()
        self.j.set_destaque_rel(None)

    def sair(self):
        self._destaque = None
        self.j.set_destaque_rel(None)
        self.p.limpar_selecao()
        if self.p.b_cheio.isChecked():
            self.p.b_cheio.setChecked(False)

    def atualizar(self):
        if self.am is None or self.ob is None:
            return
        self.R = relatorio.calcular(self.am, self.ob)
        self._chave = (id(self.am), id(self.ob))
        self.p.mostrar(self.am, self.ob, self.R)
        self._comparacao()

    # ---------- destaque no canvas ----------
    def destacar(self, dado):
        am, ob, R = self.am, self.ob, self.R
        if am is None or R is None:
            return
        self._destaque = dado
        if dado is None:
            self.j.set_destaque_rel(None)
            self.p.limpar_selecao()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            tipo = dado[0]
            extra = None
            if tipo == "obj":
                oid = int(dado[1])
                self.j.selecionar_objeto_rel(oid)
                self.p.marcar(am, ob, ("obj", oid))
                return
            if tipo == "classe":
                k = int(dado[1])
                ids = R.gid[R.classe == k]
                if k == 0 and R.ids_matriz:
                    extra = np.isin(am.rotulos, R.ids_matriz)
                desc = f"{fmt(ids.size)} grãos de {('argila', 'silte', 'areia')[k]}" + \
                       (" + matriz" if extra is not None else "")
            elif tipo == "bins":
                lo, hi = dado[1], dado[2]
                ids = R.gid[(R.diam >= lo) & (R.diam < hi)]
                desc = f"{fmt(ids.size)} grãos de {fmt(lo, 2)} a {fmt(hi, 2)} µm"
            elif tipo == "mineral":
                ids = np.zeros(0, np.int64)
                extra = am.rotulos == int(dado[1])
                m = am.mineral(int(dado[1]))
                desc = f"{m.nome.replace('_', ' ') if m else dado[1]} (todos os pixels)"
                self.p.limpar_selecao()
                self.p.g["tab"].sel = self.p.g["comp"].sel = dado
                self.p.g["tab"].update()
                self.p.g["comp"].update()
            else:
                return
            lut = np.zeros(ob.n + 1, bool)
            lut[ids] = True
            mask = lut[ob.objid]
            if extra is not None:
                mask |= extra
            s = sobreposicao(mask, cor=hex_rgb(tema.C["selA"]), alfa=110)
            self.j.set_destaque_rel(s, desc if s else f"{desc} — nada para destacar")
        finally:
            QApplication.restoreOverrideCursor()

    def clique_canvas(self, sel):
        self.p.marcar(self.am, self.ob, sel)

    # ---------- exportações ----------
    def _destino(self, sufixo, filtro):
        am = self.am
        base = Path(am.caminho).parent if am and am.caminho else Path(self.j._dir_inicial())
        nome = f"{am.amostra}_{am.sitio}_{sufixo}" if am else f"comparacao_{sufixo}"
        c, _ = QFileDialog.getSaveFileName(self.j, "Exportar", str(base / nome), filtro)
        return Path(c) if c else None

    def _imagem_canvas(self):
        niv = self.j.canvas._niveis
        if not niv:
            return None
        img = next((im for im, _f in niv if im.width() <= 1400), niv[-1][0])
        if img.width() > 1400:
            img = img.scaledToWidth(1400, Qt.TransformationMode.SmoothTransformation)
        return QImage(img)

    def blocos_amostra(self):
        am, ob, R = self.am, self.ob, self.R
        g = graficos_amostra()
        preencher_amostra(g, am, ob, R)
        blocos = [("", g["blocos"], 2)]
        img = self._imagem_canvas()
        if img is not None:
            blocos.append(("Imagem (camadas como no canvas)",
                           Imagem(img, [(m.nome.replace("_", " "), m.cor) for m in ordem_minerais(am, ob)]), 1))
        blocos += [("Ternário granulométrico (Shepard)", g["shep"], 1), ("Diâmetros (ponderados pela área)", g["hist"], 2),
                   ("Feldspato — Na-K-Ca por objeto", g["fsp"], 1), ("Composição média (fração de cátions)", g["comp"], 1),
                   ("Por mineral", g["tab"], 2)]
        r = R.resumo
        sub = (f"{fmt(am.fov_um[0], 0)} × {fmt(am.fov_um[1], 0)} µm · pixel {fmt(am.pixel_um, 4)} µm · area_min "
               f"{am.area_min} px (d_min {fmt(r['resolucao']['d_min_um'], 2)} µm) · MudMap Studio {__version__}")
        return f"Relatório — {am.titulo}", sub, blocos

    def blocos_comparacao(self):
        por = self.p.seg_por.valor()
        comp = self._compactos()
        g = graficos_comparacao()
        preencher_comparacao(g, relatorio.agregar(comp, por), por, relatorio.agregar(comp, "campo"))
        tit = "Comparação " + ("por sítio" if por == "sitio" else "por campo")
        sub = f"{len(comp)} campos · áreas somadas em µm² · MudMap Studio {__version__}"
        return tit, sub, [("Ternário granulométrico (Shepard)", g["shep"], 1),
                          ("% da área por mineral", g["min"], 1), ("Tabela comparativa", g["tab"], 2)]

    def exportar(self, tipo, caminho=None):
        am = self.am
        if self.j._ocupado:
            return None
        if tipo.startswith("cmp_"):
            if not self._compactos():
                QMessageBox.information(self.j, "Exportar", "A comparação está vazia.")
                return None
        elif am is None or self.R is None:
            return None
        ext = {"png": "png", "svg": "svg", "json": "json", "csv_minerais": "csv", "csv_graos": "csv", "html": "html",
               "cmp_png": "png", "cmp_svg": "svg", "cmp_csv": "csv", "cmp_json": "json"}[tipo]
        suf = {"png": "relatorio.png", "svg": "relatorio.svg", "json": "relatorio.json",
               "csv_minerais": "minerais.csv", "csv_graos": "graos.csv", "html": "inspetor.html",
               "cmp_png": "comparacao.png", "cmp_svg": "comparacao.svg", "cmp_csv": "comparacao.csv",
               "cmp_json": "comparacao.json"}[tipo]
        if caminho is None:
            caminho = self._destino(suf, f"{ext.upper()} (*.{ext})")
            if caminho is None:
                return None
        caminho = Path(caminho)
        pal = PAL["escuro" if self.p.fundo_escuro else "claro"]
        if tipo in ("csv_graos", "html"):              # pesados em 4096² (segundos): em segundo plano
            ob = self.ob

            def fazer(prog):
                if tipo == "html":
                    exportar_html.exportar(am, ob, caminho, prog)
                else:
                    caminho.write_text(relatorio.csv_graos(ob, am), encoding="utf-8")
                return caminho
            self.j._rodar(f"Exportando {caminho.name}", fazer,
                          lambda c: self.j.st_msg.setText(f"Exportado: {Path(c).name}"))
            return caminho
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if tipo in ("png", "svg", "cmp_png", "cmp_svg"):
                tit, sub, blocos = self.blocos_amostra() if not tipo.startswith("cmp_") else self.blocos_comparacao()
                (exportar_png if ext == "png" else exportar_svg)(caminho, LARGURA_FIG, pal, tit, sub, blocos)
            elif tipo == "json":
                caminho.write_text(relatorio.json_resumo(self.R, __version__), encoding="utf-8")
            elif tipo == "csv_minerais":
                caminho.write_text(relatorio.csv_minerais(self.R, am), encoding="utf-8")
            else:
                por = self.p.seg_por.valor()
                linhas = relatorio.agregar(self._compactos(), por)
                txt = (relatorio.csv_comparacao(linhas, por) if tipo == "cmp_csv"
                       else relatorio.json_comparacao(linhas, por, __version__))
                caminho.write_text(txt, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            box = QMessageBox(QMessageBox.Icon.Warning, "Exportar", f"Não foi possível exportar: {e}", parent=self.j)
            box.setDetailedText(traceback.format_exc())
            box.exec()
            return None
        QApplication.restoreOverrideCursor()
        self.j.st_msg.setText(f"Exportado: {caminho.name}")
        return caminho

    # ---------- comparação ----------
    def _enfileirar(self, caminho):
        if not Path(caminho).exists():
            self.info[caminho] = {"estado": "erro", "msg": "arquivo não encontrado"}
            return
        try:
            am_, sit = relatorio.sitio_do_arquivo(caminho)
        except Exception:  # noqa: BLE001
            am_, sit = "?", "?"
        self.info[caminho] = {"estado": "fila", "sitio": sit, "amostra": am_}
        cache = self.cache_dir

        def fazer(prog):
            if caminho not in self.arquivos:              # removido da lista enquanto esperava
                return None
            return relatorio.resumo_de_arquivo(caminho, prog, cache)
        self.servico.pedir(fazer, lambda comp: self._pronto(caminho, comp),
                           lambda curta, _det: self._falhou(caminho, curta),
                           lambda f, _m: self._progresso(caminho, f))

    def _progresso(self, c, f):
        if c in self.info:
            self.info[c].update(estado="calc", prog=f)
            self._lista()

    def _pronto(self, c, comp):
        if c in self.info and comp is not None:
            self.info[c].update(estado="ok", compacto=comp)
        self._lista()
        self._comparacao()

    def _falhou(self, c, msg):
        if c in self.info:
            self.info[c].update(estado="erro", msg=msg)
        self._lista()

    def ocupado(self):
        return self.servico.ocupado

    def _salvar_lista(self):
        self.cfg.setValue("comparar/arquivos", self.arquivos)

    def adicionar(self, caminhos):
        for c in caminhos:
            c = str(Path(c).resolve())
            if c not in self.arquivos:
                self.arquivos.append(c)
                self._enfileirar(c)
        self._salvar_lista()
        self._lista()
        self._comparacao()

    def _acao_comparar(self, acao):
        if acao == "adicionar":
            cs, _ = QFileDialog.getOpenFileNames(self.j, "Adicionar à comparação", self.j._dir_inicial(),
                                                 "Pacote MudMap (*.mudmap)")
            self.adicionar(cs)
        elif acao == "pasta":
            d = QFileDialog.getExistingDirectory(self.j, "Pasta com .mudmap", self.j._dir_inicial())
            if d:
                self.adicionar(sorted(str(p) for p in Path(d).rglob("*.mudmap"))[:200])
        elif acao == "remover":
            fora = set(self.p.selecionados())
            self.arquivos = [c for c in self.arquivos if c not in fora]
            self._salvar_lista()
            self._lista()
            self._comparacao()
        elif acao == "limpar":
            self.arquivos = []
            self._salvar_lista()
            self._lista()
            self._comparacao()

    def _por(self, por):
        self.cfg.setValue("comparar/por", por)
        self._comparacao()

    def _caminho_aberto(self):
        am = self.am
        return str(Path(am.caminho).resolve()) if am is not None and am.caminho else None

    def _compactos(self):
        """Amostra aberta (ao vivo) + arquivos da lista já resumidos; sem repetir (amostra, sítio)."""
        out, vistos = [], set()
        if self.R is not None:
            c = self.R.compacto()
            out.append(c)
            vistos.add((c["amostra"], c["sitio"]))
        aberto = self._caminho_aberto()
        for cam in self.arquivos:
            inf = self.info.get(cam, {})
            if cam == aberto or inf.get("estado") != "ok":
                continue
            c = inf["compacto"]
            if (c["amostra"], c["sitio"]) in vistos:
                continue
            vistos.add((c["amostra"], c["sitio"]))
            out.append(c)
        return out

    def _lista(self):
        ent = []
        am = self.am
        aberto = self._caminho_aberto()
        if am is not None and aberto not in self.arquivos:
            nome = Path(am.caminho).name if am.caminho else "amostra importada (não salva)"
            ent.append((f"●  {nome}  ·  sítio {am.sitio}  ·  aberta, ao vivo", "a amostra aberta entra com as "
                        "edições atuais (não precisa estar na lista)", None))
        for cam in self.arquivos:
            inf = self.info.get(cam, {})
            e = inf.get("estado")
            if cam == aberto:
                st = "aberta, ao vivo (com as edições atuais)"
            elif e == "ok":
                st = f"{fmt(inf['compacto']['n_graos'])} grãos"
            elif e == "calc":
                st = f"calculando {int(100 * inf.get('prog', 0))} %…"
            elif e == "fila":
                st = "na fila"
            else:
                st = f"erro: {inf.get('msg', '?')}"
            ent.append((f"{Path(cam).name}  ·  sítio {inf.get('sitio', '?')}  ·  {st}", cam, cam))
        self.p.set_lista(ent)

    def _comparacao(self):
        por = self.p.seg_por.valor()
        comp = self._compactos()
        self.p.mostrar_comparacao(relatorio.agregar(comp, por), por, relatorio.agregar(comp, "campo"))
