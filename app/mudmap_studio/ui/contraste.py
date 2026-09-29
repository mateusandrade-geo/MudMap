"""Editor de contraste: histograma (log) da camada dentro da amostra + limites mín/máx
arrastáveis + faixa com a rampa de cores. Duplo clique = automático."""
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import tema

M = 8          # margem lateral (px)
H_HIST = 58
H_RAMPA = 8


def fmt_valor(v, x0, x1):
    faixa = abs(x1 - x0)
    d = 0 if faixa >= 50 else (1 if faixa >= 5 else (2 if faixa >= 0.5 else 3))
    return f"{v:.{d}f}".replace(".", ",")


class _Histograma(QWidget):
    arrastou = pyqtSignal(float, float)
    auto = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(H_HIST + H_RAMPA + 8)
        self.setMouseTracking(True)
        self.hist = None
        self.x0, self.x1, self.lo, self.hi = 0.0, 1.0, 0.0, 1.0
        self.rampa = None
        self.cor = QColor(tema.C["acento"])
        self._alca = None

    def _px(self, v):
        w = self.width() - 2 * M
        return M + (v - self.x0) / max(self.x1 - self.x0, 1e-12) * w

    def _val(self, x):
        w = self.width() - 2 * M
        return self.x0 + (x - M) / max(w, 1) * (self.x1 - self.x0)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        r = QRectF(0, 0, w, H_HIST)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tema.C["painel"]))
        p.drawRoundedRect(r, 6, 6)
        if self.hist is not None and len(self.hist):
            h = np.log1p(np.asarray(self.hist, float))
            h = h / (h.max() or 1)
            n = len(h)
            path = QPainterPath(QPointF(M, H_HIST - 2))
            for i, v in enumerate(h):
                x = M + (i + 0.5) / n * (w - 2 * M)
                path.lineTo(QPointF(x, H_HIST - 2 - v * (H_HIST - 8)))
            path.lineTo(QPointF(w - M, H_HIST - 2))
            path.closeSubpath()
            c = QColor(self.cor)
            c.setAlpha(150)
            p.setBrush(c)
            p.drawPath(path)
        # fora da faixa: sombreado
        a, b = self._px(self.lo), self._px(self.hi)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRect(QRectF(0, 0, max(0, a), H_HIST))
        p.drawRect(QRectF(b, 0, max(0, w - b), H_HIST))
        # rampa
        y = H_HIST + 4
        if self.rampa is not None:
            g = QLinearGradient(a, 0, b, 0)
            for t in (0, 0.25, 0.5, 0.75, 1.0):
                c = self.rampa[int(round(t * 255))]
                g.setColorAt(t, QColor(int(c[0]), int(c[1]), int(c[2])))
            c0, c1 = self.rampa[0], self.rampa[255]
            p.setBrush(QColor(int(c0[0]), int(c0[1]), int(c0[2])))
            p.drawRect(QRectF(M, y, max(0, a - M), H_RAMPA))
            p.setBrush(QColor(int(c1[0]), int(c1[1]), int(c1[2])))
            p.drawRect(QRectF(b, y, max(0, w - M - b), H_RAMPA))
            p.setBrush(g)
            p.drawRect(QRectF(a, y, max(1, b - a), H_RAMPA))
        # alças
        for x in (a, b):
            p.setPen(QPen(QColor(tema.C["texto"]), 1.5))
            p.drawLine(QPointF(x, 2), QPointF(x, H_HIST + H_RAMPA + 4))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(tema.C["texto"]))
            p.drawEllipse(QPointF(x, H_HIST + H_RAMPA + 4), 4, 4)

    def mousePressEvent(self, e):
        x = e.position().x()
        self._alca = 0 if abs(x - self._px(self.lo)) <= abs(x - self._px(self.hi)) else 1
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        perto = min(abs(x - self._px(self.lo)), abs(x - self._px(self.hi))) < 7
        self.setCursor(Qt.CursorShape.SizeHorCursor if (perto or self._alca is not None)
                       else Qt.CursorShape.ArrowCursor)
        if self._alca is None:
            return
        v = min(self.x1, max(self.x0, self._val(x)))
        passo = (self.x1 - self.x0) / 400
        if self._alca == 0:
            self.lo = min(v, self.hi - passo)
        else:
            self.hi = max(v, self.lo + passo)
        self.update()
        self.arrastou.emit(self.lo, self.hi)

    def mouseReleaseEvent(self, _e):
        self._alca = None

    def mouseDoubleClickEvent(self, _e):
        self.auto.emit()


class Contraste(QWidget):
    """Emite mudou(lo, hi) durante o arraste (a fila de renderização descarta intermediários)."""
    mudou = pyqtSignal(float, float)

    def __init__(self, titulo=""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(3)
        self.titulo = QLabel(titulo)
        self.titulo.setObjectName("texto2")
        self.titulo.setStyleSheet("font-size: 8.5pt;")
        lay.addWidget(self.titulo)
        self.h = _Histograma()
        lay.addWidget(self.h)
        linha = QHBoxLayout()
        linha.setSpacing(4)
        self.l_lo = QLabel()
        self.l_hi = QLabel()
        for l in (self.l_lo, self.l_hi):
            l.setFont(tema.fonte_mono(8))
            l.setObjectName("mudo")
        self.b_auto = QPushButton("auto")
        self.b_tudo = QPushButton("tudo")
        for b, dica in ((self.b_auto, "Percentis 0,5–99,7 % dentro da amostra (duplo clique no histograma)"),
                        (self.b_tudo, "Faixa inteira dos dados")):
            b.setObjectName("seg")
            b.setToolTip(dica)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(20)
        linha.addWidget(self.l_lo)
        linha.addStretch()
        linha.addWidget(self.b_auto)
        linha.addWidget(self.b_tudo)
        linha.addStretch()
        linha.addWidget(self.l_hi)
        lay.addLayout(linha)
        self.auto_lim = (0.0, 1.0)
        self.h.arrastou.connect(self._arrastou)
        self.h.auto.connect(self._auto)
        self.b_auto.clicked.connect(self._auto)
        self.b_tudo.clicked.connect(lambda: self._aplicar(self.h.x0, self.h.x1))

    def definir(self, st, lim=None, cor=None, rampa=None, titulo=None):
        if titulo is not None:
            self.titulo.setText(titulo)
        h = np.asarray(st["hist"], float)
        if len(h) > 160:                         # 256 classes de imagem esticada = "pente" -> reagrupa em 64
            h = h[:len(h) // 4 * 4].reshape(-1, 4).sum(1)
        self.h.hist, self.h.x0, self.h.x1 = h, float(st["x0"]), float(st["x1"])
        self.auto_lim = tuple(float(v) for v in st["auto"])
        lo, hi = lim or self.auto_lim
        self.h.lo, self.h.hi = float(lo), float(hi)
        if cor is not None:
            self.h.cor = QColor(cor)
        self.h.rampa = rampa
        self._rotulos()
        self.h.update()

    def _rotulos(self):
        self.l_lo.setText(fmt_valor(self.h.lo, self.h.x0, self.h.x1))
        self.l_hi.setText(fmt_valor(self.h.hi, self.h.x0, self.h.x1))

    def _arrastou(self, lo, hi):
        self._rotulos()
        self.mudou.emit(lo, hi)

    def _aplicar(self, lo, hi):
        self.h.lo, self.h.hi = float(lo), float(hi)
        self._rotulos()
        self.h.update()
        self.mudou.emit(self.h.lo, self.h.hi)

    def _auto(self):
        self._aplicar(*self.auto_lim)
