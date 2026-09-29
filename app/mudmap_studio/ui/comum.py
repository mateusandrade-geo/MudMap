"""Utilitários de interface compartilhados pelos painéis (fonte única — não duplicar)."""
import math

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton,
                             QVBoxLayout, QWidget)
from scipy import ndimage as ndi

from . import icones, tema


def num_bonito(x, mantissas=(1, 2, 5, 10)):
    """Menor número 'redondo' ≥ x (escalas, passos de eixo)."""
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    return next((m * e for m in mantissas if m * e >= x), 10 * e)


def descartar(widgets):
    """Tira da tela e libera widgets de uma lista que vai ser recriada."""
    for w in widgets:
        w.setParent(None)
        w.deleteLater()


def rolagem(w):
    """QScrollArea vertical em volta de w (largura acompanha o painel)."""
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    s.setWidget(w)
    return s


class PainelRolavel(QScrollArea):
    """Painel lateral rolável com fundo 'painel'; o conteúdo vai em self.L (QVBoxLayout)."""

    def __init__(self, margens=(16, 12, 14, 16), parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        base = QWidget()
        base.setObjectName("painel")
        self.setWidget(base)
        self.L = QVBoxLayout(base)
        self.L.setContentsMargins(*margens)
        self.L.setSpacing(2)


def fmt(x, d=0):
    """Número no padrão brasileiro (milhar = espaço fino, decimal = vírgula)."""
    s = f"{float(x):,.{d}f}"
    return s.replace(",", " ").replace(".", ",")


def rgba_para_qimage(rgba):
    h, w = rgba.shape[:2]
    return QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()


def sobreposicao(incl, excl=None, cor=(63, 200, 255), alfa=80, origem=(0, 0)):
    """Camada RGBA (janela mínima) com preenchimento `alfa` + contorno opaco de `incl` e só o
    contorno vermelho de `excl` -> (QImage, x0, y0) em coordenadas da imagem, ou None."""
    tudo = incl if excl is None else (incl | excl)
    ys, xs = np.nonzero(tudo)
    if ys.size == 0:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    inc = incl[y0:y1, x0:x1]
    rgba = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    rgba[inc] = (*cor, alfa)
    rgba[inc & ~ndi.binary_erosion(inc, border_value=0)] = (*cor, 255)
    if excl is not None:
        exc = excl[y0:y1, x0:x1]
        rgba[exc & ~ndi.binary_erosion(exc, border_value=0)] = (229, 83, 75, 255)
    return rgba_para_qimage(np.ascontiguousarray(rgba)), int(x0) + origem[0], int(y0) + origem[1]


def sw(cor, tam=12):
    """Quadradinho de cor (legendas)."""
    l = QLabel()
    l.setFixedSize(tam, tam)
    l.setStyleSheet(f"background:{cor}; border-radius:3px; border:1px solid rgba(0,0,0,0.45);")
    return l


def mudo(texto, pt=8):
    """Texto de apoio (cinza, quebra linha)."""
    l = QLabel(texto)
    l.setObjectName("mudo")
    l.setWordWrap(True)
    l.setStyleSheet(f"font-size: {pt}pt;")
    return l


def icone_cor(cor):
    pm = QPixmap(14, 14)
    pm.fill(QColor(cor))
    return QIcon(pm)


def botao(txt, dica="", icone=None, primario=False):
    b = QPushButton(txt)
    if icone:
        b.setIcon(icones.icone(icone, "#0d1a14" if primario else "#a5abb2", tam=16))
    if primario:
        b.setObjectName("primario")
    b.setToolTip(dica)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def botao_seg(txt, dica="", altura=20):
    """Botão pequeno de texto (estilo 'seg'): +condição, todos/nenhum, raios…"""
    b = QPushButton(txt)
    b.setObjectName("seg")
    b.setFixedHeight(altura)
    b.setToolTip(dica)
    return b


def botao_x(dica="Remover"):
    b = QPushButton("×")
    b.setObjectName("mini")
    b.setFixedSize(22, 22)
    b.setToolTip(dica)
    return b


class Mensagem(QLabel):
    """Linha de retorno dos painéis (ok / erro / info / aviso)."""
    CORES = {"ok": "acento_forte", "erro": "perigo", "info": "texto2", "aviso": "aviso"}

    def __init__(self):
        super().__init__()
        self.setWordWrap(True)
        self.hide()

    def mostrar(self, texto, tipo="ok"):
        if not texto:
            self.hide()
            return
        self.setStyleSheet(f"color: {tema.C[self.CORES[tipo]]}; font-size: 8.5pt; padding: 4px 0;")
        self.setText(texto)
        self.show()


class Secao(QWidget):
    """Seção recolhível com cabeçalho em caixa alta."""

    def __init__(self, titulo, aberta=True):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 2)
        v.setSpacing(4)
        self.cab = QToolButton()
        self.cab.setObjectName("secao")
        self.cab.setText(titulo.upper())
        self.cab.setCheckable(True)
        self.cab.setChecked(aberta)
        self.cab.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.cab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cab.toggled.connect(self._abrir)
        v.addWidget(self.cab)
        self.corpo_w = QWidget()
        self.corpo = QVBoxLayout(self.corpo_w)
        self.corpo.setContentsMargins(0, 0, 0, 4)
        self.corpo.setSpacing(5)
        v.addWidget(self.corpo_w)
        self._abrir(aberta)

    def _abrir(self, on):
        self.cab.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.corpo_w.setVisible(on)

    def add(self, w):
        (self.corpo.addLayout if hasattr(w, "addWidget") and not isinstance(w, QWidget) else self.corpo.addWidget)(w)


class Segmentado(QWidget):
    """Botões exclusivos lado a lado (valor = chave da opção marcada)."""
    escolhido = pyqtSignal(str)

    def __init__(self, opcoes, valor=None):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.grupo = QButtonGroup(self)
        self.botoes = {}
        for k, (chave, rot) in enumerate(opcoes):
            b = QPushButton(rot)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setObjectName("segE" if k == 0 else ("segD" if k == len(opcoes) - 1 else "segM"))
            self.grupo.addButton(b)
            self.botoes[chave] = b
            b.clicked.connect(lambda _c, ch=chave: self.escolhido.emit(ch))
            h.addWidget(b)
        h.addStretch()
        self.set(valor or opcoes[0][0])

    def set(self, chave):
        if chave in self.botoes:
            self.botoes[chave].setChecked(True)

    def valor(self):
        return next((k for k, b in self.botoes.items() if b.isChecked()), None)
