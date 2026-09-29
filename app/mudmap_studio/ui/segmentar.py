"""Modo Segmentar: candidato de um mineral pelas regras da config (parâmetros editáveis ao
vivo), prévia sobre a imagem, comparação com o que já está rotulado (desenho do operador),
calibração, commit (desfazível) e gravação dos parâmetros na config; k-means."""
import copy
import time

import numpy as np
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from ..nucleo import config_texto, cores
from ..nucleo import segmentacao as sg
from . import tema
from .comum import (Mensagem, PainelRolavel, Secao, Segmentado, botao_seg, botao_x, descartar, fmt,
                    rgba_para_qimage, sobreposicao)
from .dialogos import Servico
from .comum import botao as _botao, icone_cor as _icone_cor, mudo as _mudo


# ======================= editores de parâmetros =======================
class _LinhaCond(QWidget):
    """Condição de regra por fração: canal + expressão ('>0.12', '<0.05', '0.25 - 0.45')."""
    mudou = pyqtSignal()
    remover = pyqtSignal(object)

    def __init__(self, canal="", expr=""):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.canal = QLineEdit(canal)
        self.canal.setPlaceholderText("Ca, Si-Mg, Al/Si")
        self.expr = QLineEdit(expr)
        self.expr.setPlaceholderText(">0.12")
        for w, st in ((self.canal, 3), (self.expr, 2)):
            w.editingFinished.connect(self.mudou.emit)
            h.addWidget(w, st)
        b = botao_x("Remover condição")
        b.clicked.connect(lambda: self.remover.emit(self))

        h.addWidget(b)


class _Alterna(QPushButton):
    """Botão compacto que alterna entre opções a cada clique (raw↔frac, >↔<, q↔v)."""
    mudou = pyqtSignal()

    def __init__(self, opcoes, valor, dica="", largura=34):
        super().__init__(valor if valor in opcoes else opcoes[0])
        self.opcoes = opcoes
        self.setObjectName("mini")
        self.setFixedSize(largura, 22)
        self.setToolTip(dica)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._proximo)

    def _proximo(self):
        self.setText(self.opcoes[(self.opcoes.index(self.text()) + 1) % len(self.opcoes)])
        self.mudou.emit()

    def valor(self):
        return self.text()


class _LinhaCondGrupo(QWidget):
    """Condição de grupo: {canal, tipo raw|frac, op > <, q | v}."""
    mudou = pyqtSignal()
    remover = pyqtSignal(object)

    def __init__(self, c):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)
        self.canal = QLineEdit(str(c.get("canal", "")))
        self.canal.setPlaceholderText("Si")
        self.canal.setFixedWidth(62)
        self.tipo = _Alterna(["raw", "frac"], c.get("tipo", "raw"),
                             "raw = intensidade bruta · frac = fração de cátions (clique alterna)", 40)
        self.op = _Alterna([">", "<"], c.get("op", ">"), "maior / menor que (clique alterna)", 24)
        self.qv = _Alterna(["q", "v"], "v" if "v" in c else "q",
                           "q = quantil na amostra · v = valor absoluto, estável entre sítios (clique alterna)", 24)
        self.val = QDoubleSpinBox()
        self.val.setDecimals(3)
        self.val.setRange(-1000, 1000)
        self.val.setSingleStep(0.05)
        self.val.setValue(float(c.get("v", c.get("q", 0.5))))
        self.val.setMinimumWidth(64)
        self.canal.editingFinished.connect(self.mudou.emit)
        for w in (self.tipo, self.op, self.qv):
            w.mudou.connect(self.mudou.emit)
        self.val.editingFinished.connect(self.mudou.emit)
        for w in (self.canal, self.tipo, self.op, self.qv):
            h.addWidget(w)
        h.addWidget(self.val, 1)
        b = botao_x("Remover condição")

        b.clicked.connect(lambda: self.remover.emit(self))
        h.addWidget(b)

    def valor(self):
        d = {"canal": self.canal.text().strip(), "tipo": self.tipo.valor(), "op": self.op.valor()}
        d[self.qv.valor()] = round(self.val.value(), 4)
        return d


