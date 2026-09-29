"""Painel lateral de camadas.

  Amostra      informações + escurecer fora da amostra
  Fundo        BSE · Elementos (aditivo, cor e contraste por elemento, bruto/fração)
               · RGB (3 elementos) · Canal derivado das regras (Si-Mg, Al/Si…; suavizado)
  Minerais     visível / solo, preenchido ou contorno, colorir por mineral ou tamanho,
               opacidade, grãos × finos
  Clusters     k-means do reconhecer.py (se o pacote tiver)
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget)

import numpy as np

from ..nucleo import cores
from ..nucleo.objetos import LIM_AREIA, LIM_ARGILA
from ..nucleo.render import CamadaEl, Visual
from . import tema
from .comum import PainelRolavel, Secao, Segmentado, botao_seg, descartar, fmt
from .comum import mudo as _mudo, sw as _sw
from .contraste import Contraste

PRESETS_CANAL = ["Si-Mg", "Al/Si", "Fe+Mg", "Mg/Fe", "K/Al", "Ca/S", "Si", "Mg", "Fe", "Ca", "Al"]


class BotaoCor(QPushButton):
    corMudou = pyqtSignal(str)

    def __init__(self, cor):
        super().__init__()
        self.setFixedSize(18, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Trocar a cor")
        self.clicked.connect(self._escolher)
        self.set(cor)

    def set(self, cor):
        self.cor = cor
        self.setStyleSheet(f"QPushButton{{background:{cor}; border:1px solid rgba(0,0,0,0.5); border-radius:3px; padding:0;}}")

    def _escolher(self):
        c = QColorDialog.getColor(QColor(self.cor), self, "Cor da camada")
        if c.isValid():
            self.set(c.name())
            self.corMudou.emit(c.name())


def _botao_nome(txt, dica):
    """Nome clicável (texto sem moldura; marcado = acento em negrito)."""
    b = QPushButton(txt)
    b.setCheckable(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setToolTip(dica)
    b.setStyleSheet(
        f"QPushButton{{background:transparent;border:0;padding:1px 2px;text-align:left;color:{tema.C['texto']};}}"
        f"QPushButton:hover{{color:{tema.C['acento_forte']};}}"
        f"QPushButton:checked{{color:{tema.C['acento_forte']};font-weight:600;}}")
    return b


def _linha(w):
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(7)
    return h


class LinhaElemento(QWidget):
    visMudou = pyqtSignal(str, bool)
    corMudou = pyqtSignal(str, str)
    selecionado = pyqtSignal(str)

    def __init__(self, el, cor, vis):
        super().__init__()
        self.el = el
        h = _linha(self)
        self.chk = QCheckBox()
        self.chk.setChecked(vis)
        self.chk.toggled.connect(lambda on: self.visMudou.emit(el, on))
        self.cor = BotaoCor(cor)
        self.cor.corMudou.connect(lambda c: self.corMudou.emit(el, c))
        self.nome = _botao_nome(el, "Editar o contraste deste elemento")
        self.nome.clicked.connect(lambda: self.selecionado.emit(el))
        for w in (self.chk, self.cor):
            h.addWidget(w)
        h.addWidget(self.nome, 1)


class LinhaMineral(QWidget):
    visMudou = pyqtSignal()
    soloPedido = pyqtSignal(int)

    def __init__(self, mineral, n_obj, pct):
        super().__init__()
        self.mid = mineral.id
        h = _linha(self)
        self.chk = QCheckBox()
        self.chk.setChecked(True)
        self.chk.toggled.connect(self.visMudou.emit)
        h.addWidget(self.chk)
        h.addWidget(_sw(mineral.cor))
        self.nome = _botao_nome(mineral.nome.replace("_", " "), "Clique para isolar (solo) — e filtrar a tabela")
        self.nome.clicked.connect(lambda: self.soloPedido.emit(self.mid))
        h.addWidget(self.nome, 1)
        info = QLabel(f"{fmt(n_obj)} · {fmt(pct, 1)}%")
        info.setObjectName("mudo")
        info.setFont(tema.fonte_mono(8))
        info.setToolTip("objetos · % da área da amostra")
        h.addWidget(info)


class LinhaCluster(QWidget):
    visMudou = pyqtSignal()

    def __init__(self, k, nome, pct):
        super().__init__()
        self.k = k
        h = _linha(self)
        self.chk = QCheckBox()
        self.chk.setChecked(True)
        self.chk.toggled.connect(self.visMudou.emit)
        h.addWidget(self.chk)
        h.addWidget(_sw(cores.CORES_CLUSTER[(k - 1) % len(cores.CORES_CLUSTER)]))
        l = QLabel(f"{k} · {nome.replace('_', ' ')}")
        h.addWidget(l, 1)
        i = QLabel(f"{fmt(pct, 1)}%")
        i.setObjectName("mudo")
        i.setFont(tema.fonte_mono(8))
        h.addWidget(i)


class PainelCamadas(PainelRolavel):
    mudou = pyqtSignal()
    soloMudou = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__((14, 8, 12, 14), parent)
        self.lay = self.L
        self.am = self.comp = None
        self.est = {}
        self.sel_el = None
        self.rgb = [None, None, None]
        self.sel_rgb = 0
        self.tipo_el = "raw"
        self.bse_lim = None
        self.canal_lim = None
        self.solo = None
        self.linhas, self.linhas_el, self.linhas_cl = [], [], []
        self._bloq = False
        self._montar_amostra()
        self._montar_fundo()
        self._montar_minerais()
        self._montar_clusters()
        self.lay.addStretch()

    # ================= montagem =================
    def _montar_amostra(self):
        s = Secao("Amostra")
        self.info = QLabel("—")
        self.info.setObjectName("texto2")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("font-size: 8.5pt;")
        s.add(self.info)
        self.chk_fora = QCheckBox("Escurecer fora da amostra (resina)")
        self.chk_fora.toggled.connect(self._mudou)
        s.add(self.chk_fora)
        self.lay.addWidget(s)

    def _montar_fundo(self):
        s = Secao("Fundo")
        self.seg_fundo = Segmentado([("bse", "BSE"), ("elementos", "Elementos"), ("rgb", "RGB"), ("canal", "Canal")])
        self.seg_fundo.escolhido.connect(self._modo_fundo)
        s.add(self.seg_fundo)
        self.pilha = QStackedWidget()
        # BSE
        pb = QWidget()
        vb = QVBoxLayout(pb)
        vb.setContentsMargins(0, 4, 0, 0)
        self.ct_bse = Contraste("Contraste da BSE")
        self.ct_bse.mudou.connect(lambda lo, hi: self._set("bse_lim", (lo, hi)))
        vb.addWidget(self.ct_bse)
        self.pilha.addWidget(pb)
        # Elementos
        pe = QWidget()
        ve = QVBoxLayout(pe)
        ve.setContentsMargins(0, 4, 0, 0)
        ve.setSpacing(4)
        he = QHBoxLayout()
        self.seg_tipo = Segmentado([("raw", "bruto"), ("frac", "fração")])
        self.seg_tipo.escolhido.connect(self._tipo_el)
        he.addWidget(self.seg_tipo)
        he.addStretch()
        for rot, on in (("todos", True), ("nenhum", False)):
            b = botao_seg(rot)
            b.clicked.connect(lambda _c, o=on: self._todos_el(o))
            he.addWidget(b)
        ve.addLayout(he)
        self.box_el = QVBoxLayout()
        self.box_el.setSpacing(1)
        ve.addLayout(self.box_el)
        self.ct_el = Contraste()
        self.ct_el.mudou.connect(self._lim_el)
        ve.addWidget(self.ct_el)
        ve.addWidget(_mudo("nome = editar contraste · quadradinho = trocar a cor · camadas somam (aditivo)"))
        self.pilha.addWidget(pe)
        # RGB
        pr = QWidget()
        vr = QVBoxLayout(pr)
        vr.setContentsMargins(0, 4, 0, 0)
        vr.setSpacing(4)
        self.seg_tipo_rgb = Segmentado([("raw", "bruto"), ("frac", "fração")])
        self.seg_tipo_rgb.escolhido.connect(self._tipo_el)
        vr.addWidget(self.seg_tipo_rgb)
        self.combos_rgb, self.bts_rgb = [], []
        grp = QButtonGroup(self)
        for k, (canal, cor) in enumerate(zip("RGB", cores.CORES_RGB)):
            h = QHBoxLayout()
            l = QLabel(canal)
            l.setFixedWidth(14)
            l.setStyleSheet(f"color:{cor}; font-weight:700;")
            cb = QComboBox()
            cb.currentIndexChanged.connect(lambda _i, kk=k: self._rgb_mudou(kk))
            bt = QPushButton("contraste")
            bt.setObjectName("seg")
            bt.setCheckable(True)
            bt.setFixedHeight(22)
            grp.addButton(bt)
            bt.clicked.connect(lambda _c, kk=k: self._sel_rgb(kk))
            h.addWidget(l)
            h.addWidget(cb, 1)
            h.addWidget(bt)
            vr.addLayout(h)
            self.combos_rgb.append(cb)
            self.bts_rgb.append(bt)
        self.bts_rgb[0].setChecked(True)
        self.ct_rgb = Contraste()
        self.ct_rgb.mudou.connect(self._lim_rgb)
        vr.addWidget(self.ct_rgb)
        self.pilha.addWidget(pr)
        # Canal derivado
        pc = QWidget()
        vc = QVBoxLayout(pc)
        vc.setContentsMargins(0, 4, 0, 0)
        vc.setSpacing(5)
        vc.addWidget(_mudo("Expressão (elemento, A-B, A/B ou A+B+C)", 8.5))
        self.cb_expr = QComboBox()
        self.cb_expr.setEditable(True)
        self.cb_expr.addItems(PRESETS_CANAL)
        self.cb_expr.activated.connect(lambda _i: self._canal_mudou())
        self.cb_expr.lineEdit().editingFinished.connect(self._canal_mudou)
        vc.addWidget(self.cb_expr)
        self.erro_canal = QLabel()
        self.erro_canal.setObjectName("erro")
        self.erro_canal.setWordWrap(True)
        self.erro_canal.hide()
        vc.addWidget(self.erro_canal)
        self.seg_tipo_canal = Segmentado([("frac", "fração"), ("raw", "bruto")])
        self.seg_tipo_canal.escolhido.connect(lambda _v: self._canal_mudou())
        vc.addWidget(self.seg_tipo_canal)
        hr = QHBoxLayout()
        hr.addWidget(_mudo("Suavizar", 8.5))
        self.sl_raio = QSlider(Qt.Orientation.Horizontal)
        self.sl_raio.setRange(0, 45)
        self.l_raio = QLabel("sem")
        self.l_raio.setObjectName("mudo")
        self.l_raio.setFixedWidth(92)
        self.l_raio.setToolTip("Janela da média mascarada em px (e em µm nesta amostra)")
        self.sl_raio.valueChanged.connect(self._rotulo_raio)
        self.sl_raio.sliderReleased.connect(self._canal_mudou)
        self.sl_raio.valueChanged.connect(lambda _v: None if self.sl_raio.isSliderDown() else self._canal_mudou())
        hr.addWidget(self.sl_raio, 1)
        hr.addWidget(self.l_raio)
        vc.addLayout(hr)
        hp = QHBoxLayout()
        hp.addWidget(_mudo("raios das regras:", 8))
        for r, dica in ((0, "sem suavização"), (15, "quartzo / feldspato sódico"), (21, "feldspato potássico"),
                        (27, "biotita / clorita")):
            b = botao_seg(str(r), dica)
            b.clicked.connect(lambda _c, rr=r: self.sl_raio.setValue(rr))
            hp.addWidget(b)
        hp.addStretch()
        vc.addLayout(hp)
        hm = QHBoxLayout()
        hm.addWidget(_mudo("Cores", 8.5))
        self.cb_cmap = QComboBox()
        for k, rot in cores.NOMES_CMAP.items():
            self.cb_cmap.addItem(rot, k)
        self.cb_cmap.currentIndexChanged.connect(self._mudou)
        hm.addWidget(self.cb_cmap, 1)
        vc.addLayout(hm)
        self.ct_canal = Contraste()
        self.ct_canal.mudou.connect(lambda lo, hi: self._set("canal_lim", (lo, hi)))
        vc.addWidget(self.ct_canal)
        vc.addWidget(_mudo("Mesma matemática das regras: canal() do common.py e média "
                           "mascarada do segmentar.py (limiares q/v da config valem aqui)."))
        self.pilha.addWidget(pc)
        s.add(self.pilha)
        self.lay.addWidget(s)
        self._pagina(0)

    def _montar_minerais(self):
        s = Secao("Minerais")
        cab = QHBoxLayout()
        self.chk_min = QCheckBox("mostrar")
        self.chk_min.setChecked(True)
        self.chk_min.setToolTip("Liga/desliga todos os minerais (M)")
        self.chk_min.toggled.connect(self._mudou)
        cab.addWidget(self.chk_min)
        cab.addStretch()
        self.seg_estilo = Segmentado([("preenchido", "Preenchido"), ("contorno", "Contorno")])
        self.seg_estilo.escolhido.connect(self._mudou)
        cab.addWidget(self.seg_estilo)
        s.add(cab)
        self.box_min = QVBoxLayout()
        self.box_min.setSpacing(1)
        s.add(self.box_min)
        s.add(_mudo("clique no nome = isolar (solo)"))
        hc = QHBoxLayout()
        hc.addWidget(_mudo("Colorir por", 8.5))
        self.seg_colorir = Segmentado([("mineral", "Mineral"), ("tamanho", "Tamanho")])
        self.seg_colorir.escolhido.connect(self._colorir)
        hc.addWidget(self.seg_colorir)
        s.add(hc)
        self.leg_tam = QWidget()
        lt = QVBoxLayout(self.leg_tam)
        lt.setContentsMargins(0, 0, 0, 0)
        lt.setSpacing(2)
        a, b = str(LIM_ARGILA).replace(".", ","), str(LIM_AREIA).replace(".", ",")
        for cor, txt in zip(tema.CORES_WENTWORTH, (f"argila  < {a} µm", f"silte  {a}–{b} µm", f"areia  ≥ {b} µm")):
            r = QHBoxLayout()
            r.setSpacing(7)
            r.addWidget(_sw(cor, 11))
            l = QLabel(txt)
            l.setObjectName("texto2")
            l.setStyleSheet("font-size: 8.5pt;")
            r.addWidget(l)
            r.addStretch()
            lt.addLayout(r)
        self.leg_tam.hide()
        s.add(self.leg_tam)
        ho = QHBoxLayout()
        ho.addWidget(_mudo("Opacidade", 8.5))
        self.opac = QSlider(Qt.Orientation.Horizontal)
        self.opac.setRange(0, 100)
        self.opac.setValue(62)
        self.opac_v = QLabel("62%")
        self.opac_v.setObjectName("mudo")
        self.opac_v.setFixedWidth(34)
        self.opac.valueChanged.connect(lambda v: self.opac_v.setText(f"{v}%"))
        self.opac.valueChanged.connect(self._mudou)
        ho.addWidget(self.opac, 1)
        ho.addWidget(self.opac_v)
        s.add(ho)
        self.chk_graos = QCheckBox("Grãos (≥ area_min)")
        self.chk_finos = QCheckBox("Finos / cimento (< area_min)")
        for c in (self.chk_graos, self.chk_finos):
            c.setChecked(True)
            c.toggled.connect(self._mudou)
            s.add(c)
        self.lay.addWidget(s)

    def _montar_clusters(self):
        s = Secao("Clusters k-means", aberta=False)
        self.chk_cl = QCheckBox("mostrar clusters")
        self.chk_cl.toggled.connect(self._mudou)
        s.add(self.chk_cl)
        ho = QHBoxLayout()
        ho.addWidget(_mudo("Opacidade", 8.5))
        self.opac_cl = QSlider(Qt.Orientation.Horizontal)
        self.opac_cl.setRange(5, 100)
        self.opac_cl.setValue(50)
        self.opac_cl.valueChanged.connect(self._mudou)
        ho.addWidget(self.opac_cl, 1)
        s.add(ho)
        self.box_cl = QVBoxLayout()
        self.box_cl.setSpacing(1)
        s.add(self.box_cl)
        self.sem_cl = _mudo("Este pacote não tem clusters. Rode reconhecer.py no projeto e "
                            "reexporte (exportar_mudmap.py) ou importe a pasta.")
        s.add(self.sem_cl)
        self.sec_cl = s
        self.lay.addWidget(s)

    # ================= dados =================
    def _info(self, am, ob):
        h, w = am.shape
        fw, fh = am.fov_um
        self.info.setText(
            f"<b style='color:{tema.C['texto']}'>{am.amostra}</b> · sítio {am.sitio}<br>"
            f"{w} × {h} px · {fmt(am.pixel_um, 4)} µm/px · FOV {fmt(fw, 1)} × {fmt(fh, 1)} µm<br>"
            f"{fmt(ob.n)} objetos · {fmt(int((ob.area[1:] >= am.area_min).sum()))} ≥ area_min "
            f"({am.area_min} px) · elementos: {', '.join(am.elementos)}")

    def _linhas_minerais(self, am, ob, ocultos=()):
        """(Re)cria as linhas dos minerais presentes, preservando ocultos e solo."""
        descartar(self.linhas)
        self.linhas = []
        for m in am.minerais:
            if m.id < len(ob.min_npx) and ob.min_npx[m.id] > 0:
                ln = LinhaMineral(m, int(ob.n_obj_min[m.id]), float(ob.min_pct[m.id]))
                ln.chk.setChecked(m.id not in ocultos)
                ln.nome.setChecked(m.id == self.solo)
                ln.visMudou.connect(self._mudou)
                ln.soloPedido.connect(self._solo)
                self.box_min.addWidget(ln)
                self.linhas.append(ln)
        if self.solo is not None and all(l.mid != self.solo for l in self.linhas):
            self.solo = None

    def definir(self, am, ob, comp):
        self._bloq = True
        self.am, self.comp = am, comp
        self._info(am, ob)
        # elementos
        self.est = {el: {"vis": el in ("Si", "Al", "K", "Fe"), "cor": cores.cor_elemento(el, i),
                         "raw": None, "frac": None} for i, el in enumerate(am.elementos)}
        if not any(e["vis"] for e in self.est.values()):
            self.est[am.elementos[0]]["vis"] = True
        self.sel_el = next(el for el in am.elementos if self.est[el]["vis"])
        descartar(self.linhas_el)
        self.linhas_el = []
        for el in am.elementos:
            ln = LinhaElemento(el, self.est[el]["cor"], self.est[el]["vis"])
            ln.visMudou.connect(self._vis_el)
            ln.corMudou.connect(self._cor_el)
            ln.selecionado.connect(self._sel_el)
            self.box_el.addWidget(ln)
            self.linhas_el.append(ln)
        # RGB
        pref = [e for e in ("Ca", "Mg", "Si") if e in am.elementos]
        self.rgb = (pref + [e for e in am.elementos if e not in pref])[:3]
        while len(self.rgb) < 3:
            self.rgb.append(None)
        for k, cb in enumerate(self.combos_rgb):
            cb.clear()
            cb.addItem("—", None)
            for e in am.elementos:
                cb.addItem(e, e)
            cb.setCurrentIndex(max(0, cb.findData(self.rgb[k])))
        # canal
        self.canal_lim = None
        if not all(e in am.elementos for e in ("Si", "Mg")):
            self.cb_expr.setCurrentText(am.elementos[0])
        self.erro_canal.hide()
        # BSE
        self.bse_lim = None
        self.ct_bse.definir(comp.histograma(("bse",)), None, tema.C["texto2"], _rampa_cinza())
        # minerais
        self.solo = None
        self._linhas_minerais(am, ob)
        self.definir_clusters(am, emitir=False)
        self._bloq = False
        self._atualiza_ct_el()
        self._atualiza_ct_rgb()

    def definir_clusters(self, am, emitir=True):
        """(Re)monta a legenda dos clusters (também após um k-means novo no modo Segmentar)."""
        descartar(self.linhas_cl)
        self.linhas_cl = []
        tem = am.clusters is not None
        self.chk_cl.setEnabled(tem)
        self.opac_cl.setEnabled(tem)
        self.sem_cl.setVisible(not tem)
        if not tem:
            self.chk_cl.setChecked(False)
        else:
            nomes = (am.clusters_info or {}).get("nomes", {})
            cont = np.bincount(am.clusters[am.mascara].ravel(), minlength=int(am.clusters.max()) + 1)
            tot = max(1, int(cont[1:].sum()))
            for k in range(1, len(cont)):
                ln = LinhaCluster(k, nomes.get(str(k), "?"), 100 * cont[k] / tot)
                ln.visMudou.connect(self._mudou)
                self.box_cl.addWidget(ln)
                self.linhas_cl.append(ln)
        if emitir:
            self._mudou()

    def atualizar_objetos(self, am, ob, comp):
        """Depois de edições: novas contagens/minerais, preservando fundo, contraste,
        visibilidade e solo."""
        self._bloq = True
        self.comp = comp
        self._linhas_minerais(am, ob, {l.mid for l in self.linhas if not l.chk.isChecked()})
        self._info(am, ob)
        self._bloq = False

    # ================= eventos =================
    def _mudou(self, *_):
        if not self._bloq:
            self.mudou.emit()

    def _set(self, attr, val):
        setattr(self, attr, val)
        self._mudou()

    def _pagina(self, i):
        for k in range(self.pilha.count()):
            pol = QSizePolicy.Policy.Preferred if k == i else QSizePolicy.Policy.Ignored
            self.pilha.widget(k).setSizePolicy(pol, pol)
        self.pilha.setCurrentIndex(i)
        self.pilha.adjustSize()

    def _modo_fundo(self, modo):
        self._pagina(["bse", "elementos", "rgb", "canal"].index(modo))
        if modo == "elementos":
            self._atualiza_ct_el()
        elif modo == "rgb":
            self._atualiza_ct_rgb()
        self._mudou()

    def modo_fundo(self):
        return self.seg_fundo.valor()

    def set_modo_fundo(self, modo):
        self.seg_fundo.set(modo)
        self._modo_fundo(modo)

    def _lim(self, el, tipo):
        e = self.est[el]
        if e[tipo] is None:
            e[tipo] = self.comp.histograma((tipo, self.am.indice(el)))["auto"]
        return e[tipo]

    def _tipo_el(self, tipo):
        self.tipo_el = tipo
        self.seg_tipo.set(tipo)
        self.seg_tipo_rgb.set(tipo)
        self._atualiza_ct_el()
        self._atualiza_ct_rgb()
        self._mudou()

    def _todos_el(self, on):
        self._bloq = True
        for l in self.linhas_el:
            l.chk.setChecked(on)
            self.est[l.el]["vis"] = on
        self._bloq = False
        self._mudou()

    def _vis_el(self, el, on):
        self.est[el]["vis"] = on
        if on:
            self._sel_el(el, emitir=False)
        self._mudou()

    def _cor_el(self, el, cor):
        self.est[el]["cor"] = cor
        if el == self.sel_el:
            self._atualiza_ct_el()
        self._mudou()

    def _sel_el(self, el, emitir=False):
        self.sel_el = el
        self._atualiza_ct_el()

    def _atualiza_ct_el(self):
        if self.comp is None or self.sel_el is None:
            return
        for l in self.linhas_el:
            l.nome.setChecked(l.el == self.sel_el)
        el, t = self.sel_el, self.tipo_el
        st = self.comp.histograma((t, self.am.indice(el)))
        cor = self.est[el]["cor"]
        self.ct_el.definir(st, self._lim(el, t), cor, _rampa_para(cor),
                           f"Contraste — {el} ({'bruto 0–255' if t == 'raw' else 'fração de cátions'})")

    def _lim_el(self, lo, hi):
        if self.sel_el:
            self.est[self.sel_el][self.tipo_el] = (lo, hi)
            self._mudou()

    def _rgb_mudou(self, k):
        if self._bloq:
            return
        self.rgb[k] = self.combos_rgb[k].currentData()
        if k == self.sel_rgb:
            self._atualiza_ct_rgb()
        self._mudou()

    def _sel_rgb(self, k):
        self.sel_rgb = k
        self._atualiza_ct_rgb()

    def _atualiza_ct_rgb(self):
        if self.comp is None:
            return
        el = self.rgb[self.sel_rgb]
        if el is None:
            self.ct_rgb.setEnabled(False)
            return
        self.ct_rgb.setEnabled(True)
        t = self.tipo_el
        cor = cores.CORES_RGB[self.sel_rgb]
        self.ct_rgb.definir(self.comp.histograma((t, self.am.indice(el))), self._lim(el, t), cor,
                            _rampa_para(cor), f"Contraste — {'RGB'[self.sel_rgb]} = {el}")

    def _lim_rgb(self, lo, hi):
        el = self.rgb[self.sel_rgb]
        if el:
            self.est[el][self.tipo_el] = (lo, hi)
            self._mudou()

    def _rotulo_raio(self, v):
        if v <= 1:
            self.l_raio.setText("sem")
        else:
            um = f" · {fmt(v * self.am.pixel_um, 2)} µm" if self.am is not None else ""
            self.l_raio.setText(f"r={v}{um}")

    def _canal_mudou(self):
        self.canal_lim = None
        self._mudou()

    def set_canal_stats(self, st, lim, v):
        self.erro_canal.hide()
        titulo = f"{v.canal_expr} · {'fração' if v.canal_tipo == 'frac' else 'bruto'}" + \
                 (f" · suavizado r={v.canal_raio}" if v.canal_raio > 1 else "")
        self.ct_canal.definir(st, lim, tema.C["acento"], cores.lut(v.canal_cmap), titulo)

    def set_erro_canal(self, msg):
        self.erro_canal.setText(msg)
        self.erro_canal.setVisible(bool(msg))

    def _colorir(self, modo):
        self.leg_tam.setVisible(modo == "tamanho")
        self._mudou()

    def _solo(self, mid):
        self.solo = None if self.solo == mid else mid
        for l in self.linhas:
            l.nome.setChecked(l.mid == self.solo)
        self.soloMudou.emit(self.solo)
        self._mudou()

    def alternar_minerais(self):
        self.chk_min.setChecked(not self.chk_min.isChecked())

    # ================= estado -> Visual =================
    def visual(self):
        v = Visual(
            minerais=self.chk_min.isChecked(), estilo=self.seg_estilo.valor(),
            colorir=self.seg_colorir.valor(),
            ocultos={l.mid for l in self.linhas if not l.chk.isChecked()},
            solo=self.solo, opacidade=self.opac.value() / 100.0,
            graos=self.chk_graos.isChecked(), finos=self.chk_finos.isChecked(),
            clusters=self.chk_cl.isChecked() and self.chk_cl.isEnabled(),
            clusters_opac=self.opac_cl.value() / 100.0,
            clusters_ocultos={l.k for l in self.linhas_cl if not l.chk.isChecked()},
            escurecer_fora=self.chk_fora.isChecked())
        modo = self.modo_fundo()
        if self.am is None:
            return v
        if modo == "elementos":
            v.fundo, v.tipo_el = "aditivo", self.tipo_el
            v.camadas = [CamadaEl(el, self.est[el]["cor"], *self._lim(el, self.tipo_el))
                         for el in self.am.elementos if self.est[el]["vis"]]
        elif modo == "rgb":
            v.fundo, v.tipo_el = "aditivo", self.tipo_el
            v.camadas = [CamadaEl(el, cores.CORES_RGB[k], *self._lim(el, self.tipo_el))
                         for k, el in enumerate(self.rgb) if el]
        elif modo == "canal":
            v.fundo = "canal"
            v.canal_expr = self.cb_expr.currentText().strip() or "Si"
            v.canal_tipo = self.seg_tipo_canal.valor()
            v.canal_raio = self.sl_raio.value()
            v.canal_cmap = self.cb_cmap.currentData()
            v.canal_lim = self.canal_lim
        else:
            v.fundo, v.bse_lim = "bse", self.bse_lim
        return v


def _rampa_para(cor):
    r, g, b = cores.hex_rgb(cor)
    t = np.linspace(0, 1, 256)[:, None]
    return (t * np.array([r, g, b])).round().astype(np.uint8)


def _rampa_cinza():
    return cores.lut("cinza")
