"""Janela principal do MudMap Studio (modos Inspetor, Edição, Segmentar e Relatório)."""
import dataclasses
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                             QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
                             QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import FASE, __version__
from ..nucleo import cores, exportar_estado, importar, objetos, pacote
from ..nucleo.render import Compositor, hex_rgb
from . import icones, tema
from .camadas import PainelCamadas
from .canvas import Canvas, fmt_um
from .comum import fmt, sobreposicao
from .controle_edicao import ControleEdicao
from .dialogos import DialogoSitios, Servico
from .edicao import FERRAMENTAS, PainelEdicao
from .inspetor import FichaGrao
from .relatorio import ControleRelatorio, PainelRelatorio
from .renderizacao import Renderizacao
from .segmentar import ControleSegmentar, PainelSegmentar
from .tabela import PainelTabela

MODOS = [("inspetor", "Inspetor"), ("edicao", "Edição"), ("segmentar", "Segmentar"), ("relatorio", "Relatório")]
# ferramentas de edição: (chave, ícone, atalho)
FERR_ED = [("mao", "mao", "H"), ("pincel", "pincel", "B"), ("borracha", "borracha", "E"),
           ("balde", "balde", "K"), ("contagotas", "contagotas", "I"), ("remover", "remover", "X"),
           None, ("retangulo", "retangulo", "U"), ("elipse", "elipse", "O"), ("poligono", "poligono", "Y"),
           ("laco", "laco", "L"), ("pontos", "pontos", "N")]


def _sub(prog, a, b):
    return lambda f, m: prog(a + (b - a) * f, m)