class _Grupo(QWidget):
    mudou = pyqtSignal()
    remover = pyqtSignal(object)

    def __init__(self, g):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(3)
        h = QHBoxLayout()
        self.nome = QLineEdit(str(g.get("nome", "grupo")))
        self.nome.setToolTip("Nome do grupo (sub-modelo)")
        self.nome.editingFinished.connect(self.mudou.emit)
        h.addWidget(self.nome, 1)
        h.addWidget(_mudo("suavizar r", 8.5))
        self.r = QSpinBox()
        self.r.setRange(0, 101)
        self.r.setValue(int(g.get("suavizar", 15)))
        self.r.setToolTip("Janela da média mascarada (px)")
        self.r.editingFinished.connect(self.mudou.emit)
        h.addWidget(self.r)
        b = botao_x("Remover grupo")

        b.clicked.connect(lambda: self.remover.emit(self))
        h.addWidget(b)
        v.addLayout(h)
        self.box = QVBoxLayout()
        self.box.setSpacing(2)
        v.addLayout(self.box)
        self.linhas = []
        for c in g.get("cond", []):
            self._add(c)
        b = botao_seg("+ condição")

        b.clicked.connect(lambda: (self._add({"canal": "", "tipo": "raw", "op": ">", "q": 0.5})))
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)

    def _add(self, c):
        ln = _LinhaCondGrupo(c)
        ln.mudou.connect(self.mudou.emit)
        ln.remover.connect(self._rem)
        self.box.addWidget(ln)
        self.linhas.append(ln)

    def _rem(self, ln):
        self.linhas.remove(ln)
        descartar([ln])
        self.mudou.emit()

    def valor(self):
        return {"nome": self.nome.text().strip() or "grupo", "suavizar": self.r.value(),
                "cond": [l.valor() for l in self.linhas if l.valor()["canal"]]}


