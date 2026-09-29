"""Painel do modo Edição (substitui o editor napari)."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import tema
from .comum import Mensagem, PainelRolavel, Secao, Segmentado, botao_seg, fmt
from .comum import botao as _botao, icone_cor as _icone_cor, mudo as _mudo

FERRAMENTAS = {
    "mao": ("Mover", "Arraste para mover · roda = zoom · botão do meio move em qualquer ferramenta"),
    "pincel": ("Pincel", "B · arraste para pintar o mineral ativo · [ ] mudam o tamanho · Alt+clique pega o mineral"),
    "borracha": ("Borracha", "E · arraste para apagar · [ ] mudam o tamanho"),
    "balde": ("Balde", "K · clique: a região conexa sob o cursor vira o mineral ativo"),
    "contagotas": ("Conta-gotas", "I · clique num mineral para torná-lo o ativo"),
    "remover": ("Remover grão", "X · clique num grão: ele inteiro é apagado"),
    "retangulo": ("Retângulo", "U · arraste; a ação das formas define o que acontece"),
    "elipse": ("Elipse", "O · arraste; a ação das formas define o que acontece"),
    "poligono": ("Polígono", "Y · clique nos vértices · duplo clique, Enter ou botão direito fecha · "
                             "Backspace desfaz o último vértice · Esc cancela"),
    "laco": ("Laço", "L · arraste contornando a região (à mão livre)"),
    "pontos": ("Pontos → regiões", "N · clique ao redor de cada grão · G converte · botão direito remove um ponto"),
}


class PainelEdicao(PainelRolavel):
    ativoMudou = pyqtSignal(int)
    raioMudou = pyqtSignal(float)
    protecoesMudaram = pyqtSignal()
    pedido = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        L = self.L
        self.am = None

        # ---- ferramenta + mensagem ----
        self.l_ferr = QLabel("Pincel")
        self.l_ferr.setObjectName("titulo")
        L.addWidget(self.l_ferr)
        self.l_dica = _mudo("", 8.5)
        L.addWidget(self.l_dica)
        self.msg = Mensagem()
        L.addWidget(self.msg)

        # ---- mineral ativo ----
        s = Secao("Mineral ativo")
        self.cb_ativo = QComboBox()
        self.cb_ativo.setIconSize(self.cb_ativo.iconSize())
        self.cb_ativo.currentIndexChanged.connect(lambda _i: self.ativoMudou.emit(self.ativo()))
        s.add(self.cb_ativo)
        s.add(_mudo("Alt+clique no canvas (pincel/borracha) ou conta-gotas (I) pega o mineral."))
        L.addWidget(s)

        # ---- pincel ----
        s = Secao("Pincel e borracha")
        h = QHBoxLayout()
        self.sl_raio = QSlider(Qt.Orientation.Horizontal)
        self.sl_raio.setRange(1, 150)
        self.sl_raio.setValue(8)
        self.l_raio = QLabel()
        self.l_raio.setObjectName("mudo")
        self.l_raio.setFixedWidth(124)
        self.sl_raio.valueChanged.connect(self._raio)
        h.addWidget(self.sl_raio, 1)
        h.addWidget(self.l_raio)
        s.add(h)
        self.chk_borr = QCheckBox("Borracha apaga só o mineral ativo")
        self.chk_borr.setChecked(True)
        s.add(self.chk_borr)
        L.addWidget(s)

        # ---- formas ----
        s = Secao("Formas (retângulo · elipse · polígono · laço)")
        self.seg_acao = Segmentado([("pintar", "Pintar"), ("apagar", "Apagar"), ("reatribuir", "Reatribuir")])
        self.seg_acao.escolhido.connect(self._acao)
        s.add(self.seg_acao)
        h = QHBoxLayout()
        self.l_alvo = _mudo("Age sobre", 8.5)
        h.addWidget(self.l_alvo)
        self.cb_alvo = QComboBox()
        h.addWidget(self.cb_alvo, 1)
        self.w_alvo = QWidget()
        self.w_alvo.setLayout(h)
        h.setContentsMargins(0, 0, 0, 0)
        s.add(self.w_alvo)
        self.ed_filtro = QLineEdit()
        self.ed_filtro.setPlaceholderText("filtro químico opcional, ex.: Fe>0.12, S>0.12")
        self.ed_filtro.setToolTip("Condições em FRAÇÃO de cátions (mesma sintaxe das regras). "
                                  "Aceita canais compostos: Si-Mg>0.15, Al/Si<0.5")
        s.add(self.ed_filtro)
        self.chk_livres = QCheckBox("Incluir pixels livres que passam no filtro")
        s.add(self.chk_livres)
        L.addWidget(s)

        # ---- proteções ----
        s = Secao("Proteções")
        self.chk_invadir = QCheckBox("Não invadir outros minerais")
        self.chk_amostra = QCheckBox("Só dentro da amostra (fora = resina)")
        for c in (self.chk_invadir, self.chk_amostra):
            c.setChecked(True)
            c.toggled.connect(self.protecoesMudaram.emit)
            s.add(c)
        L.addWidget(s)

        # ---- pontos ----
        s = Secao("Pontos → regiões")
        self.l_npts = _mudo("0 pontos — ferramenta Pontos (N)", 8.5)
        s.add(self.l_npts)
        self.seg_pts = Segmentado([("angular", "Angular"), ("convexo", "Convexo"), ("semente", "Semente")])
        self.seg_pts.setToolTip("Angular = polígono pelos pontos em volta do centro (editor napari); "
                                "Convexo = fecho convexo; Semente = disco em cada ponto")
        s.add(self.seg_pts)
        g = QGridLayout()
        g.addWidget(_mudo("Agrupar até", 8.5), 0, 0)
        self.sp_eps = QSpinBox()
        self.sp_eps.setRange(2, 2000)
        self.sp_eps.setSuffix(" px")
        self.sp_eps.setToolTip("Pontos mais próximos que isto formam o mesmo grão")
        g.addWidget(self.sp_eps, 0, 1)
        g.addWidget(_mudo("Raio semente", 8.5), 1, 0)
        self.sp_semente = QSpinBox()
        self.sp_semente.setRange(1, 300)
        self.sp_semente.setValue(6)
        self.sp_semente.setSuffix(" px")
        g.addWidget(self.sp_semente, 1, 1)
        s.add(g)
        h = QHBoxLayout()
        b = _botao("Converter (G)", "Agrupa os pontos e pinta as regiões no mineral ativo", "pontos")
        b.clicked.connect(lambda: self.pedido.emit("pontos", None))
        h.addWidget(b)
        b = _botao("Limpar (C)", "Remove todos os pontos", "fechar")
        b.clicked.connect(lambda: self.pedido.emit("limpar_pontos", None))
        h.addWidget(b)
        s.add(h)
        L.addWidget(s)

        # ---- propagar ----
        s = Secao("Propagar por exemplo")
        s.add(_mudo("Aprende a química do núcleo do mineral ativo e propõe regiões novas "
                    "(algoritmo do propagar.py). Você revisa antes de aceitar."))
        g = QGridLayout()
        self.sp_thr = QDoubleSpinBox()
        self.sp_thr.setRange(0.3, 5.0)
        self.sp_thr.setSingleStep(0.1)
        self.sp_thr.setValue(1.2)
        self.sp_thr.setToolTip("Fator sobre a distância de Mahalanobis p98 da semente (maior = mais permissivo)")
        self.sp_gate = QDoubleSpinBox()
        self.sp_gate.setRange(0.0, 0.9)
        self.sp_gate.setSingleStep(0.05)
        self.sp_gate.setValue(0.10)
        self.sp_gate.setToolTip("Portão por região: mediana nos mapas_seg ≥ este quantil das medianas da semente")
        self.sp_erode = QSpinBox()
        self.sp_erode.setRange(0, 8)
        self.sp_erode.setValue(2)
        self.sp_erode.setToolTip("Erosão da semente antes de aprender (exclui bordas mistas)")
        for i, (rot, w) in enumerate((("Tolerância (thr)", self.sp_thr), ("Portão (q)", self.sp_gate),
                                      ("Erosão (px)", self.sp_erode))):
            g.addWidget(_mudo(rot, 8.5), i, 0)
            g.addWidget(w, i, 1)
        s.add(g)
        self.chk_limpar = QCheckBox("Limpar speckle da semente")
        self.chk_limpar.setChecked(True)
        s.add(self.chk_limpar)
        b = _botao("Propagar (P)", "Propõe regiões novas do mineral ativo", "propagar")
        b.clicked.connect(lambda: self.pedido.emit("propagar", None))
        s.add(b)
        self.w_prop = QWidget()
        vp = QVBoxLayout(self.w_prop)
        vp.setContentsMargins(0, 4, 0, 0)
        self.l_prop = QLabel()
        self.l_prop.setWordWrap(True)
        self.l_prop.setStyleSheet(f"color: {tema.C['selB']};")
        vp.addWidget(self.l_prop)
        h = QHBoxLayout()
        for rot, on in (("incluir todas", True), ("excluir todas", False)):
            b = botao_seg(rot)
            b.clicked.connect(lambda _c, o=on: self.pedido.emit("prop_todas", o))
            h.addWidget(b)
        h.addStretch()
        vp.addLayout(h)
        h = QHBoxLayout()
        b = _botao("Aceitar", "Pinta as regiões propostas que continuam incluídas", primario=True)
        b.clicked.connect(lambda: self.pedido.emit("aceitar_prop", None))
        h.addWidget(b)
        b = _botao("Descartar")
        b.clicked.connect(lambda: self.pedido.emit("descartar_prop", None))
        h.addWidget(b)
        vp.addLayout(h)
        self.w_prop.hide()
        s.add(self.w_prop)
        L.addWidget(s)

        # ---- morfologia ----
        s = Secao("Morfologia (mineral ativo)", aberta=False)
        g = QGridLayout()
        self.sp_fechar = QSpinBox()
        self.sp_fechar.setRange(1, 20)
        self.sp_fechar.setValue(2)
        self.sp_fechar.setPrefix("r = ")
        self.sp_abrir = QSpinBox()
        self.sp_abrir.setRange(1, 20)
        self.sp_abrir.setValue(1)
        self.sp_abrir.setPrefix("r = ")
        self.sp_limpar = QSpinBox()
        self.sp_limpar.setRange(1, 100000)
        self.sp_limpar.setValue(30)
        self.sp_limpar.setSuffix(" px")
        linhas = [("Fechar", "fechar", self.sp_fechar, "Fechamento (junta falhas e dentes)"),
                  ("Abrir", "abrir", self.sp_abrir, "Abertura (remove pontas e speckle)"),
                  ("Limpar <", "limpar", self.sp_limpar, "Remove objetos menores que a área"),
                  ("Preencher buracos", "preencher", None, "Grão sólido"),
                  ("Fecho convexo", "convexo", None, "Fecho convexo de cada grão"),
                  ("Manter o maior", "maior", None, "Mantém só o maior grão")]
        for i, (rot, op, sp, dica) in enumerate(linhas):
            b = _botao(rot, dica)
            b.clicked.connect(lambda _c, o=op, w=sp: self.pedido.emit("morf", (o, w.value() if w else 0)))
            if sp:
                g.addWidget(b, i, 0)
                g.addWidget(sp, i, 1)
            else:
                g.addWidget(b, i, 0, 1, 2)
        s.add(g)
        s.add(_mudo("Mesma semântica do pós-filtro 'forma' das regras (segmentar.aplicar_forma)."))
        L.addWidget(s)

        # ---- limpeza ----
        s = Secao("Limpeza", aberta=False)
        b = _botao("Remover rótulos fora da amostra…", "Mostra quantos pixels, por mineral, estão fora da "
                   "máscara (resina) e pede confirmação", "limpar")
        b.clicked.connect(lambda: self.pedido.emit("limpar_fora", None))
        s.add(b)
        L.addWidget(s)

        # ---- histórico ----
        s = Secao("Histórico")
        h = QHBoxLayout()
        self.b_desf = _botao("Desfazer", "Ctrl+Z", "desfazer")
        self.b_ref = _botao("Refazer", "Ctrl+Y", "refazer")
        self.b_desf.clicked.connect(lambda: self.pedido.emit("desfazer", None))
        self.b_ref.clicked.connect(lambda: self.pedido.emit("refazer", None))
        h.addWidget(self.b_desf)
        h.addWidget(self.b_ref)
        s.add(h)
        self.lista = QListWidget()
        self.lista.setMinimumHeight(130)
        self.lista.setMaximumHeight(220)
        self.lista.setStyleSheet("QListWidget::item { padding: 3px 6px; }")
        s.add(self.lista)
        self.l_hist = _mudo("", 8)
        s.add(self.l_hist)
        L.addWidget(s)

        # ---- salvar ----
        s = Secao("Salvar")
        self.l_sujo = QLabel()
        s.add(self.l_sujo)
        h = QHBoxLayout()
        b = _botao("Salvar .mudmap", "Ctrl+S — guarda também a versão anterior dos rótulos", "salvar", primario=True)
        b.clicked.connect(lambda: self.pedido.emit("salvar", None))
        h.addWidget(b)
        b = _botao("Exportar p/ estado/…", "Grava estado/rotulos.npy do projeto (com backup)", "exportar")
        b.clicked.connect(lambda: self.pedido.emit("exportar", None))
        h.addWidget(b)
        s.add(h)
        L.addWidget(s)
        L.addStretch()
        self._acao("pintar")
        self.set_sujo(False)

    # ================= dados =================
    def definir(self, am):
        self.am = am
        self.cb_ativo.blockSignals(True)
        self.cb_ativo.clear()
        for m in am.minerais:
            self.cb_ativo.addItem(_icone_cor(m.cor), f"{m.id} · {m.nome.replace('_', ' ')}", m.id)
        self.cb_ativo.blockSignals(False)
        presentes = [int(v) for v in set(am.rotulos[::4, ::4].ravel().tolist()) if v]
        if presentes:
            self.set_ativo(min(presentes))
        self._acao(self.seg_acao.valor())
        h, w = am.shape
        self.sp_eps.setValue(int(0.04 * (h * h + w * w) ** 0.5))
        self.sp_limpar.setValue(am.area_min)
        self._raio(self.sl_raio.value())
        self.set_prop(None)

    def ativo(self):
        return self.cb_ativo.currentData() or 0

    def set_ativo(self, mid):
        i = self.cb_ativo.findData(int(mid))
        if i >= 0:
            self.cb_ativo.setCurrentIndex(i)

    def cor_ativo(self):
        m = self.am.mineral(self.ativo()) if self.am else None
        return m.cor if m else tema.C["acento_forte"]

    def mudar_raio(self, fator):
        self.sl_raio.setValue(max(1, min(150, round(self.sl_raio.value() * fator + (1 if fator > 1 else -1)))))

    def _raio(self, v):
        um = f" · {fmt(v * self.am.pixel_um, 2)} µm" if self.am else ""
        self.l_raio.setText(f"r = {v} px{um}")
        self.raioMudou.emit(float(v))

    def _acao(self, acao):
        self.cb_alvo.clear()
        self.w_alvo.setVisible(acao != "pintar")
        self.chk_livres.setVisible(acao == "reatribuir")
        if acao == "apagar":
            self.cb_alvo.addItem("Mineral ativo", None)
            self.cb_alvo.addItem("Todos os minerais", -1)
        elif acao == "reatribuir":
            self.cb_alvo.addItem("Qualquer mineral → ativo", None)
        if acao != "pintar" and self.am:
            for m in self.am.minerais:
                self.cb_alvo.addItem(_icone_cor(m.cor), ("só " if acao == "apagar" else "de ") +
                                     m.nome.replace("_", " "), m.id)

    def acao_forma(self):
        return self.seg_acao.valor()

    def origem(self):
        return self.cb_alvo.currentData() if self.acao_forma() != "pintar" else None

    def filtro(self):
        return self.ed_filtro.text().strip()

    def params_pontos(self):
        return self.seg_pts.valor(), float(self.sp_eps.value()), float(self.sp_semente.value())

    def params_propagar(self):
        return dict(thr=self.sp_thr.value(), gate_q=self.sp_gate.value(), erode=self.sp_erode.value(),
                    limpar=self.chk_limpar.isChecked())

    # ================= feedback =================
    def set_ferramenta(self, nome):
        t, d = FERRAMENTAS.get(nome, (nome, ""))
        self.l_ferr.setText(t)
        self.l_dica.setText(d)

    def set_msg(self, texto, tipo="ok"):
        self.msg.mostrar(texto, tipo)

    def set_n_pontos(self, n):
        self.l_npts.setText(f"{n} ponto(s) — G converte no mineral ativo" if n else
                            "0 pontos — ferramenta Pontos (N)")

    def set_prop(self, texto):
        self.w_prop.setVisible(bool(texto))
        self.l_prop.setText(texto or "")

    def set_sujo(self, sujo, arquivo=None):
        if sujo:
            self.l_sujo.setText("● alterações não salvas")
            self.l_sujo.setStyleSheet(f"color: {tema.C['aviso']}; font-size: 8.5pt;")
        else:
            self.l_sujo.setText("salvo" + (f" em {arquivo}" if arquivo else ""))
            self.l_sujo.setStyleSheet(f"color: {tema.C['mudo']}; font-size: 8.5pt;")

    def atualizar_historico(self, hist):
        self.lista.clear()
        for i, p in enumerate(hist.passos):
            it = QListWidgetItem(f"{'✓' if i < hist.pos else '↶'}  {p.desc}  ·  {fmt(p.px)} px")
            if i >= hist.pos:
                it.setForeground(QColor(tema.C["mudo"]))
                f = QFont(it.font())
                f.setItalic(True)
                it.setFont(f)
            self.lista.addItem(it)
        if hist.pos > 0:
            self.lista.scrollToItem(self.lista.item(hist.pos - 1))
        mb = sum(p.nbytes for p in hist.passos) / 2 ** 20
        self.l_hist.setText(f"{hist.pos} de {len(hist.passos)} passos aplicados · {mb:.1f} MB na memória")
        self.b_desf.setEnabled(hist.pode_desfazer)
        self.b_ref.setEnabled(hist.pode_refazer)
