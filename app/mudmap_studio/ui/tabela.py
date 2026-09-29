"""Tabela de grãos ordenável/filtrável; selecionar uma linha centraliza o grão no canvas.

Filtro e ordenação são feitos em numpy dentro do modelo (sem QSortFilterProxyModel, que
chamaria Python a cada comparação) -> instantâneo mesmo com centenas de milhares de grãos.
"""
import numpy as np
from PyQt6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                             QLabel, QTableView, QToolButton, QVBoxLayout, QWidget)

from ..nucleo.objetos import CLASSES
from . import icones, tema
from .comum import fmt

COLS = ["#", "Mineral", "Classe", "Área (µm²)", "Diâm. (µm)", "Pixels", "Fino", "Dominante"]
NUM = {0, 3, 4, 5}


class ModeloGraos(QAbstractTableModel):
    def __init__(self, am, ob):
        super().__init__()
        self.am, self.ob = am, ob
        self._cor = {m.id: QColor(m.cor) for m in am.minerais}
        self._nome = {m.id: m.nome.replace("_", " ") for m in am.minerais}
        self._dom = ob.frac.argmax(axis=1)
        self.mineral = None
        self.ocultar_finos = False
        self._col, self._ord = 5, Qt.SortOrder.DescendingOrder
        self.linhas = np.arange(1, ob.n + 1)
        self._aplicar()

    # ---- filtro + ordenação em numpy ----
    def _chave(self, col, ids):
        ob = self.ob
        if col == 0:
            return ids
        if col == 1:
            ordem_nome = {mid: i for i, mid in enumerate(sorted(self._nome, key=self._nome.get))}
            lut = np.array([ordem_nome.get(k, 0) for k in range(int(ob.mineral.max()) + 1)])
            return lut[ob.mineral[ids]]
        return (None, None, ob.classe, ob.um2, ob.diam, ob.area, ob.sub.astype(np.int8), self._dom)[col][ids]

    def _aplicar(self):
        ids = np.arange(1, self.ob.n + 1)
        if self.mineral is not None:
            ids = ids[self.ob.mineral[ids] == self.mineral]
        if self.ocultar_finos:
            ids = ids[~self.ob.sub[ids]]
        o = np.argsort(self._chave(self._col, ids), kind="stable")
        if self._ord == Qt.SortOrder.DescendingOrder:
            o = o[::-1]
        self.linhas = ids[o]

    def filtrar(self, mineral, ocultar_finos):
        self.beginResetModel()
        self.mineral, self.ocultar_finos = mineral, ocultar_finos
        self._aplicar()
        self.endResetModel()

    def sort(self, col, order=Qt.SortOrder.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        self._col, self._ord = col, order
        self._aplicar()
        self.layoutChanged.emit()

    def linha_de(self, oid):
        r = np.nonzero(self.linhas == oid)[0]
        return int(r[0]) if r.size else -1

    # ---- Qt ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.linhas)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, sec, ori, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and ori == Qt.Orientation.Horizontal:
            return COLS[sec]
        return None

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        i, c = int(self.linhas[idx.row()]), idx.column()
        ob = self.ob
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return str(i)
            if c == 1:
                return self._nome.get(int(ob.mineral[i]), "?")
            if c == 2:
                return "matriz" if ob.matriz[i] else CLASSES[int(ob.classe[i])]
            if c == 3:
                return fmt(ob.um2[i], 3)
            if c == 4:
                return fmt(ob.diam[i], 3)
            if c == 5:
                return fmt(ob.area[i])
            if c == 6:
                return "fino" if ob.sub[i] else ""
            return self.am.elementos[int(self._dom[i])]
        if role == Qt.ItemDataRole.DecorationRole and c == 1:
            return self._cor.get(int(ob.mineral[i]))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int((Qt.AlignmentFlag.AlignRight if c in NUM else Qt.AlignmentFlag.AlignLeft)
                       | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and c == 6:
            return QColor(tema.C["aviso"])
        return None


class PainelTabela(QWidget):
    ativado = pyqtSignal(int)
    fechar = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("painel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        barra = QWidget()
        barra.setObjectName("painel")
        hb = QHBoxLayout(barra)
        hb.setContentsMargins(10, 5, 6, 5)
        hb.setSpacing(10)
        t = QLabel("GRÃOS")
        t.setObjectName("secao")
        t.setStyleSheet("padding-top: 0;")
        hb.addWidget(t)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(150)
        hb.addWidget(self.combo)
        self.finos = QCheckBox("Ocultar finos (< area_min)")
        hb.addWidget(self.finos)
        self.cont = QLabel()
        self.cont.setObjectName("mudo")
        hb.addWidget(self.cont)
        hb.addStretch()
        fb = QToolButton()
        fb.setIcon(icones.icone("fechar", tam=16))
        fb.setToolTip("Fechar tabela (T)")
        fb.clicked.connect(self.fechar.emit)
        hb.addWidget(fb)
        lay.addWidget(barra)
        self.view = QTableView()
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setShowGrid(False)
        lay.addWidget(self.view)
        self.modelo = None
        self._bloq = False
        self.combo.currentIndexChanged.connect(self._filtro)
        self.finos.toggled.connect(self._filtro)

    def definir(self, am, ob):
        self._bloq = True
        self.modelo = ModeloGraos(am, ob)
        self.view.setModel(self.modelo)
        self.view.selectionModel().currentRowChanged.connect(self._linha)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for c, w in enumerate((64, 130, 70, 96, 90, 76, 52, 84)):
            self.view.setColumnWidth(c, w)
        h.setStretchLastSection(True)
        self.view.setSortingEnabled(True)
        h.setSortIndicator(5, Qt.SortOrder.DescendingOrder)
        self.combo.clear()
        self.combo.addItem("Todos os minerais", None)
        for m in am.minerais:
            if m.id < len(ob.n_obj_min) and ob.n_obj_min[m.id]:
                self.combo.addItem(m.nome.replace("_", " "), m.id)
        self.finos.setChecked(False)
        self._bloq = False
        self._contagem()

    def _contagem(self):
        self.cont.setText(f"{fmt(self.modelo.rowCount())} de {fmt(self.modelo.ob.n)}")

    def _filtro(self):
        if self._bloq or self.modelo is None:
            return
        self._bloq = True
        self.modelo.filtrar(self.combo.currentData(), self.finos.isChecked())
        self._bloq = False
        self._contagem()

    def set_mineral(self, mid):
        i = self.combo.findData(mid)
        self.combo.setCurrentIndex(max(0, i))

    def _linha(self, cur, _prev):
        if self._bloq or not cur.isValid():
            return
        self.ativado.emit(int(self.modelo.linhas[cur.row()]))

    def selecionar(self, oid):
        if self.modelo is None or not oid:
            return
        r = self.modelo.linha_de(oid)
        self._bloq = True
        if r >= 0:
            idx = self.modelo.index(r, 0)
            self.view.selectionModel().setCurrentIndex(
                idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            if self.isVisible():
                self.view.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
        else:
            self.view.clearSelection()
        self._bloq = False