# ======================= painel =======================
class PainelSegmentar(PainelRolavel):
    parametrosMudaram = pyqtSignal()
    mineralMudou = pyqtSignal(int)
    pedido = pyqtSignal(str, object)
    visaoMudou = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        L = self.L

        self.am = None
        self.params = {}
        self._bloq = False

        t = QLabel("Segmentar")
        t.setObjectName("titulo")
        L.addWidget(t)
        self.msg = Mensagem()
        L.addWidget(self.msg)

        s = Secao("Mineral")
        self.cb_min = QComboBox()
        self.cb_min.currentIndexChanged.connect(lambda _i: None if self._bloq else self.mineralMudou.emit(self.mineral()))
        s.add(self.cb_min)
        self.l_cfg = _mudo("", 8.5)
        s.add(self.l_cfg)
        self.l_ja = _mudo("", 8.5)
        s.add(self.l_ja)
        b = _botao("Restaurar parâmetros da config", "Descarta as mudanças e volta aos parâmetros gravados")
        b.clicked.connect(lambda: self.mineralMudou.emit(self.mineral()))
        s.add(b)
        L.addWidget(s)

        s = Secao("Fonte do candidato")
        self.seg_fonte = Segmentado([("regra", "Regra"), ("mapa", "Mapa"), ("cluster", "Cluster")])
        self.seg_fonte.escolhido.connect(self._fonte)
        s.add(self.seg_fonte)
        self.w_regra = QWidget()
        vr = QVBoxLayout(self.w_regra)
        vr.setContentsMargins(0, 4, 0, 0)
        vr.addWidget(_mudo("Condições em fração de cátions (todas exigidas). Aceita A-B, A/B, A+B "
                           "e faixa '0.25 - 0.45'.", 8))
        self.box_cond = QVBoxLayout()
        self.box_cond.setSpacing(2)
        vr.addLayout(self.box_cond)
        b = botao_seg("+ condição")

        b.clicked.connect(lambda: (self._add_cond("", ""), None))
        vr.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        s.add(self.w_regra)
        self.w_mapa = QWidget()
        vm = QVBoxLayout(self.w_mapa)
        vm.setContentsMargins(0, 4, 0, 0)
        self.seg_modelo = Segmentado([("grupos", "Por região (grupos)"), ("pixel", "Por pixel (mapas_seg)")])
        self.seg_modelo.escolhido.connect(self._modelo)
        vm.addWidget(self.seg_modelo)
        self.w_grupos = QWidget()
        vg = QVBoxLayout(self.w_grupos)
        vg.setContentsMargins(0, 2, 0, 0)
        vg.addWidget(_mudo("União de sub-modelos; cada grupo = E de condições sobre mapas suavizados "
                           "(média mascarada de raio r). canal · raw/frac · > < · q (quantil) ou v (valor).", 8))
        self.box_grupos = QVBoxLayout()
        vg.addLayout(self.box_grupos)
        hg = QHBoxLayout()
        b = botao_seg("+ grupo")

        b.clicked.connect(self._novo_grupo)
        hg.addWidget(b)
        hg.addStretch()
        hg.addWidget(_mudo("só o grupo", 8.5))
        self.cb_so_grupo = QComboBox()
        self.cb_so_grupo.currentIndexChanged.connect(lambda _i: self._mudou())
        hg.addWidget(self.cb_so_grupo)
        vg.addLayout(hg)
        vm.addWidget(self.w_grupos)
        self.w_pixel = QWidget()
        vp = QGridLayout(self.w_pixel)
        vp.setContentsMargins(0, 2, 0, 0)
        vp.addWidget(_mudo("Mapas", 8.5), 0, 0)
        self.ed_mapas = QLineEdit()
        self.ed_mapas.setPlaceholderText("Ca, S")
        self.ed_mapas.editingFinished.connect(self._mudou)
        vp.addWidget(self.ed_mapas, 0, 1)
        vp.addWidget(_mudo("Modo", 8.5), 1, 0)
        self.cb_modo = QComboBox()
        self.cb_modo.addItems(["interseccao", "soma", "convergencia"])
        self.cb_modo.currentIndexChanged.connect(lambda _i: self._mudou())
        vp.addWidget(self.cb_modo, 1, 1)
        vp.addWidget(_mudo("Limiar", 8.5), 2, 0)
        hl = QHBoxLayout()
        self.cb_limiar = QComboBox()
        self.cb_limiar.addItems(["otsu", "quantil"])
        self.cb_limiar.currentIndexChanged.connect(lambda _i: self._mudou())
        self.sp_q = QDoubleSpinBox()
        self.sp_q.setRange(0, 1)
        self.sp_q.setSingleStep(0.05)
        self.sp_q.setDecimals(3)
        self.sp_q.editingFinished.connect(self._mudou)
        hl.addWidget(self.cb_limiar)
        hl.addWidget(self.sp_q)
        vp.addLayout(hl, 2, 1)
        vm.addWidget(self.w_pixel)
        s.add(self.w_mapa)
        self.w_cluster = QWidget()
        self.box_cl = QVBoxLayout(self.w_cluster)
        self.box_cl.setContentsMargins(0, 4, 0, 0)
        self.box_cl.setSpacing(1)
        self.chk_cl = []
        s.add(self.w_cluster)
        self.chk_dissem = QCheckBox("Disseminado (não limpar objetos < area_min)")
        self.chk_dissem.toggled.connect(self._mudou)
        s.add(self.chk_dissem)
        L.addWidget(s)

        s = Secao("Forma (pós-filtro)")
        self.chk_forma = QCheckBox("Aplicar forma (senão: limpeza genérica < area_min)")
        self.chk_forma.toggled.connect(self._mudou)
        s.add(self.chk_forma)
        g = QGridLayout()
        self.sp_close = QSpinBox()
        self.sp_close.setRange(0, 30)
        self.sp_amin = QSpinBox()
        self.sp_amin.setRange(0, 1000000)
        self.sp_ecc = QDoubleSpinBox()
        self.sp_ecc.setRange(0, 1)
        self.sp_ecc.setSingleStep(0.02)
        self.sp_ecc.setDecimals(2)
        for i, (rot, w) in enumerate((("fechar (r)", self.sp_close), ("área mín (px)", self.sp_amin),
                                      ("excentric. mín", self.sp_ecc))):
            g.addWidget(_mudo(rot, 8.5), i, 0)
            g.addWidget(w, i, 1)
            w.editingFinished.connect(self._mudou)
        s.add(g)
        h = QHBoxLayout()
        self.chk_convex = QCheckBox("convexo")
        self.chk_maior = QCheckBox("maior")
        self.chk_preencher = QCheckBox("preencher")
        for c in (self.chk_convex, self.chk_maior, self.chk_preencher):
            c.toggled.connect(self._mudou)
            h.addWidget(c)
        s.add(h)
        L.addWidget(s)

        s = Secao("Candidato")
        h = QHBoxLayout()
        self.chk_vivo = QCheckBox("Atualizar ao vivo")
        self.chk_vivo.setChecked(True)
        h.addWidget(self.chk_vivo)
        h.addStretch()
        b = _botao("Gerar", "Recalcula o candidato", "segmentar")
        b.clicked.connect(lambda: self.pedido.emit("gerar", None))
        h.addWidget(b)
        s.add(h)
        self.seg_sub = Segmentado([("somar", "Só pixels livres"), ("substituir", "Livres + o próprio")])
        self.seg_sub.setToolTip("Só livres = como o segmentar.py (commit soma). Livres + o próprio = "
                                "re-segmentar o mineral (como o comparar.py)")
        self.seg_sub.escolhido.connect(self._mudou)
        s.add(self.seg_sub)
        self.l_res = QLabel("—")
        self.l_res.setWordWrap(True)
        s.add(self.l_res)
        self.seg_visao = Segmentado([("candidato", "Candidato"), ("comparar", "Comparar"), ("nada", "Ocultar")])
        self.seg_visao.escolhido.connect(self.visaoMudou.emit)
        s.add(self.seg_visao)
        self.l_leg = _mudo("", 8)
        s.add(self.l_leg)
        L.addWidget(s)

        s = Secao("Commitar")
        self.l_commit = _mudo("", 8.5)
        s.add(self.l_commit)
        b = _botao("Commitar candidato", "Grava nos rótulos (1 passo desfazível; Ctrl+Z)", "salvar", primario=True)
        b.clicked.connect(lambda: self.pedido.emit("commitar", None))
        s.add(b)
        L.addWidget(s)

        s = Secao("Calibrar (desenho do operador)", aberta=False)
        s.add(_mudo("Propõe uma regra por fração a partir da química dos pixels já rotulados deste "
                    "mineral × o resto da amostra (comparar.py --calibrar).", 8))
        b = _botao("Propor regra")
        b.clicked.connect(lambda: self.pedido.emit("calibrar", None))
        s.add(b)
        self.t_cal = QPlainTextEdit()
        self.t_cal.setReadOnly(True)
        self.t_cal.setFont(tema.fonte_mono(8))
        self.t_cal.setMinimumHeight(150)
        self.t_cal.hide()
        s.add(self.t_cal)
        self.b_usar = _botao("Usar a regra proposta")
        self.b_usar.clicked.connect(lambda: self.pedido.emit("usar_calibrada", None))
        self.b_usar.hide()
        s.add(self.b_usar)
        self.sec_cal = s
        L.addWidget(s)

        s = Secao("Config", aberta=False)
        s.add(_mudo("Grava os parâmetros atuais deste mineral na config do pacote e, se quiser, no "
                    "arquivo da config do projeto (com backup; comentários preservados).", 8))
        b = _botao("Salvar parâmetros na config…", icone="exportar")
        b.clicked.connect(lambda: self.pedido.emit("salvar_config", None))
        s.add(b)
        L.addWidget(s)

        s = Secao("Clusters k-means", aberta=False)
        g = QGridLayout()
        self.sp_k = QSpinBox()
        self.sp_k.setRange(2, 30)
        self.sp_k.setValue(9)
        self.sp_raio = QSpinBox()
        self.sp_raio.setRange(0, 20)
        self.sp_raio.setValue(4)
        g.addWidget(_mudo("k", 8.5), 0, 0)
        g.addWidget(self.sp_k, 0, 1)
        g.addWidget(_mudo("raio maioria", 8.5), 1, 0)
        g.addWidget(self.sp_raio, 1, 1)
        s.add(g)
        b = _botao("Recalcular clusters", "k-means do reconhecer.py (n_init=10, random_state=0) + filtro de maioria")
        b.clicked.connect(lambda: self.pedido.emit("kmeans", None))
        s.add(b)
        s.add(_mudo("Em 4096² pode levar minutos. Os nomes vêm da 1ª regra da config que o centro satisfaz.", 8))
        L.addWidget(s)
        L.addStretch()
        self.conds = []
        self.grupos = []

    # ---------- dados ----------
    def definir(self, am):
        self.am = am
        self._bloq = True
        self.cb_min.clear()
        for m in am.minerais:
            self.cb_min.addItem(_icone_cor(m.cor), f"{m.id} · {m.nome.replace('_', ' ')}", m.id)
        self._bloq = False

    def mineral(self):
        return self.cb_min.currentData() or 0

    def set_mineral(self, mid, emitir=False):
        self._bloq = not emitir
        i = self.cb_min.findData(int(mid))
        if i >= 0:
            self.cb_min.setCurrentIndex(i)
        self._bloq = False

    def carregar(self, params, fonte_ok, px_ja):
        """Preenche os editores a partir de params (sem disparar recálculo)."""
        self._bloq = True
        self.params = copy.deepcopy(params)
        p = self.params
        am = self.am
        self.l_cfg.setText("Na config: " + sg.resumo(p))
        self.l_ja.setText(f"Já rotulado: {fmt(px_ja)} px" + (" — a comparação usa esses pixels como "
                          "'operador'." if px_ja else " — nada a comparar ainda."))
        for k, b in self.seg_fonte.botoes.items():
            b.setEnabled(fonte_ok.get(k, True))
            b.setToolTip("" if fonte_ok.get(k, True) else "indisponível para esta amostra/mineral")
        self.seg_fonte.set(p.get("fonte", "regra"))
        # regra
        descartar(self.conds)
        self.conds = []
        for k, v in (p.get("condicoes") or {}).items():
            self._add_cond(k, v)
        # mapa
        self.seg_modelo.set("grupos" if p.get("mapas_grupos") else "pixel")
        descartar(self.grupos)
        self.grupos = []
        for g in p.get("mapas_grupos") or []:
            self._add_grupo(g)
        self._grupos_combo()
        self.ed_mapas.setText(", ".join(p.get("mapas_seg") or []))
        self.cb_modo.setCurrentText(p.get("mapas_modo", "interseccao"))
        self.cb_limiar.setCurrentText(p.get("mapas_limiar", "otsu"))
        self.sp_q.setValue(float(p.get("mapas_q", 0.65)))
        # clusters
        descartar(self.chk_cl)
        self.chk_cl = []
        if am.clusters is not None:
            nomes = (am.clusters_info or {}).get("nomes", {})
            for k in range(1, int(am.clusters.max()) + 1):
                c = QCheckBox(f"{k} · {nomes.get(str(k), '?').replace('_', ' ')}")
                c.setStyleSheet(f"QCheckBox {{ color: {cores.CORES_CLUSTER[(k - 1) % 12]}; }}")
                c.setChecked(k in (p.get("clusters") or []))
                c.toggled.connect(self._mudou)
                c.k = k
                self.box_cl.addWidget(c)
                self.chk_cl.append(c)
        else:
            c = _mudo("Sem clusters — recalcule o k-means abaixo.", 8.5)
            self.box_cl.addWidget(c)
            self.chk_cl.append(c)
        self.chk_dissem.setChecked(bool(p.get("disseminado")))
        f = p.get("forma") or {}
        self.chk_forma.setChecked(bool(f))
        self.sp_close.setValue(int(f.get("close", 0)))
        self.sp_amin.setValue(int(f.get("area_min", 0)))
        self.sp_ecc.setValue(float(f.get("ecc_min", 0)))
        self.chk_convex.setChecked(bool(f.get("convex")))
        self.chk_maior.setChecked(bool(f.get("maior")))
        self.chk_preencher.setChecked(bool(f.get("preencher")))
        self._fonte(p.get("fonte", "regra"), emitir=False)
        self.t_cal.hide()
        self.b_usar.hide()
        self._bloq = False

    def _add_cond(self, k, v):
        ln = _LinhaCond(k, v)
        ln.mudou.connect(self._mudou)
        ln.remover.connect(self._rem_cond)
        self.box_cond.addWidget(ln)
        self.conds.append(ln)

    def _rem_cond(self, ln):
        self.conds.remove(ln)
        descartar([ln])
        self._mudou()

    def _add_grupo(self, g):
        w = _Grupo(g)
        w.mudou.connect(self._grupo_mudou)
        w.remover.connect(self._rem_grupo)
        self.box_grupos.addWidget(w)
        self.grupos.append(w)

    def _novo_grupo(self):
        self._add_grupo({"nome": f"grupo{len(self.grupos) + 1}", "suavizar": 15,
                         "cond": [{"canal": "Si", "tipo": "raw", "op": ">", "q": 0.5}]})
        self._grupo_mudou()

    def _rem_grupo(self, w):
        self.grupos.remove(w)
        descartar([w])
        self._grupo_mudou()

    def _grupo_mudou(self):
        self._grupos_combo()
        self._mudou()

    def _grupos_combo(self):
        atual = self.cb_so_grupo.currentData()
        self.cb_so_grupo.blockSignals(True)
        self.cb_so_grupo.clear()
        self.cb_so_grupo.addItem("todos (união)", None)
        for g in self.grupos:
            self.cb_so_grupo.addItem(g.nome.text(), g.nome.text())
        i = self.cb_so_grupo.findData(atual)
        self.cb_so_grupo.setCurrentIndex(max(0, i))
        self.cb_so_grupo.blockSignals(False)

    def _fonte(self, f, emitir=True):
        self.w_regra.setVisible(f == "regra")
        self.w_mapa.setVisible(f == "mapa")
        self.w_cluster.setVisible(f == "cluster")
        self._modelo(self.seg_modelo.valor(), emitir=False)
        if emitir:
            self._mudou()

    def _modelo(self, m, emitir=True):
        self.w_grupos.setVisible(m == "grupos")
        self.w_pixel.setVisible(m == "pixel")
        if emitir:
            self._mudou()

    def _mudou(self, *_):
        if not self._bloq:
            self.parametrosMudaram.emit()

    def ler(self):
        """Params atuais dos editores (formato da config) + fonte + clusters."""
        p = {"fonte": self.seg_fonte.valor()}
        fonte_cfg = self.params.get("fonte_default")
        if fonte_cfg or p["fonte"] != sg.fonte_padrao(self.params):
            p["fonte_default"] = p["fonte"]
        cond = {}
        for c in self.conds:
            k, v = c.canal.text().strip(), c.expr.text().strip()
            if k and v:
                cond[k] = v
        p["condicoes"] = cond
        if self.seg_modelo.valor() == "grupos" and self.grupos:
            p["mapas_grupos"] = [g.valor() for g in self.grupos]
            if "suavizar" in self.params:
                p["suavizar"] = self.params["suavizar"]
            if self.params.get("mapas_seg"):
                p["mapas_seg"] = self.params["mapas_seg"]
        else:
            ms = [e.strip() for e in self.ed_mapas.text().replace(";", ",").split(",") if e.strip()]
            if ms:
                p["mapas_seg"] = ms
            if self.cb_modo.currentText() != "interseccao" or "mapas_modo" in self.params:
                p["mapas_modo"] = self.cb_modo.currentText()
            if self.cb_limiar.currentText() != "otsu" or "mapas_limiar" in self.params:
                p["mapas_limiar"] = self.cb_limiar.currentText()
            if self.cb_limiar.currentText() == "quantil" or "mapas_q" in self.params:
                p["mapas_q"] = round(self.sp_q.value(), 4)
        if self.chk_dissem.isChecked():
            p["disseminado"] = True
        if self.chk_forma.isChecked():
            f = {}
            if self.sp_close.value():
                f["close"] = self.sp_close.value()
            if self.sp_amin.value():
                f["area_min"] = self.sp_amin.value()
            if self.sp_ecc.value():
                f["ecc_min"] = round(self.sp_ecc.value(), 3)
            for k, c in (("convex", self.chk_convex), ("maior", self.chk_maior), ("preencher", self.chk_preencher)):
                if c.isChecked():
                    f[k] = True
            if f:
                p["forma"] = f
        p["clusters"] = [c.k for c in self.chk_cl if isinstance(c, QCheckBox) and c.isChecked()]
        return p

    def grupo_unico(self):
        return self.cb_so_grupo.currentData() if self.seg_modelo.valor() == "grupos" else None

    def substituir(self):
        return self.seg_sub.valor() == "substituir"

    # ---------- feedback ----------
    def set_msg(self, texto, tipo="ok"):
        self.msg.mostrar(texto, tipo)

    def set_resultado(self, info, comp, calculando=False):
        if calculando:
            self.l_res.setText("calculando…")
            return
        if info is None:
            self.l_res.setText("—")
            return
        txt = (f"<b>{fmt(info['px'])} px</b> · {fmt(info['graos'])} grãos "
               f"<span style='color:{tema.C['mudo']}'>(de {fmt(info['livres'])} px livres · "
               f"fonte {info['fonte']} · {info['tempo']:.2f} s)</span>")
        if comp:
            txt += (f"<br>vs rotulado: <b>IoU {comp['iou']:.3f}</b> · Dice {comp['dice']:.3f} · "
                    f"precisão {comp['precisao']:.3f} · recall {comp['recall']:.3f}"
                    f"<br><span style='color:{tema.C['texto2']}'>grãos rotulados cobertos ≥50%: "
                    f"{comp['graos_oper_cobertos']}/{comp['graos_oper']} · grãos do candidato sem "
                    f"sobreposição: {comp['graos_auto_falsos']}/{comp['graos_auto']}</span>")
        self.l_res.setText(txt)