class BoasVindas(QWidget):
    def __init__(self, janela):
        super().__init__()
        self.janela = janela
        fora = QVBoxLayout(self)
        fora.addStretch(2)
        linha = QHBoxLayout()
        linha.addStretch()
        card = QFrame()
        card.setObjectName("cartao")
        card.setFixedWidth(520)
        c = QVBoxLayout(card)
        c.setContentsMargins(34, 30, 34, 28)
        c.setSpacing(10)
        logo = QLabel()
        png = Path(__file__).resolve().parents[1] / "recursos" / "mudmap.png"
        if png.exists():
            logo.setPixmap(QPixmap(str(png)).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
        else:
            logo.setPixmap(icones.pixmap("inspetor", tema.C["acento_forte"], 40))
        c.addWidget(logo)
        t = QLabel("MudMap Studio")
        t.setStyleSheet("font-size: 22pt; font-weight: 600;")
        c.addWidget(t)
        s = QLabel("Inspeção e edição da segmentação mineral por EDS.\n"
                   "Abra um pacote .mudmap ou importe um sítio direto do projeto.")
        s.setObjectName("texto2")
        c.addWidget(s)
        c.addSpacing(8)
        bl = QHBoxLayout()
        b1 = QPushButton("  Abrir .mudmap")
        b1.setIcon(icones.icone("abrir", "#0d1a14"))
        b1.setObjectName("primario")
        b1.clicked.connect(lambda: janela.abrir_arquivo())
        b2 = QPushButton("  Importar pasta do projeto")
        b2.setIcon(icones.icone("importar"))
        b2.clicked.connect(janela.importar_pasta)
        for b in (b1, b2):
            b.setMinimumHeight(36)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bl.addWidget(b)
        c.addLayout(bl)
        c.addSpacing(10)
        r = QLabel("RECENTES")
        r.setObjectName("secao")
        c.addWidget(r)
        self.lista = QListWidget()
        self.lista.setMinimumHeight(150)
        self.lista.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.itemActivated.connect(lambda it: janela.abrir_arquivo(it.data(256)))
        c.addWidget(self.lista)
        self.vazio = QLabel("Nenhum arquivo aberto ainda · arraste um .mudmap para esta janela")
        self.vazio.setObjectName("mudo")
        c.addWidget(self.vazio)
        v = QLabel(f"versão {__version__} · fase {FASE}")
        v.setObjectName("mudo")
        v.setStyleSheet("font-size: 8pt;")
        c.addWidget(v)
        linha.addWidget(card)
        linha.addStretch()
        fora.addLayout(linha)
        fora.addStretch(3)

    def atualizar(self, recentes):
        self.lista.clear()
        for p in recentes:
            it = QListWidgetItem(f"{Path(p).name}\n{Path(p).parent}")
            it.setData(256, p)
            it.setIcon(icones.icone("abrir"))
            self.lista.addItem(it)
        self.lista.setVisible(bool(recentes))
        self.vazio.setVisible(not recentes)


class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MudMap Studio")
        self.resize(1480, 900)
        self.setAcceptDrops(True)
        self.cfg = QSettings("MudMap", "Studio")
        self.am = self.ob = self.comp = None
        self.sel_a = self.sel_b = None
        self.fixado = False
        self.modo_comparar = False
        self.modo = "inspetor"
        self.sujo = False
        self.versao_stats = 0
        self._ocupado = False
        self._hover_sel = None
        self._primeira = True
        self._visual = None
        self._ferr_ed = "pincel"
        self.tarefas = Servico(self)              # _rodar: uma tarefa longa por vez
        self.render = Renderizacao(self)
        self.render.resultado.connect(self._ao_render)
        self.render.erro.connect(self._erro_render)
        self.render.ocupado.connect(lambda on: self.st_render.setText("compondo…" if on else ""))
        self._montar()
        self.controle = ControleEdicao(self)
        self.seg = ControleSegmentar(self)
        self.rel = ControleRelatorio(self)
        self._tam_antes = None
        self._atalhos()
        self.boas.atualizar(self._recentes())
        self._timer_recompor = QTimer(self)
        self._timer_recompor.setSingleShot(True)
        self._timer_recompor.setInterval(15)
        self._timer_recompor.timeout.connect(self._pedir_render)

    # ================= montagem =================
    def _montar(self):
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        marca = QLabel()
        marca.setPixmap(icones.pixmap("inspetor", tema.C["acento_forte"], 20))
        tb.addWidget(marca)
        nome = QLabel(" MudMap Studio  ")
        nome.setStyleSheet("font-weight: 600; font-size: 10.5pt;")
        tb.addWidget(nome)
        tb.addSeparator()
        self.a_abrir = QAction(icones.icone("abrir"), "Abrir", self)
        self.a_abrir.setToolTip("Abrir .mudmap (Ctrl+O)")
        self.a_abrir.triggered.connect(lambda: self.abrir_arquivo())
        self.a_importar = QAction(icones.icone("importar"), "Importar pasta", self)
        self.a_importar.setToolTip("Importar um sítio das pastas do projeto (Ctrl+I)")
        self.a_importar.triggered.connect(self.importar_pasta)
        self.a_salvar = QAction(icones.icone("salvar"), "Salvar", self)
        self.a_salvar.setToolTip("Salvar no .mudmap (Ctrl+S) · Ctrl+Shift+S = salvar como")
        self.a_salvar.triggered.connect(self.salvar)
        self.a_salvar.setEnabled(False)
        self.a_exportar = QAction(icones.icone("exportar"), "Exportar p/ estado", self)
        self.a_exportar.setToolTip("Grava os rótulos em estado/rotulos.npy do projeto (com backup)")
        self.a_exportar.triggered.connect(self.exportar_estado)
        self.a_exportar.setEnabled(False)
        for a in (self.a_abrir, self.a_importar, self.a_salvar, self.a_exportar):
            tb.addAction(a)
        esp = QWidget()
        esp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(esp)
        self.lbl_amostra = QLabel("")
        self.lbl_amostra.setObjectName("texto2")
        tb.addWidget(self.lbl_amostra)
        tb.addWidget(QLabel("  "))
        self.pill_modo = QLabel("Inspetor")
        self.pill_modo.setObjectName("pillModo")
        tb.addWidget(self.pill_modo)
        tb.addWidget(QLabel(" "))

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        barra = QWidget()
        barra.setObjectName("barraModos")
        barra.setFixedWidth(52)
        bv = QVBoxLayout(barra)
        bv.setContentsMargins(6, 8, 6, 8)
        bv.setSpacing(6)
        self.grupo_modos = QButtonGroup(self)
        self.botoes_modo = {}
        for i, (chave, rot) in enumerate(MODOS):
            b = QToolButton()
            b.setObjectName("modo")
            b.setIcon(icones.icone(chave, tam=22))
            b.setIconSize(QSize(22, 22))
            b.setCheckable(True)
            b.setFixedSize(40, 40)
            b.setToolTip(f"{rot} (F{i + 1})")
            b.setChecked(chave == "inspetor")
            b.clicked.connect(lambda _c, k=chave: self.set_modo(k))
            self.grupo_modos.addButton(b)
            self.botoes_modo[chave] = b
            bv.addWidget(b)
        bv.addStretch()
        h.addWidget(barra)

        self.pilha = QStackedWidget()
        self.boas = BoasVindas(self)
        self.pilha.addWidget(self.boas)
        self.pilha.addWidget(self._area_trabalho())
        h.addWidget(self.pilha, 1)
        self.setCentralWidget(central)

        sb = self.statusBar()
        self.st_pos = QLabel()
        self.st_alvo = QLabel()
        self.st_sonda = QLabel()
        self.st_sonda.setFont(tema.fonte_mono(8))
        self.st_zoom = QLabel()
        self.st_render = QLabel()
        self.st_render.setStyleSheet(f"color: {tema.C['acento_forte']};")
        self.st_msg = QLabel()
        self.st_prog = QProgressBar()
        self.st_prog.setFixedWidth(160)
        self.st_prog.setRange(0, 1000)
        self.st_prog.setTextVisible(False)
        self.st_prog.hide()
        for w in (self.st_pos, self.st_alvo, self.st_sonda):
            sb.addWidget(w)
        sb.addPermanentWidget(self.st_render)
        sb.addPermanentWidget(self.st_msg)
        sb.addPermanentWidget(self.st_prog)
        sb.addPermanentWidget(self.st_zoom)

    def _barra_inspetor(self):
        ferr, fh = self._barra(4)
        self.b_mao = self._botao_ferr("mao", "Selecionar / mover (arraste para mover, roda = zoom)")
        self.b_regua = self._botao_ferr("regua", "Régua em µm (R)")
        self.b_comp = self._botao_ferr("comparar", "Comparar: o próximo clique vira o grão B (ou ⇧ clique)")
        self.b_mao.setChecked(True)
        self.b_mao.clicked.connect(lambda: self._ferramenta("mao"))
        self.b_regua.clicked.connect(lambda: self._ferramenta("regua"))
        self.b_comp.clicked.connect(self._alternar_comparar)
        for b in (self.b_mao, self.b_regua):
            fh.addWidget(b)
        fh.addWidget(self._sep())
        fh.addWidget(self.b_comp)
        fh.addWidget(self._sep())
        self._botoes_vista(fh)
        fh.addWidget(self._sep())
        self.b_tab = self._botao_ferr("tabela", "Tabela de grãos (T)")
        self.b_tab.setText(" Tabela")
        self.b_tab.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_tab.toggled.connect(self._mostrar_tabela)
        fh.addWidget(self.b_tab)
        fh.addStretch()
        self.lbl_regua = QLabel()
        self.lbl_regua.setStyleSheet(f"color: {tema.C['selA']};")
        fh.addWidget(self.lbl_regua)
        return ferr

    def _barra_edicao(self):
        ferr, fh = self._barra()
        self.grupo_ed = QButtonGroup(self)
        self.botoes_ed = {}
        for item in FERR_ED:
            if item is None:
                fh.addWidget(self._sep())
                continue
            chave, ic, atalho = item
            nome, dica = FERRAMENTAS[chave]
            b = self._botao_ferr(ic, f"{nome} ({atalho}) — {dica}")
            b.clicked.connect(lambda _c, k=chave: self.ferramenta_edicao(k))
            self.grupo_ed.addButton(b)
            self.botoes_ed[chave] = b
            fh.addWidget(b)
        fh.addWidget(self._sep())
        self._botoes_historico(fh)
        fh.addWidget(self._sep())
        self._botoes_vista(fh)
        fh.addStretch()
        self.sw_ativo = QLabel()
        self.sw_ativo.setFixedSize(14, 14)
        self.lbl_ativo = QLabel()
        fh.addWidget(self.sw_ativo)
        fh.addWidget(self.lbl_ativo)
        return ferr

    def _barra_segmentar(self):
        ferr, fh = self._barra()
        b = self._botao_ferr("mao", "Mover (arraste) · roda = zoom", checavel=False)
        fh.addWidget(b)
        fh.addWidget(self._sep())
        self._botoes_historico(fh, " — inclusive um commit")
        fh.addWidget(self._sep())
        self._botoes_vista(fh)
        fh.addStretch()
        self.sw_seg = QLabel()
        self.sw_seg.setFixedSize(14, 14)
        self.lbl_seg = QLabel()
        fh.addWidget(QLabel("segmentando "))
        fh.addWidget(self.sw_seg)
        fh.addWidget(self.lbl_seg)
        return ferr

    def _barra_relatorio(self):
        ferr, fh = self._barra()
        b = self._botao_ferr("mao", "Mover (arraste) · roda = zoom · clique num grão marca-o nos gráficos",
                             checavel=False)
        fh.addWidget(b)
        fh.addWidget(self._sep())
        self._botoes_vista(fh)
        fh.addWidget(self._sep())
        b = self._botao_ferr("limpar", "Limpar o destaque (Esc)", checavel=False)
        b.clicked.connect(self._limpar_rel)
        fh.addWidget(b)
        fh.addStretch()
        self.lbl_destaque = QLabel()
        self.lbl_destaque.setStyleSheet(f"color: {tema.C['selA']};")
        fh.addWidget(self.lbl_destaque)
        return ferr

    def mostrar_ativo_seg(self, mid):
        m = self.am.mineral(mid) if self.am else None
        if m:
            self.sw_seg.setStyleSheet(f"background:{m.cor}; border-radius:3px; border:1px solid rgba(0,0,0,0.45);")
            self.lbl_seg.setText(f" {m.nome.replace('_', ' ')}  ")

    def _barra(self, espaco=3):
        ferr = QWidget()
        ferr.setObjectName("painel")
        fh = QHBoxLayout(ferr)
        fh.setContentsMargins(8, 4, 8, 4)
        fh.setSpacing(espaco)
        return ferr, fh

    def _botoes_historico(self, fh, extra=""):
        for acao, dica in (("desfazer", f"Desfazer (Ctrl+Z){extra}"), ("refazer", "Refazer (Ctrl+Y)")):
            b = self._botao_ferr(acao, dica, checavel=False)
            b.clicked.connect(lambda _c, a=acao: getattr(self.controle, a)())   # controle nasce depois
            fh.addWidget(b)

    def _botoes_vista(self, fh):
        b_aj = self._botao_ferr("ajustar", "Ajustar à janela (F)", checavel=False)
        b_aj.clicked.connect(lambda: self.canvas.ajustar())
        b_11 = QToolButton()
        b_11.setText("1:1")
        b_11.setToolTip("Pixel real (1)")
        b_11.clicked.connect(lambda: self.canvas.um_para_um())
        fh.addWidget(b_aj)
        fh.addWidget(b_11)

    def _area_trabalho(self):
        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.setChildrenCollapsible(False)
        self.sp_h = sp
        self.camadas = PainelCamadas()
        self.camadas.setMinimumWidth(270)
        self.camadas.mudou.connect(self.recompor)
        self.camadas.soloMudou.connect(self._solo)
        sp.addWidget(self.camadas)

        meio = QWidget()
        self.meio = meio
        mv = QVBoxLayout(meio)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        self.pilha_ferr = QStackedWidget()
        self.pilha_ferr.addWidget(self._barra_inspetor())
        self.pilha_ferr.addWidget(self._barra_edicao())
        self.pilha_ferr.addWidget(self._barra_segmentar())
        self.pilha_ferr.addWidget(self._barra_relatorio())
        self.pilha_ferr.setFixedHeight(40)
        mv.addWidget(self.pilha_ferr)
        linha = QFrame()
        linha.setObjectName("linha")
        mv.addWidget(linha)

        self.sp_v = QSplitter(Qt.Orientation.Vertical)
        self.sp_v.setChildrenCollapsible(False)
        self.canvas = Canvas()
        self.canvas.hover.connect(self._hover)
        self.canvas.clique.connect(self._clique)
        self.canvas.zoomMudou.connect(lambda e: self.st_zoom.setText(f"zoom {e * 100:.0f}%"))
        self.canvas.reguaMudou.connect(
            lambda v: self.lbl_regua.setText("" if v is None else f"régua  {fmt_um(v)}"))
        self.sp_v.addWidget(self.canvas)
        self.tabela = PainelTabela()
        self.tabela.ativado.connect(self._da_tabela)
        self.tabela.fechar.connect(lambda: self.b_tab.setChecked(False))
        self.tabela.hide()
        self.sp_v.addWidget(self.tabela)
        self.sp_v.setSizes([640, 260])
        mv.addWidget(self.sp_v, 1)
        sp.addWidget(meio)

        self.pilha_dir = QStackedWidget()
        self.pilha_dir.setMinimumWidth(330)
        direita = QScrollArea()
        direita.setWidgetResizable(True)
        direita.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ficha = FichaGrao()
        self.ficha.setObjectName("painel")
        self.ficha.modoMudou.connect(lambda _m: self._atualiza_sonda())
        direita.setWidget(self.ficha)
        self.pilha_dir.addWidget(direita)
        self.painel_ed = PainelEdicao()
        self.pilha_dir.addWidget(self.painel_ed)
        self.painel_seg = PainelSegmentar()
        self.pilha_dir.addWidget(self.painel_seg)
        self.painel_rel = PainelRelatorio()
        self.pilha_dir.addWidget(self.painel_rel)
        sp.addWidget(self.pilha_dir)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setStretchFactor(2, 0)
        sp.setSizes([290, 850, 350])
        return sp

    def _botao_ferr(self, nome, dica, checavel=True):
        b = QToolButton()
        b.setIcon(icones.icone(nome, tam=18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(dica)
        b.setCheckable(checavel)
        return b

    @staticmethod
    def _sep():
        s = QFrame()
        s.setFixedSize(1, 20)
        s.setStyleSheet(f"background: {tema.C['borda']};")
        return s

    # ================= atalhos (dependem do modo) =================
    def _atalhos(self):
        ed = lambda fn: (lambda: fn() if self.modo == "edicao" and self.am is not None else None)
        eds = lambda fn: (lambda: fn() if self.modo in ("edicao", "segmentar") and self.am is not None else None)
        ins = lambda fn: (lambda: fn() if self.modo == "inspetor" and self.am is not None else None)
        teclas = [
            (QKeySequence.StandardKey.Open, lambda: self.abrir_arquivo()),
            ("Ctrl+I", self.importar_pasta), ("Ctrl+S", self.salvar), ("Ctrl+Shift+S", self.salvar_como),
            ("Esc", self._esc), ("F", lambda: self.canvas.ajustar()), ("1", lambda: self.canvas.um_para_um()),
            ("M", lambda: self.camadas.alternar_minerais()),
            ("R", ins(lambda: self._ferramenta("mao" if self.canvas.ferramenta == "regua" else "regua"))),
            ("T", ins(lambda: self.b_tab.setChecked(not self.b_tab.isChecked()))),
            ("C", lambda: self._alternar_comparar() if self.modo == "inspetor" else self.canvas.limpar_pontos()),
            ("Ctrl+Z", eds(lambda: self.controle.desfazer())), ("Ctrl+Y", eds(lambda: self.controle.refazer())),
            ("Ctrl+Shift+Z", eds(lambda: self.controle.refazer())),
            ("G", ed(lambda: self.controle.converter_pontos())), ("P", ed(lambda: self.controle.propagar())),
            ("[", ed(lambda: self.painel_ed.mudar_raio(0.8))), ("]", ed(lambda: self.painel_ed.mudar_raio(1.25))),
            ("Return", ed(lambda: self.canvas.fechar_poligono())), ("Enter", ed(lambda: self.canvas.fechar_poligono())),
            ("Backspace", ed(lambda: self.canvas.remover_ultimo_vertice())),
        ]
        teclas += [(f"F{i + 1}", lambda k=k: self.set_modo(k)) for i, (k, _r) in enumerate(MODOS)]
        for item in FERR_ED:
            if item:
                teclas.append((item[2], ed(lambda k=item[0]: self.ferramenta_edicao(k))))
        for seq, fn in teclas:
            QShortcut(QKeySequence(seq), self, activated=fn)

    # ================= modos =================
    def set_modo(self, modo):
        modos = [k for k, _r in MODOS]
        if self.am is None or self._ocupado or modo == self.modo or modo not in modos:
            self.botoes_modo[self.modo].setChecked(True)
            return
        anterior, self.modo = self.modo, modo
        if anterior == "edicao":
            self.controle.sair()
        elif anterior == "segmentar":
            self.seg.sair()
        elif anterior == "relatorio":
            self._sair_relatorio()
        elif anterior == "inspetor":
            self._tab_antes = self.b_tab.isChecked()
            self.b_tab.setChecked(False)
            self.fixado, self.sel_a, self.sel_b, self._hover_sel = False, None, None, None
            self._destaque()
            self.canvas.limpar_regua()
        self.botoes_modo[modo].setChecked(True)
        self.pill_modo.setText(dict(MODOS)[modo])
        i = modos.index(modo)
        self.pilha_ferr.setCurrentIndex(i)
        self.pilha_dir.setCurrentIndex(i)
        if modo == "edicao":
            self.ferramenta_edicao(self._ferr_ed)
            self.painel_ed.atualizar_historico(self.controle.editor.hist)
            self.recompor()
        elif modo == "segmentar":
            self.canvas.set_ferramenta("mao")
            self.recompor()
            self.seg.entrar()
        else:                        # Inspetor e Relatório precisam dos grãos em dia com as edições
            self._ferramenta("mao")
            if modo == "relatorio":
                # a barra da Edição (larga) não pode segurar a largura do meio: o painel precisa de espaço
                self.pilha_ferr.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                self._tam_antes = self.sp_h.sizes()
                tot, esq = sum(self._tam_antes), self._tam_antes[0]
                d = max(560, int(tot * 0.40))
                self.sp_h.setSizes([esq, max(300, tot - esq - d), d])
            if self.controle.editor and self.controle.editor.versao != self.versao_stats:
                self._recalcular()                  # -> _objetos_novos -> rel.entrar()
            else:
                self.recompor()
                if modo == "relatorio":
                    self.rel.entrar()
            if modo == "inspetor" and getattr(self, "_tab_antes", False):
                self.b_tab.setChecked(True)

    def _sair_relatorio(self):
        self.rel.sair()
        self._sel_rel(None)
        self.painel_cheio(False)
        self.pilha_ferr.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if self._tam_antes:
            self.sp_h.setSizes(self._tam_antes)
            self._tam_antes = None

    # ---- relatório: destaque no canvas e painel cheio ----
    def set_destaque_rel(self, s, desc=""):
        self.canvas.set_camada("rel", *(s or (None,)))
        self.lbl_destaque.setText(f"destaque: {desc}  ·  Esc limpa  " if desc else "")

    def _sel_rel(self, sel):
        """Grão/mineral escolhido no modo Relatório (clique no canvas ou num ponto do Na-K-Ca)."""
        if sel is not None and sel[0] == "obj" and self.ob is not None:
            x0, y0, x1, y1 = (int(v) for v in self.ob.bbox[sel[1]])
            s = sobreposicao(self.ob.objid[y0:y1, x0:x1] == sel[1], cor=hex_rgb(tema.C["selA"]), alfa=60,
                             origem=(x0, y0))
            self.canvas.set_camada("A", *s)
            self.canvas.set_caixa("A", self.ob.bbox[sel[1]], tema.C["selA"])
        else:
            self.canvas.set_camada("A", None)
            self.canvas.set_caixa("A", None)
        if self.modo == "relatorio":
            self.rel.clique_canvas(sel)

    def selecionar_objeto_rel(self, oid):
        self._sel_rel(("obj", oid))
        self.canvas.zoom_para(*self.ob.bbox[oid])

    def _limpar_rel(self):
        self.rel.destacar(None)
        self._sel_rel(None)

    def painel_cheio(self, on):
        on = bool(on) and self.modo == "relatorio"
        self.meio.setVisible(not on)
        self.camadas.setVisible(not on)
        if self.painel_rel.b_cheio.isChecked() != on:
            self.painel_rel.b_cheio.setChecked(on)

    def ferramenta_edicao(self, chave):
        self._ferr_ed = chave
        self.canvas.set_ferramenta(chave)
        if chave in self.botoes_ed:
            self.botoes_ed[chave].setChecked(True)
        self.painel_ed.set_ferramenta(chave)

    def mostrar_ativo(self, mid):
        m = self.am.mineral(mid) if self.am else None
        if m:
            self.sw_ativo.setStyleSheet(f"background:{m.cor}; border-radius:3px; border:1px solid rgba(0,0,0,0.45);")
            self.lbl_ativo.setText(f" {m.nome.replace('_', ' ')}  ")

    def _recalcular(self):
        am, v0 = self.am, self.controle.editor.versao
        if self.modo == "relatorio":
            self.painel_rel.set_estado("recalculando…")
        self._rodar("Recalculando grãos", lambda prog: objetos.calcular(am, 3, prog),
                    lambda ob: self._objetos_novos(ob, v0))

    def _objetos_novos(self, ob, v0):
        self.ob = ob
        self.comp = Compositor(self.am, ob, tema.CORES_WENTWORTH)
        self.render.definir(self.comp)
        self.camadas.atualizar_objetos(self.am, ob, self.comp)
        self.tabela.definir(self.am, ob)
        self.versao_stats = v0
        self._soltar()
        self.recompor()
        self.st_msg.setText(f"{fmt(ob.n)} objetos (recalculados após a edição)")
        if self.modo == "relatorio":
            self.rel.entrar()

    def marcar_sujo(self, sujo=True):
        self.sujo = sujo
        self.painel_ed.set_sujo(sujo, Path(self.am.caminho).name if (self.am and self.am.caminho) else None)
        self._titulo()

    # ================= arquivos =================
    def _recentes(self):
        r = self.cfg.value("recentes", []) or []
        r = [r] if isinstance(r, str) else list(r)
        return [p for p in r if Path(p).exists()]

    def _add_recente(self, caminho):
        r = [str(caminho)] + [p for p in self._recentes() if p != str(caminho)]
        self.cfg.setValue("recentes", r[:8])
        self.boas.atualizar(r[:8])

    def _dir_inicial(self):
        d = self.cfg.value("ultimo_dir", "")
        return d if d and Path(d).exists() else str(Path.home())

    def _pode_descartar(self):
        """Pergunta antes de perder edições não salvas. True = pode seguir."""
        if not self.sujo:
            return True
        r = QMessageBox.question(
            self, "Alterações não salvas",
            "Há edições não salvas nesta amostra. Salvar antes de continuar?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self._salvar_sincrono()
        return True

    def abrir_arquivo(self, caminho=None):
        if self._ocupado or not self._pode_descartar():
            return
        if not caminho:
            caminho, _ = QFileDialog.getOpenFileName(
                self, "Abrir pacote MudMap", self._dir_inicial(), "Pacote MudMap (*.mudmap)")
            if not caminho:
                return
        caminho = Path(caminho)
        self.cfg.setValue("ultimo_dir", str(caminho.parent))

        def trabalho(prog):
            am = pacote.abrir(caminho, _sub(prog, 0, 0.5))
            return am, objetos.calcular(am, 3, _sub(prog, 0.5, 1.0))
        self._rodar(f"Abrindo {caminho.name}", trabalho, lambda r: self._carregado(r, caminho))

    def importar_pasta(self):
        if self._ocupado or not self._pode_descartar():
            return
        pasta = QFileDialog.getExistingDirectory(self, "Importar pasta do projeto MudMap ou pasta EDS",
                                                 self._dir_inicial())
        if not pasta:
            return
        pasta = Path(pasta)
        self.cfg.setValue("ultimo_dir", str(pasta))
        raiz = importar.raiz_do_projeto(pasta)
        if raiz is not None and not importar.elementos_da_pasta(pasta):
            fontes = importar.listar_sitios(raiz)
            if not fontes:
                QMessageBox.warning(self, "Importar", "Nenhum sítio encontrado neste projeto.")
                return
            pref = pasta.name if pasta.parent.name == "sitios" else None
            dlg = DialogoSitios(fontes, raiz, pref, self)
            if dlg.exec() != DialogoSitios.DialogCode.Accepted or dlg.escolhida() is None:
                return
            fonte = dlg.escolhida()

            def trabalho(prog):
                am = importar.importar_sitio(fonte, _sub(prog, 0, 0.7))
                return am, objetos.calcular(am, 3, _sub(prog, 0.7, 1.0))
            self._rodar(f"Importando sítio {fonte.sitio}", trabalho, lambda r: self._carregado(r, None))
        elif importar.elementos_da_pasta(pasta):
            def trabalho(prog):
                am = importar.importar_pasta_eds(pasta, _sub(prog, 0, 0.7))
                return am, objetos.calcular(am, 3, _sub(prog, 0.7, 1.0))
            self._rodar(f"Importando {pasta.name}", trabalho, lambda r: self._carregado(r, None))
        else:
            QMessageBox.information(
                self, "Importar",
                "Esta pasta não é de um projeto MudMap (config/classificacao.yaml) nem contém mapas "
                "elementais (.tif). Escolha a pasta do projeto, uma pasta em sitios/ ou uma pasta EDS.")

    def salvar(self):
        if self.am is None or self._ocupado:
            return
        if self.am.caminho and str(self.am.caminho).lower().endswith(pacote.EXT):
            am, cam = self.am, self.am.caminho
            self._rodar("Salvando", lambda prog: pacote.salvar(am, cam, prog), self._salvo)
        else:
            self.salvar_como()

    def salvar_como(self):
        if self._ocupado or self.am is None:
            return
        base = Path(self.am.caminho).parent if self.am.caminho else Path(self._dir_inicial())
        sug = base / f"{self.am.amostra}_{self.am.sitio}{pacote.EXT}"
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar pacote MudMap", str(sug),
                                                 "Pacote MudMap (*.mudmap)")
        if not caminho:
            return
        am = self.am
        self._rodar("Salvando", lambda prog: pacote.salvar(am, caminho, prog), self._salvo)

    def _salvar_sincrono(self):
        """Salvamento bloqueante (usado ao fechar). True se salvou."""
        cam = self.am.caminho if (self.am.caminho and str(self.am.caminho).lower().endswith(pacote.EXT)) else None
        if cam is None:
            base = Path(self._dir_inicial()) / f"{self.am.amostra}_{self.am.sitio}{pacote.EXT}"
            cam, _ = QFileDialog.getSaveFileName(self, "Salvar pacote MudMap", str(base),
                                                 "Pacote MudMap (*.mudmap)")
            if not cam:
                return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._salvo(pacote.salvar(self.am, cam))
        finally:
            QApplication.restoreOverrideCursor()
        return True

    def _salvo(self, caminho):
        self._add_recente(caminho)
        self.cfg.setValue("ultimo_dir", str(Path(caminho).parent))
        self.marcar_sujo(False)
        self.st_msg.setText(f"Salvo em {Path(caminho).name}")
        if self.modo == "edicao":
            self.painel_ed.set_msg(f"Salvo em {Path(caminho).name} (versão anterior guardada no arquivo).", "ok")

    def exportar_estado(self):
        if self.am is None or self._ocupado:
            return
        destino = exportar_estado.destino_padrao(self.am)
        if destino is None:
            d = QFileDialog.getExistingDirectory(self, "Escolha a pasta estado/ do projeto", self._dir_inicial())
            if not d:
                return
            destino = Path(d)
        try:
            mud, difere = exportar_estado.comparar(self.am, destino)
        except ValueError as e:
            QMessageBox.warning(self, "Exportar", str(e))
            return
        if difere == 0:
            QMessageBox.information(self, "Exportar", f"{destino / 'rotulos.npy'} já é igual aos rótulos do app.")
            return
        ativo, _raiz = exportar_estado.sitio_ativo(destino)
        aviso = ""
        if ativo is not None and str(ativo) != str(self.am.sitio):
            aviso = (f"\n\nATENÇÃO: o sítio ATIVO do projeto é {ativo}, e esta amostra é o sítio "
                     f"{self.am.sitio}. Confira se a pasta de destino é a certa.")
        linhas = "\n".join(f"   • {n}: {fmt(a)} → {fmt(b)} px" for n, (a, b) in mud.items())
        r = QMessageBox.question(
            self, "Exportar para estado/",
            f"Gravar os rótulos do app em:\n{destino / 'rotulos.npy'}\n\n{fmt(difere)} px diferentes.\n"
            f"{linhas}\n\nO atual vai para rotulos_prev.npy (backup) e o progresso.json é atualizado." + aviso)
        if r != QMessageBox.StandardButton.Yes:
            return
        res = exportar_estado.exportar(self.am, destino)
        msg = f"Exportado: {res['destino']} (backup em rotulos_prev.npy)."
        self.st_msg.setText(msg)
        if self.modo == "edicao":
            self.painel_ed.set_msg(msg, "ok")

    def _rodar(self, rotulo, fn, ao_terminar):
        """Tarefa longa em segundo plano (abrir, salvar, grãos, propagar, k-means…): barra de
        progresso, cursor ocupado e ações de arquivo travadas até terminar."""
        self._ocupado = True
        for a in (self.a_abrir, self.a_importar, self.a_salvar, self.a_exportar):
            a.setEnabled(False)
        self.st_prog.setValue(0)
        self.st_prog.show()
        self.st_msg.setText(rotulo + "…")
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        def prog(f, m):
            self.st_prog.setValue(int(f * 1000))
            self.st_msg.setText(f"{rotulo} — {m}")

        def fim(r):
            self._fim_tarefa()
            ao_terminar(r)

        def erro(curta, detalhe):
            self._fim_tarefa()
            if self.modo == "edicao" and not detalhe:          # erro "de usuário": na linha do painel
                self.painel_ed.set_msg(curta, "erro")
                return
            box = QMessageBox(QMessageBox.Icon.Warning, "Não deu certo", curta, parent=self)
            if detalhe:
                box.setDetailedText(detalhe)
            box.exec()
        self.tarefas.pedir(fn, fim, erro, prog)

    def _fim_tarefa(self):
        QApplication.restoreOverrideCursor()
        self._ocupado = False
        self.st_prog.hide()
        self.st_msg.setText("")
        self.a_abrir.setEnabled(True)
        self.a_importar.setEnabled(True)
        self.a_salvar.setEnabled(self.am is not None)
        self.a_exportar.setEnabled(self.am is not None)

    def _carregado(self, res, caminho):
        am, ob = res
        self.am, self.ob = am, ob
        self.comp = Compositor(am, ob, tema.CORES_WENTWORTH)
        self.sel_a = self.sel_b = self._hover_sel = None
        self.fixado = False
        self.controle.sair()                      # (amostra nova sempre abre no Inspetor)
        self.seg.sair()
        if self.modo == "relatorio":
            self._sair_relatorio()
        self.modo = "inspetor"
        self.botoes_modo["inspetor"].setChecked(True)
        self.pill_modo.setText("Inspetor")
        self.pilha_ferr.setCurrentIndex(0)
        self.pilha_dir.setCurrentIndex(0)
        self._ferramenta("mao")
        self.canvas.limpar()
        self.canvas.msg_vazio = "Compondo a imagem…"
        self.canvas.pixel_um = am.pixel_um
        self.render.definir(self.comp)
        self.camadas.definir(am, ob, self.comp)
        self.tabela.definir(am, ob)
        self.controle.definir(am)
        self.seg.definir(am)
        self.rel.definir(am)
        self.versao_stats = 0
        self.pilha.setCurrentIndex(1)
        self.a_salvar.setEnabled(True)
        self.a_exportar.setEnabled(True)
        self._primeira = True
        self.marcar_sujo(False)
        self._pedir_render()
        if caminho:
            self._add_recente(caminho)
        self._titulo()
        if ob.n:
            maior = int(np.argmax(ob.area[1:])) + 1
            self._fixar(("obj", maior), centralizar=False)
        self.st_msg.setText(f"{fmt(ob.n)} objetos carregados")

    def _titulo(self):
        am = self.am
        if am is None:
            return
        arq = Path(am.caminho).name if am.caminho else "importado — não salvo"
        marca = "● " if self.sujo else ""
        self.setWindowTitle(f"{marca}MudMap Studio — {am.titulo}  [{arq}]")
        self.lbl_amostra.setText(f"{marca}{am.titulo}   ·   {arq}")

    # ================= visual =================
    def _visual_atual(self):
        v = self.camadas.visual()
        ed = self.controle.editor
        v.por_rotulo = self.modo not in ("inspetor", "relatorio") or (ed is not None and ed.versao != self.versao_stats)
        v.versao = ed.versao if ed else 0
        return v

    def recompor(self):
        self._timer_recompor.start()

    def _pedir_render(self):
        if self.comp is not None:
            self.render.solicitar(self._visual_atual())

    def _ao_render(self, niveis, info):
        v = info.get("visual")
        ed = self.controle.editor
        if v is not None and ed is not None and v.versao != ed.versao:
            # rótulos mudaram durante a composição: descarta (os remendos já estão na tela);
            # só recompõe se o visual pedido era diferente do exibido
            base = lambda x: dataclasses.replace(x, versao=0) if x is not None else None
            if not self.canvas.tem_imagem or base(v) != base(self._visual):
                self.recompor()
            return
        h, w = self.am.shape
        self.canvas.set_niveis(niveis, manter_vista=not self._primeira, tamanho=(w, h))
        self._primeira = False
        if info.get("previa"):
            self.st_render.setText("prévia · refinando…")
        self._visual = v
        if v is not None and v.fundo == "canal":
            self.camadas.set_canal_stats(info["canal_stats"], info["canal_lim"], v)
            lo, hi = info["canal_lim"]
            tit = f"{v.canal_expr} · {'fração' if v.canal_tipo == 'frac' else 'bruto'}" + \
                  (f" · r={v.canal_raio}" if v.canal_raio > 1 else "")
            self.canvas.set_legenda(("rampa", tit, cores.lut(v.canal_cmap), lo, hi))
        elif v is not None and v.fundo == "aditivo" and v.camadas:
            self.canvas.set_legenda(("chips", [(c.el, c.cor) for c in v.camadas]))
        else:
            self.canvas.set_legenda(None)
        self._atualiza_sonda()

    def _erro_render(self, msg, v):
        if v is not None and v.fundo == "canal" and "\n" not in msg.strip():
            self.camadas.set_erro_canal(msg)
            return
        box = QMessageBox(QMessageBox.Icon.Warning, "Não foi possível compor a imagem",
                          msg.strip().splitlines()[-1], parent=self)
        box.setDetailedText(msg)
        box.exec()

    def aguardar_render(self, limite_s=60):
        """Espera a fila de renderização (e tarefas) esvaziar — usado no autoteste."""
        import time
        t0 = time.time()
        QApplication.processEvents()
        while (self.render.ativo or self._timer_recompor.isActive() or self._ocupado or
               self.seg.ocupado) and time.time() - t0 < limite_s:
            QApplication.processEvents()
            time.sleep(0.01)
        QApplication.processEvents()

    def closeEvent(self, e):
        if not self._pode_descartar():
            e.ignore()
            return
        for s in (self.render, self.seg, self.rel, self.tarefas):
            s.parar()
        super().closeEvent(e)

    # ================= inspetor: seleção =================
    def _destaque(self):
        for chave, sel, cor in (("A", self.sel_a if self.fixado else self._hover_sel,
                                 tema.C["selA"] if self.fixado else tema.C["acento_forte"]),
                                ("B", self.sel_b, tema.C["selB"])):
            if sel is not None and sel[0] == "obj" and self.modo == "inspetor":
                x0, y0, x1, y1 = (int(v) for v in self.ob.bbox[sel[1]])
                s = sobreposicao(self.ob.objid[y0:y1, x0:x1] == sel[1], cor=hex_rgb(cor), alfa=60,
                                 origem=(x0, y0))
                self.canvas.set_camada(chave, *s)
                self.canvas.set_caixa(chave, self.ob.bbox[sel[1]], cor)
            else:
                self.canvas.set_camada(chave, None)
                self.canvas.set_caixa(chave, None)

    def _stats_em_dia(self):
        ed = self.controle.editor
        return ed is None or ed.versao == self.versao_stats

    def _sel_em(self, x, y):
        if x < 0 or self.ob is None:
            return None
        if self._stats_em_dia():
            oid = int(self.ob.objid[y, x])
            if oid:
                return ("obj", oid)
        mid = int(self.am.rotulos[y, x])
        return ("min", mid) if mid else None

    def _mostrar_ficha(self):
        a = self.sel_a if self.fixado else self._hover_sel
        self.ficha.mostrar(self.am, self.ob, a, self.sel_b if self.fixado else None, self.fixado)
        self._destaque()

    def _fixar(self, sel, centralizar=False):
        self.sel_a, self.sel_b, self.fixado = sel, None, True
        self._mostrar_ficha()
        if sel[0] == "obj":
            self.tabela.selecionar(sel[1])
            if centralizar:
                self.canvas.zoom_para(*self.ob.bbox[sel[1]])

    def _soltar(self):
        self.fixado = False
        self.sel_a = self.sel_b = None
        self._mostrar_ficha()

    # ================= interação =================
    def _hover(self, x, y):
        if self.am is None:
            return
        if x < 0:
            self.st_pos.setText("")
            self.st_alvo.setText("")
            self.st_sonda.setText("")
            if self.modo == "inspetor" and not self.fixado and self._hover_sel is not None:
                self._hover_sel = None
                self._mostrar_ficha()
            return
        px = self.am.pixel_um
        self.st_pos.setText(f"x {x}  y {y}  ·  {fmt(x * px, 2)} × {fmt(y * px, 2)} µm")
        sel = self._sel_em(x, y)
        if sel is None:
            self.st_alvo.setText("sem classe" if self.am.mascara[y, x] else "fora da amostra (resina)")
        elif sel[0] == "obj":
            m = self.am.mineral(int(self.ob.mineral[sel[1]]))
            self.st_alvo.setText(f"{m.nome.replace('_', ' ')} · objeto #{sel[1]}")
        else:
            m = self.am.mineral(sel[1])
            fora = "" if self.am.mascara[y, x] else " · fora da amostra"
            self.st_alvo.setText(f"{m.nome.replace('_', ' ') if m else sel[1]}"
                                 f"{' · fino' if self.modo == 'inspetor' else ''}{fora}")
        if self.am.clusters is not None and self.am.clusters[y, x]:
            k = int(self.am.clusters[y, x])
            nome = (self.am.clusters_info or {}).get("nomes", {}).get(str(k), "?")
            self.st_alvo.setText(self.st_alvo.text() + f"  ·  cluster {k} ({nome.replace('_', ' ')})")
        if self.modo == "segmentar" and self.seg.res is not None:
            self.st_alvo.setText(self.st_alvo.text() + ("  ·  NO candidato" if self.seg.res["cand"][y, x]
                                                        else "  ·  fora do candidato"))
        self._xy = (x, y)
        self._atualiza_sonda()
        if self.modo == "inspetor" and not self.fixado and sel != self._hover_sel:
            self._hover_sel = sel
            self._mostrar_ficha()

    def _atualiza_sonda(self):
        if self.am is None or not hasattr(self, "_xy"):
            return
        x, y = self._xy
        if self.ficha.modo == "frac":
            v = self.am.frac_pixel(y, x)
            txt = "  ".join(f"{e} {v[i]:.2f}".replace(".", ",") for i, e in enumerate(self.am.elementos))
        else:
            v = self.am.raw_pixel(y, x)
            txt = "  ".join(f"{e} {v[i]:.0f}" for i, e in enumerate(self.am.elementos))
        vis = self._visual
        if vis is not None and vis.fundo == "canal" and self.comp is not None:
            c = self.comp.canal_em_cache(vis.canal_expr, vis.canal_tipo, vis.canal_raio)
            if c is not None:
                val = float(c[0][y, x])
                txt += f"   │  {vis.canal_expr} = " + ("—" if np.isnan(val) else f"{val:.3f}".replace(".", ","))
        self.st_sonda.setText(txt)

    def _clique(self, x, y, mods):
        if self.am is None:
            return
        if self.modo == "edicao":
            self.controle.clique_mao(x, y)
            return
        if self.modo == "relatorio":
            self._sel_rel(self._sel_em(x, y))
            return
        sel = self._sel_em(x, y)
        comparar = self.modo_comparar or bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if comparar and self.fixado and sel is not None and sel != self.sel_a:
            self.sel_b = sel
            self._mostrar_ficha()
            if self.modo_comparar:
                self.b_comp.setChecked(False)
                self.modo_comparar = False
            return
        if sel is None:
            self._soltar()
        else:
            self._fixar(sel)

    def _da_tabela(self, oid):
        self._fixar(("obj", oid), centralizar=True)

    def _solo(self, mid):
        self.tabela.set_mineral(mid)

    def _esc(self):
        if self.modo == "edicao":
            self.canvas.cancelar_forma()
            self.painel_ed.set_msg("")
            return
        if self.modo == "relatorio":
            self._limpar_rel()
            return
        self.canvas.limpar_regua()
        if self.modo_comparar:
            self._alternar_comparar()
        elif self.sel_b is not None:
            self.sel_b = None
            self._mostrar_ficha()
        else:
            self._soltar()

    def _ferramenta(self, f):
        self.canvas.set_ferramenta(f)
        self.b_mao.setChecked(f == "mao")
        self.b_regua.setChecked(f == "regua")
        if f != "regua":
            self.canvas.limpar_regua()

    def _alternar_comparar(self):
        self.modo_comparar = not self.modo_comparar
        self.b_comp.setChecked(self.modo_comparar)
        if self.modo_comparar:
            self._ferramenta("mao")
            self.st_msg.setText("Comparar: clique no grão B")
        else:
            self.st_msg.setText("")

    def _mostrar_tabela(self, on):
        self.tabela.setVisible(on)
        if on and self.sel_a and self.sel_a[0] == "obj":
            self.tabela.selecionar(self.sel_a[1])

    # ================= arrastar e soltar =================
    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(pacote.EXT) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(pacote.EXT):
                self.abrir_arquivo(u.toLocalFile())
                break