# ======================= controle (cálculo no Servico, coalescente) =======================
def _calcular(am, mid, params, substituir, grupo):
    """Candidato + comparação com o que já está rotulado (roda na thread do Servico)."""
    t = time.time()
    cand, info = sg.candidato(am, mid, params, substituir=substituir, grupo=grupo)
    oper = am.rotulos == mid
    comp = sg.comparar(oper, cand) if oper.any() else None
    info["tempo"] = time.time() - t
    return cand, info, comp, oper


class ControleSegmentar(QObject):
    def __init__(self, janela):
        super().__init__(janela)
        self.j = janela
        self.p = janela.painel_seg
        self.c = janela.canvas
        self.res = None
        self._gen = 0
        self._proposta_cal = None
        self.servico = Servico(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.gerar)
        self.p.parametrosMudaram.connect(self._params_mudaram)
        self.p.mineralMudou.connect(self.escolher)
        self.p.pedido.connect(self._pedido)
        self.p.visaoMudou.connect(lambda _v: self._desenhar())

    @property
    def am(self):
        return self.j.am

    @property
    def ocupado(self):
        """Candidato em cálculo ou agendado (autoteste / aguardar_render)."""
        return self.servico.ocupado or self.timer.isActive()

    def parar(self):
        self.servico.parar()

    # ---------- ciclo ----------
    def definir(self, am):
        self.p.definir(am)
        self.res = None
        presentes = [int(v) for v in np.unique(am.rotulos[::4, ::4]) if v]
        self.p.set_mineral(presentes[0] if presentes else am.minerais[0].id)

    def entrar(self):
        self.escolher(self.p.mineral())

    def sair(self):
        self.c.set_camada("cand", None)
        self.timer.stop()

    def escolher(self, mid):
        am = self.am
        if am is None or not mid:
            return
        params = sg.params_da_regra(am, mid)
        tem_mapa = bool(params.get("mapas_seg") or params.get("mapas_grupos"))
        ok = {"regra": True, "mapa": True, "cluster": am.clusters is not None}
        if not tem_mapa and params["fonte"] == "mapa":
            params["fonte"] = "regra"
        if params["fonte"] == "cluster" and not params.get("clusters") and params.get("condicoes"):
            params["fonte"] = "regra"                  # sem cluster com este nome: começa pela regra
        px = int((am.rotulos == mid).sum())
        self.p.carregar(params, ok, px)
        self.p.seg_sub.set("substituir" if px else "somar")
        self.p.l_commit.setText("")
        self.p.set_msg("")
        self.j.mostrar_ativo_seg(mid)
        self.gerar()

    def _params_mudaram(self):
        if self.p.chk_vivo.isChecked():
            self.timer.start()

    def gerar(self):
        if self.j.modo != "segmentar" or self.am is None:
            return
        self._gen += 1
        g, versao = self._gen, self.j.controle.editor.versao
        am, mid, params, sub, grupo = self.am, self.p.mineral(), self.p.ler(), self.p.substituir(), self.p.grupo_unico()
        self.p.set_resultado(None, None, calculando=True)
        self.j.st_render.setText("calculando candidato…")
        self.servico.pedir(lambda _prog: _calcular(am, mid, params, sub, grupo),
                           lambda r: self._pronto(g, r, dict(mid=mid, params=params, substituir=sub, versao=versao)),
                           lambda curta, _det: self._falhou(g, curta), coalescer=True)

    def _fim_calculo(self):
        if not self.servico.ocupado:
            self.j.st_render.setText("")

    def _pronto(self, g, r, pedido):
        self._fim_calculo()
        if g != self._gen:
            return
        cand, info, comp, oper = r
        self.res = {"cand": cand, "info": info, "comp": comp, "oper": oper, **pedido}
        self.p.set_resultado(info, comp)
        self.p.set_msg("")
        modo = "substitui o mineral (apaga o que sobrar fora do candidato)" if self.p.substituir() \
            else "soma ao que já existe (como o segmentar.py)"
        self.p.l_commit.setText(f"Commit: {modo}. Nunca sobrescreve outros minerais.")
        self._desenhar()

    def _falhou(self, g, msg):
        self._fim_calculo()
        if g == self._gen:
            self.res = None
            self.p.set_resultado(None, None)
            self.p.set_msg(msg, "erro")
            self.c.set_camada("cand", None)

    def _desenhar(self):
        if self.res is None or self.j.modo != "segmentar":
            self.c.set_camada("cand", None)
            return
        visao = self.p.seg_visao.valor()
        cand, oper = self.res["cand"], self.res["oper"]
        if visao == "nada":
            self.c.set_camada("cand", None)
            self.p.l_leg.setText("")
            return
        if visao == "comparar" and oper.any():
            tudo = cand | oper
            ys, xs = np.nonzero(tudo)
            if ys.size == 0:
                self.c.set_camada("cand", None)
                return
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            a, o = cand[y0:y1, x0:x1], oper[y0:y1, x0:x1]
            rgba = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
            rgba[a & o] = (26, 230, 26, 200)
            rgba[a & ~o] = (242, 38, 38, 210)
            rgba[o & ~a] = (51, 102, 255, 210)
            self.c.set_camada("cand", rgba_para_qimage(np.ascontiguousarray(rgba)), int(x0), int(y0))
            self.p.l_leg.setText("verde = acerto (candidato ∩ rotulado) · vermelho = só no candidato · "
                                 "azul = só no rotulado")
            return
        s = sobreposicao(cand, cor=(255, 204, 63), alfa=120)
        if s is None:
            self.c.set_camada("cand", None)
            self.p.l_leg.setText("candidato vazio")
            return
        self.c.set_camada("cand", *s)
        self.p.l_leg.setText("amarelo = candidato (prévia PRÉ)" +
                             ("" if not oper.any() else " · 'Comparar' mostra acertos e erros vs o rotulado"))

    # ---------- ações ----------
    def _pedido(self, acao, _arg):
        if self.j._ocupado:
            return
        {"gerar": self.gerar, "commitar": self.commitar, "calibrar": self.calibrar,
         "usar_calibrada": self.usar_calibrada, "salvar_config": self.salvar_config,
         "kmeans": self.kmeans}[acao]()

    def commitar(self):
        r = self.res
        ed = self.j.controle.editor
        if r is None:
            self.p.set_msg("Gere um candidato primeiro.", "aviso")
            return
        if r["versao"] != ed.versao or r["mid"] != self.p.mineral():
            self.p.set_msg("Os rótulos mudaram desde o cálculo — recalculando; commite de novo.", "aviso")
            self.gerar()
            return
        mid, cand = r["mid"], r["cand"]
        rot = self.am.rotulos
        permitido = cand & ((rot == 0) | (rot == mid))          # como o segmentar.py: não sobrescreve outros
        nome = ed.nome(mid)
        fonte = r["info"]["fonte"]

        def fazer():
            if r["substituir"]:
                ed.aplicar((rot == mid) & ~cand, 0, 0, 0, alvo=mid, fora_ok=True)
            ed.aplicar(permitido, 0, 0, mid, forcar=True)
        passo = ed._passo(f"segmentar {nome} ({fonte}{', substituir' if r['substituir'] else ''})", fazer)
        if passo is None:
            self.p.set_msg("Nada mudou — o candidato já está rotulado.", "info")
            return
        self.j.marcar_sujo(True)
        self.j.render.invalidar()
        self.j.recompor()
        self.p.set_msg(f"PÓS: {passo.desc} · {fmt(passo.px)} px alterados · agora "
                       f"{fmt(int((rot == mid).sum()))} px de {nome}. Ctrl+Z desfaz.", "ok")
        self.p.l_ja.setText(f"Já rotulado: {fmt(int((rot == mid).sum()))} px")
        self.gerar()

    def calibrar(self):
        mid = self.p.mineral()
        oper = self.am.rotulos == mid
        if oper.sum() < 10:
            self.p.set_msg("Rotule (desenhe) alguns grãos deste mineral primeiro — a calibração aprende deles.", "aviso")
            return
        am = self.am

        def fazer(_prog):
            regra, diag, mp = sg.calibrar(am, oper)
            atual = sg.metricas_regra(am, oper, am.regra(mid).get("condicoes"))
            return regra, diag, mp, atual
        self.j._rodar("Calibrando", fazer, self._calibrado)

    def _calibrado(self, r):
        regra, diag, mp, atual = r
        self._proposta_cal = regra
        linhas = ["Separação por elemento (operador × resto da amostra):"] + ["  " + d for d in diag]
        linhas += ["", "Regra proposta: " + (", ".join(f"{k}{v}" for k, v in regra.items()) or "—"),
                   f"  → IoU {mp['iou']:.3f} · precisão {mp['precisao']:.3f} · recall {mp['recall']:.3f}"]
        if atual:
            linhas.append(f"Regra atual (condicoes): IoU {atual['iou']:.3f} · precisão {atual['precisao']:.3f} · "
                          f"recall {atual['recall']:.3f}")
        self.p.t_cal.setPlainText("\n".join(linhas))
        self.p.sec_cal.cab.setChecked(True)            # abre a seção (pode estar recolhida)
        self.p.t_cal.show()
        self.p.b_usar.setVisible(bool(regra))

    def usar_calibrada(self):
        if not self._proposta_cal:
            return
        p = self.p.ler()
        p["condicoes"] = dict(self._proposta_cal)
        p["fonte"] = "regra"
        for k in ("mapas_grupos", "forma"):
            p.pop(k, None)
        mid = self.p.mineral()
        self.p.carregar(p, {"regra": True, "mapa": True, "cluster": self.am.clusters is not None},
                        int((self.am.rotulos == mid).sum()))
        self.p.seg_fonte.set("regra")
        self.p._fonte("regra", emitir=False)
        self.gerar()

    def salvar_config(self):
        mid = self.p.mineral()
        m = self.am.mineral(mid)
        p = self.p.ler()
        params = {k: p[k] for k in sg.CHAVES_REGRA if k in p}
        if self.am.config_yaml is None:
            self.p.set_msg("Este pacote não tem config.", "erro")
            return
        try:
            novo_txt, antigo_b, novo_b = config_texto.substituir(self.am.config_yaml, m.nome, params,
                                                                 self.am.pixel_um)
        except ValueError as e:
            self.p.set_msg(f"Não foi possível gravar: {e}", "erro")
            return
        arq = (self.am.origem or {}).get("config")
        dlg = _DialogoConfig(self.j, m.nome, antigo_b, novo_b, arq)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.am.config_yaml = novo_txt
        self.am.__dict__.pop("config", None)                  # reinterpreta a config no próximo acesso
        self.j.marcar_sujo(True)
        msg = f"Parâmetros de {m.nome} gravados na config do pacote (salve o .mudmap)."
        if dlg.no_projeto():
            try:
                bak, _a, _b = config_texto.gravar_arquivo(arq, m.nome, params, self.am.pixel_um)
                msg += f" Projeto: {arq} atualizado (backup {bak.name})."
            except Exception as e:  # noqa: BLE001
                msg += f" Projeto NÃO atualizado: {e}"
        self.p.set_msg(msg, "ok")

    def kmeans(self):
        am, k, r = self.am, self.p.sp_k.value(), self.p.sp_raio.value()
        if am.clusters is not None:
            res = QMessageBox.question(self.j, "Recalcular clusters",
                                       f"Substituir os clusters atuais do pacote por um k-means novo (k={k})?")
            if res != QMessageBox.StandardButton.Yes:
                return
        self.j._rodar(f"k-means (k={k})", lambda prog: sg.kmeans(am, k, r, prog), self._kmeans_pronto)

    def _kmeans_pronto(self, r):
        lab, info = r
        am = self.am
        am.clusters = lab.astype(np.uint8 if lab.max() < 256 else np.uint16)
        am.clusters_info = info
        self.j.marcar_sujo(True)
        self.j.camadas.definir_clusters(am)
        self.p.set_msg(f"Clusters recalculados (k={info['k']}): " +
                       ", ".join(f"{k} {n}" for k, n in info["nomes"].items()), "ok")
        self.escolher(self.p.mineral())


class _DialogoConfig(QDialog):
    def __init__(self, parent, nome, antigo, novo, arq_projeto):
        super().__init__(parent)
        self.setWindowTitle(f"Salvar parâmetros de {nome} na config")
        self.setMinimumSize(760, 560)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Bloco de <b>{nome}</b> — antes e depois (só as chaves de regra mudam; "
                           "comentários e outros minerais ficam como estão):"))
        h = QHBoxLayout()
        for titulo, txt in (("Antes", antigo), ("Depois", novo)):
            col = QVBoxLayout()
            col.addWidget(_mudo(titulo, 9))
            t = QPlainTextEdit(txt)
            t.setReadOnly(True)
            t.setFont(tema.fonte_mono(8))
            t.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            col.addWidget(t)
            h.addLayout(col)
        v.addLayout(h)
        self.chk = QCheckBox(f"Também gravar no arquivo do projeto: {arq_projeto}" if arq_projeto
                             else "Sem arquivo de config do projeto associado (só o pacote)")
        self.chk.setEnabled(bool(arq_projeto))
        v.addWidget(self.chk)
        v.addWidget(_mudo("O arquivo do projeto ganha um backup .bak_<data> antes de ser alterado.", 8.5))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Gravar")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def no_projeto(self):
        return self.chk.isChecked()
