"""Gráficos do Relatório em QPainter (sem matplotlib): o MESMO desenho vai para a tela, o PNG e o SVG.

Cada gráfico implementa desenhar(p, w, h, pal, alvos) sem depender do widget: a tela usa a paleta
escura (e registra os alvos de mouse), a exportação usa a clara (ou a escura, se pedido).
Regras de desenho (skill dataviz): marcas finas, barras com 2 px de vão e topo arredondado, pontos
com anel de 2 px na cor da superfície, grade em linha fina SÓLIDA um tom acima da superfície, texto
sempre nas cores de texto (nunca na cor da série), dica ao passar o mouse, alvo de clique ≥ 24 px.
Cores: série única = azul (slot 1); sítios = slots 1–3 validados (todos os pares, escuro e claro) +
forma + rótulo direto (acima de 3 sítios a cor deixa de identificar: só forma + rótulo); mapa de
calor = rampa azul sequencial (perto de zero some na superfície); minerais = cores da config.
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..nucleo.relatorio import classe_shepard
from .comum import fmt, num_bonito

RAMPA_AZUL = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
              "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
PAL = {
    "escuro": dict(sup="#23272c", fundo="#1c1f23", texto="#e7e9eb", texto2="#a5abb2", mudo="#7d848c",
                   grade="#30353b", eixo="#4a5058", serie=("#3987e5", "#d95926", "#199e70"),
                   destaque="#ffcc3f", rampa=RAMPA_AZUL[::-1], tinta_clara="#ffffff", tinta_escura="#0b0b0b"),
    "claro": dict(sup="#ffffff", fundo="#f4f4f1", texto="#0b0b0b", texto2="#52514e", mudo="#898781",
                  grade="#e1e0d9", eixo="#c3c2b7", serie=("#2a78d6", "#eb6834", "#1baf7a"),
                  destaque="#c98500", rampa=RAMPA_AZUL, tinta_clara="#ffffff", tinta_escura="#0b0b0b"),
}
FORMAS = ("circulo", "quadrado", "triangulo", "losango", "pentagono", "hexagono")
SQ3 = math.sqrt(3) / 2


def fonte(px, peso=QFont.Weight.Normal, tabular=False):
    f = QFont("Segoe UI")
    f.setPixelSize(int(px))
    f.setWeight(peso)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)          # algarismos de largura fixa em colunas
        except (AttributeError, TypeError):
            pass
    return f


def cor_rampa(t, pal):
    r = pal["rampa"]
    t = min(1.0, max(0.0, float(t))) * (len(r) - 1)
    i = min(int(t), len(r) - 2)
    a, b = QColor(r[i]), QColor(r[i + 1])
    f = t - i
    return QColor(round(a.red() + f * (b.red() - a.red())), round(a.green() + f * (b.green() - a.green())),
                  round(a.blue() + f * (b.blue() - a.blue())))


def tinta_sobre(fundo, pal):
    c = QColor(fundo)
    lum = (0.2126 * c.redF() ** 2.2 + 0.7152 * c.greenF() ** 2.2 + 0.0722 * c.blueF() ** 2.2)
    return QColor(pal["tinta_escura"] if lum > 0.28 else pal["tinta_clara"])


def desenhar_forma(p, forma, c, r):
    if forma == "circulo":
        p.drawEllipse(c, r, r)
        return
    if forma == "quadrado":
        p.drawRect(QRectF(c.x() - r * 0.88, c.y() - r * 0.88, r * 1.76, r * 1.76))
        return
    n, rot, k = {"triangulo": (3, -90, 1.2), "losango": (4, -90, 1.15), "pentagono": (5, -90, 1.08),
                 "hexagono": (6, 0, 1.05)}[forma]
    p.drawPolygon(QPolygonF([QPointF(c.x() + k * r * math.cos(math.radians(rot + 360 * i / n)),
                                     c.y() + k * r * math.sin(math.radians(rot + 360 * i / n))) for i in range(n)]))


def texto(p, rect, s, cor, f, alinh=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
    p.setFont(f)
    p.setPen(QColor(cor))
    p.drawText(rect, int(alinh), s)


class Alvo:
    """Região sensível ao mouse: retângulo ou ponto (raio de captura ≥ 12 px)."""

    def __init__(self, chave, dica, dado=None, rect=None, ponto=None, raio=12.0):
        self.chave, self.dica, self.dado = chave, dica, dado
        self.rect, self.ponto, self.raio = rect, ponto, max(12.0, raio)

    def dist(self, pos):
        if self.rect is not None:
            r = self.rect
            if r.height() < 24:                                     # alvo mínimo de 24 px
                r = r.adjusted(0, -(24 - r.height()) / 2, 0, (24 - r.height()) / 2)
            return 0.0 if r.contains(pos) else None
        d = math.hypot(pos.x() - self.ponto.x(), pos.y() - self.ponto.y())
        return d if d <= self.raio else None


class Grafico(QWidget):
    """Base: altura função da largura; alvos registrados no último desenho da tela."""
    ativado = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.alvos = []
        self.hover = None
        self._ajustar_altura(360)

    # ---- tamanho ----
    def altura_para(self, w):
        return 200

    def _ajustar_altura(self, w=None):
        h = int(self.altura_para(w or max(self.width(), 200)))
        if h != self.height():
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        self._ajustar_altura(e.size().width())
        super().resizeEvent(e)

    def sizeHint(self):
        return QSize(420, int(self.altura_para(420)))

    def mudou(self):
        self._ajustar_altura()
        self.update()

    # ---- desenho ----
    def desenhar(self, p, w, h, pal, alvos=None):
        raise NotImplementedError

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.alvos = []
        self.desenhar(p, self.width(), self.height(), PAL["escuro"], self.alvos)
        p.end()

    # ---- mouse ----
    def _alvo_em(self, pos):
        melhor, dmin = None, None
        for a in self.alvos:
            d = a.dist(pos)
            if d is not None and (dmin is None or d < dmin):
                melhor, dmin = a, d
        return melhor

    def mouseMoveEvent(self, e):
        a = self._alvo_em(e.position())
        chave = a.chave if a else None
        if chave != self.hover:
            self.hover = chave
            self.update()
        if a and a.dica:
            QToolTip.showText(e.globalPosition().toPoint(), a.dica, self)
        else:
            QToolTip.hideText()
        self.setCursor(Qt.CursorShape.PointingHandCursor if a is not None and a.dado is not None
                       else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, _e):
        if self.hover is not None:
            self.hover = None
            self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        a = self._alvo_em(e.position())
        if a is not None and a.dado is not None:
            self.ativado.emit(a.dado)


# ================================ blocos de números ================================
class Blocos(Grafico):
    """Linha de números-chave (rótulo + valor), 2 colunas quando estreito."""

    def __init__(self):
        self.itens = []            # [(rótulo, valor)]
        self.aviso = ""
        super().__init__()

    def definir(self, itens, aviso=""):
        self.itens, self.aviso = list(itens), aviso
        self.mudou()

    def _cols(self, w):
        return max(1, min(len(self.itens) or 1, 4 if w >= 520 else 2))

    def altura_para(self, w):
        n = max(1, len(self.itens))
        linhas = math.ceil(n / self._cols(w))
        return linhas * 58 + (linhas - 1) * 8 + (26 if self.aviso else 0)

    def desenhar(self, p, w, h, pal, alvos=None):
        cols = self._cols(w)
        cw = (w - (cols - 1) * 8) / cols
        for i, (rot, val) in enumerate(self.itens):
            x, y = (i % cols) * (cw + 8), (i // cols) * 66
            r = QRectF(x, y, cw, 58)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["fundo"]))
            p.drawRoundedRect(r, 7, 7)
            texto(p, QRectF(x + 12, y + 7, cw - 20, 16), rot, pal["texto2"], fonte(11))
            f = fonte(17, QFont.Weight.DemiBold)
            fm = QFontMetricsF(f)
            s = fm.elidedText(val, Qt.TextElideMode.ElideRight, cw - 20)
            texto(p, QRectF(x + 12, y + 25, cw - 20, 26), s, pal["texto"], f)
            if alvos is not None and s != val:
                alvos.append(Alvo(("b", i), f"{rot}: <b>{val}</b>", rect=r))
        if self.aviso:
            y = math.ceil(len(self.itens) / cols) * 66
            p.setPen(QPen(QColor(pal["destaque"]), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(7, y + 12), 5, 5)                       # ícone ⓘ + texto (nunca só cor)
            texto(p, QRectF(5, y + 6, 4, 12), "!", pal["destaque"], fonte(9, QFont.Weight.Bold),
                  Qt.AlignmentFlag.AlignCenter)
            texto(p, QRectF(18, y + 2, w - 18, 20), self.aviso, pal["texto2"], fonte(11))


# ================================ ternários ================================
class _Ternario(Grafico):
    """Triângulo equilátero: vértices (topo, esquerda, direita) = (a, b, c) com a+b+c = 1."""
    NOMES = ("A", "B", "C")
    LADO_MAX = 360
    MARGEM = 32                    # por lado (espaço dos rótulos dos vértices)
    RODAPE = 30

    def _geom(self, w):
        lado = min(w - 2 * self.MARGEM, self.LADO_MAX)
        alt = lado * SQ3
        x0 = (w - lado) / 2
        y0 = 24
        return QPointF(x0 + lado / 2, y0), QPointF(x0, y0 + alt), QPointF(x0 + lado, y0 + alt), lado

    def altura_para(self, w):
        return int(self._geom(w)[3] * SQ3 + 24 + 22 + self.RODAPE)

    @staticmethod
    def ponto(T, L, R, a, b, c):
        return QPointF(a * T.x() + b * L.x() + c * R.x(), a * T.y() + b * L.y() + c * R.y())

    @staticmethod
    def bary(T, L, R, q):
        """Inverso de ponto(): (a, b, c) do ponto q da tela."""
        det = (L.y() - R.y()) * (T.x() - R.x()) + (R.x() - L.x()) * (T.y() - R.y())
        a = ((L.y() - R.y()) * (q.x() - R.x()) + (R.x() - L.x()) * (q.y() - R.y())) / det
        b = ((R.y() - T.y()) * (q.x() - R.x()) + (T.x() - R.x()) * (q.y() - R.y())) / det
        return a, b, 1 - a - b

    def _moldura(self, p, T, L, R, pal, grade=True):
        seg = lambda u, v: p.drawLine(self.ponto(T, L, R, *u), self.ponto(T, L, R, *v))
        if grade:
            p.setPen(QPen(QColor(pal["grade"]), 1))
            for f in (0.2, 0.4, 0.6, 0.8):
                g = 1 - f
                seg((f, g, 0), (f, 0, g))
                seg((0, f, g), (g, f, 0))
                seg((g, 0, f), (0, g, f))
        p.setPen(QPen(QColor(pal["eixo"]), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF([T, L, R]))
        f = fonte(11, QFont.Weight.DemiBold)
        texto(p, QRectF(T.x() - 60, T.y() - 22, 120, 18), self.NOMES[0], pal["texto2"], f,
              Qt.AlignmentFlag.AlignCenter)
        texto(p, QRectF(L.x() - 30, L.y() + 4, 90, 18), self.NOMES[1], pal["texto2"], f,
              Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        texto(p, QRectF(R.x() - 60, R.y() + 4, 90, 18), self.NOMES[2], pal["texto2"], f,
              Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)


class TernarioShepard(_Ternario):
    """Areia (topo) · silte (esq.) · argila (dir.), campos de Shepard (1954) em linha fina.

    pontos: [{rotulo, fr: (areia, silte, argila), grupo, dado, sat: bool, pai: índice ou None}]
    Uma amostra: 1 ponto + leitura clicável das 3 classes. Vários: cor por sítio (≤ 3), forma por sítio,
    rótulo direto em cada ponto grande e legenda."""
    NOMES = ("areia", "silte", "argila")
    RODAPE = 34

    def __init__(self):
        self.pontos, self.grupos, self.leitura, self.sel = [], [], None, None
        super().__init__()

    def definir(self, pontos, grupos=None, leitura=None):
        """grupos: [(chave, rótulo)] na ordem das cores/formas; leitura: (areia, silte, argila) clicável."""
        self.pontos, self.grupos, self.leitura = list(pontos), list(grupos or []), leitura
        self.mudou()

    def _leg_linhas(self, w):
        if len(self.grupos) < 2:
            return 0
        x, linhas = 0, 1
        for _g, rot in self.grupos:
            lw = QFontMetricsF(fonte(11)).horizontalAdvance(rot) + 32
            if x + lw > w and x > 0:
                linhas, x = linhas + 1, 0
            x += lw
        return linhas

    def altura_para(self, w):
        return super().altura_para(w) + 20 * self._leg_linhas(w)

    def estilo(self, grupo, pal):
        chaves = [g for g, _r in self.grupos]
        i = chaves.index(grupo) if grupo in chaves else 0
        cor = pal["serie"][i] if len(chaves) <= 3 else pal["serie"][0]
        return QColor(cor), FORMAS[i % len(FORMAS)]

    def desenhar(self, p, w, h, pal, alvos=None):
        T, L, R, lado = self._geom(w)
        # campos de Shepard: 75 % nos cantos, triângulo central (todos ≥ 20 %) e as 6 divisórias
        p.setPen(QPen(QColor(pal["grade"]), 1))
        seg = lambda u, v: p.drawLine(self.ponto(T, L, R, *u), self.ponto(T, L, R, *v))
        seg((.75, .25, 0), (.75, 0, .25))
        seg((0, .75, .25), (.25, .75, 0))
        seg((.25, 0, .75), (0, .25, .75))
        p.drawPolygon(QPolygonF([self.ponto(T, L, R, *v) for v in ((.6, .2, .2), (.2, .6, .2), (.2, .2, .6))]))
        seg((.5, .5, 0), (.4, .4, .2))
        seg((.5, 0, .5), (.4, .2, .4))
        seg((0, .5, .5), (.2, .4, .4))
        seg((.75, .125, .125), (.6, .2, .2))
        seg((.125, .75, .125), (.2, .6, .2))
        seg((.125, .125, .75), (.2, .2, .6))
        self._moldura(p, T, L, R, pal, grade=False)
        if alvos is not None:
            alvos.append(_AlvoCampo(T, L, R, self))
        # pontos: satélites (campos) primeiro, ligados ao ponto do sítio por linha fina
        grandes, sats = [], []
        for i, pt in enumerate(self.pontos):
            c, forma = self.estilo(pt.get("grupo"), pal)
            q = self.ponto(T, L, R, *pt["fr"])
            if pt.get("sat"):
                pai = self.pontos[pt["pai"]] if pt.get("pai") is not None else None
                if pai is not None:
                    p.setPen(QPen(QColor(pal["eixo"]), 1))
                    p.drawLine(q, self.ponto(T, L, R, *pai["fr"]))
                self._marca(p, forma, q, 3.5, c, pal)
                sats.append((pt, q))
                if alvos is not None:
                    alvos.append(Alvo(("p", i), self._dica(pt), pt.get("dado"), ponto=q))
            else:
                grandes.append((i, pt, q, c, forma))
        ocup = [QRectF(q.x() - 8, q.y() - 8, 16, 16) for _i, _pt, q, _c, _f in grandes]
        for i, pt, q, c, forma in grandes:
            r = 7.5 if (self.hover == ("p", i) or self.sel == i) else 6
            self._marca(p, forma, q, r, c, pal, destaque=(self.sel == i))
            if alvos is not None:
                alvos.append(Alvo(("p", i), self._dica(pt), pt.get("dado"), ponto=q))
            if self.leitura is None:                                  # comparação: rótulo direto sempre
                ocup.append(self._rotulo(p, q, pt["rotulo"], ocup, pal, w, h))
        for pt, q in sats:                                            # campos: rótulo menor, se couber
            ocup.append(self._rotulo(p, q, pt["rotulo"], ocup, pal, w, h, px=10, cor="texto2", so_livre=True))
        # rodapé: leitura (1 amostra) ou legenda (vários)
        y = self.altura_para(w) - self.RODAPE - 20 * self._leg_linhas(w) + 4
        if self.leitura is not None:
            partes = [(k, f"{nome} {fmt(100 * v, 1)} %") for k, (nome, v) in
                      enumerate(zip(("areia", "silte", "argila"), self.leitura))]
            f = fonte(12)
            fm = QFontMetricsF(f)
            tot = sum(fm.horizontalAdvance(s) for _k, s in partes) + 28 * 2
            x = (w - tot) / 2
            for k, s in partes:
                lw = fm.horizontalAdvance(s)
                rr = QRectF(x - 6, y, lw + 12, 24)
                if self.hover == ("c", k):
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(pal["grade"]))
                    p.drawRoundedRect(rr, 5, 5)
                texto(p, QRectF(x, y, lw, 24), s, pal["texto"], f)
                if alvos is not None:
                    alvos.append(Alvo(("c", k), f"Destacar no canvas os grãos de <b>{('areia', 'silte', 'argila')[k]}</b>"
                                      + (" (e a matriz inteira)" if k == 2 else ""), ("classe", 2 - k), rect=rr))
                x += lw + 28
        if len(self.grupos) >= 2:
            self._legenda(p, w, y + 2, pal)

    def _marca(self, p, forma, q, r, cor, pal, destaque=False):
        p.setPen(QPen(QColor(pal["sup"]), 2))                     # anel de 2 px na cor da superfície
        p.setBrush(cor)
        desenhar_forma(p, forma, q, r)
        if destaque:
            p.setPen(QPen(QColor(pal["destaque"]), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            desenhar_forma(p, forma, q, r + 3.5)

    @staticmethod
    def _rotulo(p, q, s, ocup, pal, w, h, px=11, cor="texto", so_livre=False):
        f = fonte(px)
        fm = QFontMetricsF(f)
        lw, lh = fm.horizontalAdvance(s) + 2, px + 4
        cands = [QRectF(q.x() + 10, q.y() - lh / 2, lw, lh), QRectF(q.x() - 10 - lw, q.y() - lh / 2, lw, lh),
                 QRectF(q.x() - lw / 2, q.y() - 12 - lh, lw, lh), QRectF(q.x() - lw / 2, q.y() + 11, lw, lh)]
        livre = [c for c in cands if c.left() >= 0 and c.right() <= w and c.top() >= 0 and
                 not any(c.intersects(o) for o in ocup)]
        if not livre and so_livre:
            return QRectF()                               # sem espaço: fica na dica e na tabela
        r = livre[0] if livre else cands[0]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["sup"]))                    # fundo: o rótulo não se mistura às linhas
        p.drawRoundedRect(r.adjusted(-2, 0, 2, 0), 3, 3)
        texto(p, r, s, pal[cor], f)
        return r

    def _legenda(self, p, w, y, pal):
        f = fonte(11)
        fm = QFontMetricsF(f)
        x = 0
        for g, rot in self.grupos:
            lw = fm.horizontalAdvance(rot) + 32
            if x + lw > w and x > 0:
                x, y = 0, y + 20
            c, forma = self.estilo(g, pal)
            self._marca(p, forma, QPointF(x + 8, y + 9), 5, c, pal)
            texto(p, QRectF(x + 18, y, lw - 18, 18), rot, pal["texto2"], f)
            x += lw

    @staticmethod
    def _dica(pt):
        a, s, c = pt["fr"]
        cl = classe_shepard(a, s, c) or "—"
        return (f"<b>{pt['rotulo']}</b> · {cl}<br>areia <b>{fmt(100 * a, 1)} %</b> · silte <b>{fmt(100 * s, 1)} %</b>"
                f" · argila <b>{fmt(100 * c, 1)} %</b>" + (f"<br>{pt['extra']}" if pt.get("extra") else ""))


class _AlvoCampo(Alvo):
    """Qualquer lugar dentro do triângulo: diz o campo de Shepard sob o mouse (sem clique)."""

    def __init__(self, T, L, R, g):
        super().__init__(("campo",), "", None, rect=QRectF())
        self.T, self.L, self.R = T, L, R

    def dist(self, pos):
        a, b, c = _Ternario.bary(self.T, self.L, self.R, pos)
        if min(a, b, c) < -1e-9:
            return None
        self.dica = (f"campo de Shepard: <b>{classe_shepard(a, b, c)}</b><br>"
                     f"areia {fmt(100 * a, 0)} % · silte {fmt(100 * b, 0)} % · argila {fmt(100 * c, 0)} %")
        return 1e6                           # prioridade mínima: qualquer ponto por perto vence


class TernarioFicha(_Ternario):
    """Na-K-Ca compacto da ficha do Inspetor: o grão A (e o B, na comparação) na cor da seleção."""
    NOMES = ("Ca", "Na", "K")
    LADO_MAX = 140
    MARGEM = 30
    RODAPE = 0

    def __init__(self):
        self.pontos = []
        super().__init__()
        self.setFixedWidth(200)

    def definir(self, pontos):
        """pontos: [(na, k, ca, cor)]"""
        self.pontos = list(pontos)
        self.update()

    def desenhar(self, p, w, h, pal, alvos=None):
        T, L, R, _lado = self._geom(w)
        self._moldura(p, T, L, R, pal)
        for na, k, ca, cor in self.pontos:
            p.setPen(QPen(QColor(pal["sup"]), 2))
            p.setBrush(QColor(cor))
            p.drawEllipse(self.ponto(T, L, R, ca, na, k), 5.5, 5.5)


class TernarioNaKCa(_Ternario):
    """Feldspato por objeto: Ca (An) no topo, Na (Ab) à esquerda, K (Or) à direita; raio ∝ √área."""
    NOMES = ("Ca (An)", "Na (Ab)", "K (Or)")
    LADO_MAX = 300
    RODAPE = 22

    def __init__(self):
        self.pts, self.cor, self.vazio, self.sel = [], "#e8846b", "", None
        super().__init__()

    def definir(self, pts, cor, vazio=""):
        """pts: [(na, k, ca, area_px, oid)]"""
        self.pts, self.cor, self.vazio = list(pts), cor, vazio
        self.mudou()

    def desenhar(self, p, w, h, pal, alvos=None):
        T, L, R, _lado = self._geom(w)
        self._moldura(p, T, L, R, pal)
        if not self.pts:
            texto(p, QRectF(0, h - 22, w, 20), self.vazio or "sem objetos de feldspato ≥ area_min",
                  pal["mudo"], fonte(11), Qt.AlignmentFlag.AlignCenter)
            return
        amax = max(a for *_x, a, _o in self.pts)
        ordem = sorted(range(len(self.pts)), key=lambda i: -self.pts[i][3])     # grandes atrás
        for i in ordem:
            na, k, ca, a, oid = self.pts[i]
            q = self.ponto(T, L, R, ca, na, k)
            r = 4 + 5 * math.sqrt(a / amax)
            c = QColor(self.cor)
            c.setAlphaF(0.9)
            p.setPen(QPen(QColor(pal["sup"]), 2))
            p.setBrush(c)
            p.drawEllipse(q, r, r)
            if self.hover == ("o", oid) or self.sel == oid:
                p.setPen(QPen(QColor(pal["destaque"] if self.sel == oid else pal["texto"]), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(q, r + 3, r + 3)
            if alvos is not None:
                alvos.append(Alvo(("o", oid), f"objeto <b>#{oid}</b> · {a} px<br>Na <b>{na:.2f}</b> · K <b>{k:.2f}</b>"
                                  f" · Ca <b>{ca:.2f}</b>".replace(".", ","), ("obj", oid), ponto=q, raio=r + 4))
        # média ponderada pela área (anel na cor do texto + rótulo)
        A = np.array([[na, k, ca, a] for na, k, ca, a, _o in self.pts], np.float64)
        m = (A[:, :3] * A[:, 3:4]).sum(0) / A[:, 3].sum()
        q = self.ponto(T, L, R, m[2], m[0], m[1])
        p.setPen(QPen(QColor(pal["texto"]), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        desenhar_forma(p, "losango", q, 6)
        f = fonte(11)
        lw = QFontMetricsF(f).horizontalAdvance("média") + 10
        rr = QRectF(q.x() - lw / 2, q.y() - 30, lw, 17)                   # acima do losango, com fundo
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["sup"]))
        p.drawRoundedRect(rr, 4, 4)
        texto(p, rr, "média", pal["texto"], f, Qt.AlignmentFlag.AlignCenter)
        texto(p, QRectF(0, h - 22, w, 20), f"n = {len(self.pts)} objetos · média ponderada pela área: "
              f"Na {m[0]:.2f} · K {m[1]:.2f} · Ca {m[2]:.2f}".replace(".", ","), pal["texto2"], fonte(11),
              Qt.AlignmentFlag.AlignCenter)


# ================================ histograma ================================
class HistogramaDiametros(Grafico):
    """Diâmetro equivalente (eixo log) ponderado pela área: % da área de grãos por classe de tamanho.
    Clique numa barra (ou arraste por várias) destaca esses grãos no canvas."""
    ALT = 250
    ML, MR, MT, MB = 44, 12, 22, 40

    def __init__(self):
        self.diam = np.zeros(0)
        self.um2 = np.zeros(0)
        self.bordas = np.zeros(0)
        self.pct = np.zeros(0)
        self.n = np.zeros(0, int)
        self.d_min = self.d50 = self.marca = None
        self.sel = None            # (i0, i1) inclusivo
        self._arrasto = None
        super().__init__()

    def altura_para(self, w):
        return self.ALT

    def definir(self, diam, um2, d_min=None, d50=None):
        self.diam, self.um2 = np.asarray(diam, np.float64), np.asarray(um2, np.float64)
        self.d_min, self.d50, self.sel, self.marca = d_min, d50, None, None
        if self.diam.size:
            lo, hi = max(float(self.diam.min()), 0.1), float(self.diam.max()) + 1e-9
            if hi / lo < 1.5:
                lo, hi = lo / 1.25, hi * 1.25
            self.bordas = np.logspace(np.log10(lo), np.log10(hi), 41)       # = relatorio_final.py
            idx = np.clip(np.searchsorted(self.bordas, self.diam, side="right") - 1, 0, 39)
            area = np.bincount(idx, weights=self.um2, minlength=40)
            self.pct = 100 * area / max(area.sum(), 1e-12)
            self.n = np.bincount(idx, minlength=40)
        else:
            self.bordas, self.pct, self.n = np.zeros(0), np.zeros(0), np.zeros(0, int)
        self.update()

    def _dominio(self):
        lo, hi = float(self.bordas[0]), float(self.bordas[-1])
        lo = min(lo, 3.9 / 1.6, (self.d_min or lo) / 1.15)          # mostra sempre o limite de resolução
        hi = max(hi, 3.9 * 1.6)
        if hi > 20:
            hi = max(hi, 62.5 * 1.6)
        return math.log10(lo), math.log10(hi)

    def _x(self, d, w):
        a, b = self._dominio()
        return self.ML + (math.log10(d) - a) / (b - a) * (w - self.ML - self.MR)

    def desenhar(self, p, w, h, pal, alvos=None):
        if not self.bordas.size:
            texto(p, QRectF(0, 0, w, h), "sem grãos ≥ area_min", pal["mudo"], fonte(12), Qt.AlignmentFlag.AlignCenter)
            return
        y0, y1 = self.MT, h - self.MB
        passo = num_bonito(float(self.pct.max()) / 4, (1, 2, 2.5, 5, 10))
        ymax = passo * math.ceil(float(self.pct.max()) / passo)
        Y = lambda v: y1 - (v / ymax) * (y1 - y0)
        f_eixo = fonte(10, tabular=True)
        # grade horizontal + rótulos do eixo y (% da área)
        v = 0.0
        while v <= ymax + 1e-9:
            p.setPen(QPen(QColor(pal["grade"] if v > 0 else pal["eixo"]), 1))
            p.drawLine(QPointF(self.ML, Y(v)), QPointF(w - self.MR, Y(v)))
            texto(p, QRectF(0, Y(v) - 8, self.ML - 6, 16), f"{fmt(v, 0 if passo >= 1 else 1)} %", pal["mudo"], f_eixo,
                  Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            v += passo
        # faixas de Wentworth: divisas em linha fina + nome da classe no topo
        a, b = self._dominio()                                  # o domínio sempre contém 3,9 µm
        xs = [self.ML] + [self._x(d, w) for d in (3.9, 62.5) if a < math.log10(d) < b] + [w - self.MR]
        nomes = ("argila", "silte", "areia")[:len(xs) - 1]
        p.setPen(QPen(QColor(pal["eixo"]), 1))
        for x in xs[1:-1]:
            p.drawLine(QPointF(x, y0 - 14), QPointF(x, y1))
        for i in range(len(xs) - 1):
            texto(p, QRectF(xs[i] + 4, 2, xs[i + 1] - xs[i] - 8, 14), nomes[i], pal["mudo"], fonte(10),
                  Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # barras (2 px de vão, topo arredondado, no máximo 24 px de largura — o resto da faixa fica vazio)
        tem_sel = self.sel is not None
        for i in range(len(self.pct)):
            xa, xb = self._x(self.bordas[i], w) + 1, self._x(self.bordas[i + 1], w) - 1
            fa, fb = xa - 1, xb + 1                                   # alvo = a faixa inteira
            if xb - xa > 24:
                xm = (xa + xb) / 2
                xa, xb = xm - 12, xm + 12
            if self.pct[i] > 0:
                r = QRectF(xa, Y(self.pct[i]), max(1.0, xb - xa), y1 - Y(self.pct[i]))
                c = QColor(pal["serie"][0])
                if tem_sel and not (self.sel[0] <= i <= self.sel[1]):
                    c.setAlphaF(0.35)
                elif self.hover == ("b", i):
                    c = c.lighter(125)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                rad = min(4.0, (xb - xa) / 2, r.height())
                path = QPainterPath()
                path.addRoundedRect(r, rad, rad)
                path.addRect(QRectF(r.left(), r.bottom() - rad, r.width(), rad))   # base reta
                p.drawPath(path.simplified())
            if alvos is not None and self.n[i]:
                lo, hi = self.bordas[i], self.bordas[i + 1]
                alvos.append(Alvo(("b", i), f"<b>{fmt(self.pct[i], 1)} %</b> da área de grãos<br>"
                                  f"{fmt(lo, 2)}–{fmt(hi, 2)} µm · {fmt(self.n[i])} grãos",
                                  ("bins", i, i), rect=QRectF(fa, y0, fb - fa, y1 - y0)))
        # eixo x (log): marcas "bonitas"
        f = fonte(10, tabular=True)
        for d in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
            if a <= math.log10(d) <= b:
                x = self._x(d, w)
                p.setPen(QPen(QColor(pal["eixo"]), 1))
                p.drawLine(QPointF(x, y1), QPointF(x, y1 + 4))
                texto(p, QRectF(x - 20, y1 + 5, 40, 14), fmt(d, 1 if d < 1 else 0), pal["mudo"], f,
                      Qt.AlignmentFlag.AlignCenter)
        texto(p, QRectF(0, h - 17, w, 16), "diâmetro equivalente (µm, escala log)", pal["texto2"], fonte(10),
              Qt.AlignmentFlag.AlignCenter)
        # d_min (resolução) e D50: linha fina + rótulo no alto do gráfico (fora das barras e do eixo)
        for k, (dv, rot, cor) in enumerate(((self.d50, "D50", pal["texto2"]), (self.d_min, "d_min", pal["mudo"]))):
            if dv and a <= math.log10(dv) <= b:
                x = self._x(dv, w)
                p.setPen(QPen(QColor(cor), 1))
                p.drawLine(QPointF(x, y0 + 2 + 14 * k), QPointF(x, y1))
                s = f"{rot} {fmt(dv, 2)} µm"
                f = fonte(10)
                lw = QFontMetricsF(f).horizontalAdvance(s) + 6
                xl = x + 4 if x + 4 + lw <= w - self.MR else x - 4 - lw
                texto(p, QRectF(xl, y0 + 14 * k, lw, 14), s, cor, f)
        if self.marca and a <= math.log10(self.marca) <= b:
            x = self._x(self.marca, w)
            p.setPen(QPen(QColor(pal["destaque"]), 1.6))
            p.drawLine(QPointF(x, y0), QPointF(x, y1))

    def _bin_em(self, pos):
        if not self.bordas.size:
            return None
        a, b = self._dominio()
        w = self.width()
        t = (pos.x() - self.ML) / (w - self.ML - self.MR)
        d = 10 ** (a + t * (b - a))
        i = int(np.searchsorted(self.bordas, d, side="right") - 1)
        return i if 0 <= i < len(self.pct) else None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._arrasto = self._bin_em(e.position())

    def mouseMoveEvent(self, e):
        if self._arrasto is not None and e.buttons() & Qt.MouseButton.LeftButton:
            i = self._bin_em(e.position())
            if i is not None:
                self.sel = (min(i, self._arrasto), max(i, self._arrasto))
                self.update()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._arrasto is None:
            return
        i = self._bin_em(e.position())
        i0 = self._arrasto
        self._arrasto = None
        if i is None:
            self.sel = None
            self.ativado.emit(None)
        else:
            self.sel = (min(i, i0), max(i, i0))
            if self.n[self.sel[0]:self.sel[1] + 1].sum() == 0:
                self.sel = None
                self.ativado.emit(None)
            else:
                self.ativado.emit(("bins", float(self.bordas[self.sel[0]]), float(self.bordas[self.sel[1] + 1])))
        self.update()


# ================================ mapa de calor ================================
class MapaCalor(Grafico):
    """Linhas × colunas em rampa sequencial; valores escritos só onde importam (máximo da linha e
    ≥ limiar) — o resto fica na dica e no CSV. Clique na linha = ativado(dado da linha)."""
    LH = 22

    def __init__(self, unidade="fração de cátions", limiar=0.2, casas=2, escala_fixa=None):
        self.linhas, self.cols, self.M = [], [], np.zeros((0, 0))
        self.unidade, self.limiar, self.casas, self.escala_fixa = unidade, limiar, casas, escala_fixa
        self.sel = None
        super().__init__()

    def definir(self, linhas, cols, M):
        """linhas: [(rótulo, cor ou None, dado)]"""
        self.linhas, self.cols, self.M = list(linhas), list(cols), np.asarray(M, np.float64)
        self.mudou()

    def _lab_w(self):
        fm = QFontMetricsF(fonte(11))
        sw = 20 if any(c for _r, c, _d in self.linhas) else 4
        return min(180.0, max([fm.horizontalAdvance(r) for r, _c, _d in self.linhas] + [40.0]) + sw + 12)

    def _girar(self, w):
        cw = (w - self._lab_w()) / max(1, len(self.cols))
        fm = QFontMetricsF(fonte(10))
        return any(fm.horizontalAdvance(c) > cw - 4 for c in self.cols)

    def _topo(self, w):
        if not self._girar(w):
            return 20
        fm = QFontMetricsF(fonte(10))
        return 10 + max([fm.horizontalAdvance(c) for c in self.cols] + [10]) * 0.72

    def altura_para(self, w):
        return int(self._topo(w) + len(self.linhas) * self.LH + 44) if self.linhas else 60

    def desenhar(self, p, w, h, pal, alvos=None):
        if not self.linhas:
            texto(p, QRectF(0, 0, w, h), "sem dados", pal["mudo"], fonte(12), Qt.AlignmentFlag.AlignCenter)
            return
        lw = self._lab_w()
        top = self._topo(w)
        nc = max(1, len(self.cols))
        cw = (w - lw) / nc
        vmax = self.escala_fixa or max(float(self.M.max()), 1e-9)
        girar = self._girar(w)
        f_col = fonte(10)
        for j, c in enumerate(self.cols):
            cx = lw + (j + 0.5) * cw
            if girar:
                p.save()
                p.translate(cx - 2, top - 4)
                p.rotate(-45)
                texto(p, QRectF(0, -8, 200, 14), c, pal["texto2"], f_col)
                p.restore()
            else:
                texto(p, QRectF(cx - cw / 2, 2, cw, 16), c, pal["texto2"], f_col, Qt.AlignmentFlag.AlignCenter)
        f_lab, f_val = fonte(11), fonte(10, tabular=True)
        for i, (rot, cor, dado) in enumerate(self.linhas):
            y = top + i * self.LH
            if self.hover == ("l", i) or (self.sel is not None and self.sel == dado):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["grade"]))
                p.drawRoundedRect(QRectF(0, y, lw - 4, self.LH - 2), 4, 4)
            x_txt = 4
            if cor:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(cor))
                p.drawRoundedRect(QRectF(4, y + 6, 10, 10), 2.5, 2.5)
                x_txt = 20
            fm = QFontMetricsF(f_lab)
            texto(p, QRectF(x_txt, y, lw - x_txt - 6, self.LH - 2), fm.elidedText(rot, Qt.TextElideMode.ElideRight,
                                                                                  lw - x_txt - 6), pal["texto"], f_lab)
            vals = self.M[i] if self.M.size else []
            jmax = int(np.argmax(vals)) if len(vals) else -1
            for j, v in enumerate(vals):
                r = QRectF(lw + j * cw + 1, y + 1, cw - 2, self.LH - 2)          # 2 px de vão entre células
                fc = cor_rampa(v / vmax, pal)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fc)
                p.drawRoundedRect(r, 2, 2)
                if (j == jmax or v >= self.limiar) and v > 0 and cw >= 26:
                    s = fmt(v, self.casas)
                    if QFontMetricsF(f_val).horizontalAdvance(s) <= cw - 4:
                        texto(p, r, s, tinta_sobre(fc, pal), f_val, Qt.AlignmentFlag.AlignCenter)
                if alvos is not None:
                    alvos.append(Alvo(("c", i, j), f"{rot} · {self.cols[j]} = <b>{fmt(v, max(self.casas, 3))}</b>"
                                      f" <span style='color:#a5abb2'>({self.unidade})</span>", dado, rect=r))
            if alvos is not None:
                alvos.append(Alvo(("l", i), f"<b>{rot}</b> — clique destaca no canvas" if dado is not None else rot,
                                  dado, rect=QRectF(0, y, lw, self.LH)))
        # escala (gradiente) — sem ela a cor não diz o valor
        y = top + len(self.linhas) * self.LH + 12
        gw = min(220.0, w - lw - 60)
        g = QLinearGradient(lw, 0, lw + gw, 0)
        for k in range(11):
            g.setColorAt(k / 10, cor_rampa(k / 10, pal))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(lw, y, gw, 8), 3, 3)
        f = fonte(10, tabular=True)
        texto(p, QRectF(lw - 30, y - 4, 26, 16), "0", pal["mudo"], f, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        texto(p, QRectF(lw + gw + 4, y - 4, 200, 16), f"{fmt(vmax, self.casas)} · {self.unidade}", pal["mudo"], f)


# ================================ tabela ================================
class Tabela(Grafico):
    """Tabela desenhada (vai igual para o PNG/SVG). colunas: [(título, peso, 'e'|'d')];
    linhas: [(valores, cor do quadradinho ou None, dado)]. Clique na linha = ativado(dado)."""
    LH, CAB = 22, 24

    def __init__(self, colunas):
        self.colunas, self.linhas, self.sel, self.rodape = list(colunas), [], None, ""
        super().__init__()

    def definir(self, linhas, rodape=""):
        self.linhas, self.rodape = list(linhas), rodape
        self.mudou()

    def altura_para(self, w):
        return self.CAB + max(1, len(self.linhas)) * self.LH + (22 if self.rodape else 4)

    def _xs(self, w):
        tot = sum(c[1] for c in self.colunas)
        xs, x = [], 0.0
        for c in self.colunas:
            xs.append(x)
            x += c[1] / tot * w
        return xs + [w]

    def desenhar(self, p, w, h, pal, alvos=None):
        xs = self._xs(w)
        f_cab, f_txt, f_num = fonte(10, QFont.Weight.DemiBold), fonte(11), fonte(11, tabular=True)
        for k, (tit, _pw, al) in enumerate(self.colunas):
            a = Qt.AlignmentFlag.AlignRight if al == "d" else Qt.AlignmentFlag.AlignLeft
            texto(p, QRectF(xs[k] + 4, 0, xs[k + 1] - xs[k] - 8, self.CAB - 4), tit, pal["mudo"], f_cab,
                  a | Qt.AlignmentFlag.AlignVCenter)
        p.setPen(QPen(QColor(pal["eixo"]), 1))
        p.drawLine(QPointF(0, self.CAB - 1), QPointF(w, self.CAB - 1))
        if not self.linhas:
            texto(p, QRectF(0, self.CAB, w, self.LH), "—", pal["mudo"], f_txt, Qt.AlignmentFlag.AlignCenter)
        for i, (vals, cor, dado) in enumerate(self.linhas):
            y = self.CAB + i * self.LH
            r = QRectF(0, y, w, self.LH)
            selec = self.sel is not None and self.sel == dado
            if self.hover == ("l", i) or selec:
                p.setPen(Qt.PenStyle.NoPen)
                c = QColor(pal["destaque"]) if selec else QColor(pal["grade"])
                if selec:
                    c.setAlphaF(0.16)
                p.setBrush(c)
                p.drawRect(r)
            for k, v in enumerate(vals):
                x0 = xs[k] + 4
                if k == 0 and cor:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(cor))
                    p.drawRoundedRect(QRectF(x0, y + 6, 10, 10), 2.5, 2.5)
                    x0 += 16
                al = self.colunas[k][2]
                f = f_num if al == "d" else f_txt
                larg = xs[k + 1] - x0 - 4
                s = QFontMetricsF(f).elidedText(str(v), Qt.TextElideMode.ElideRight, larg)
                texto(p, QRectF(x0, y, larg, self.LH), s, pal["texto"] if k == 0 else pal["texto2"], f,
                      (Qt.AlignmentFlag.AlignRight if al == "d" else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
            p.setPen(QPen(QColor(pal["grade"]), 1))
            p.drawLine(QPointF(0, y + self.LH - 0.5), QPointF(w, y + self.LH - 0.5))
            if alvos is not None:
                alvos.append(Alvo(("l", i), (f"<b>{vals[0]}</b> — clique destaca no canvas" if dado is not None
                                             else ""), dado, rect=r))
        if self.rodape:
            texto(p, QRectF(0, h - 20, w, 18), self.rodape, pal["mudo"], fonte(10))


# ================================ imagem (exportação) ================================
class Imagem(Grafico):
    """Composição do canvas + legenda dos minerais (só na exportação)."""

    def __init__(self, qimage, legenda):
        self.img, self.legenda = qimage, list(legenda)
        super().__init__()

    def _linhas_leg(self, w):
        fm = QFontMetricsF(fonte(11))
        x, n = 0, 1
        for nome, _c in self.legenda:
            lw = fm.horizontalAdvance(nome) + 28
            if x + lw > w and x > 0:
                n, x = n + 1, 0
            x += lw
        return n if self.legenda else 0

    def altura_para(self, w):
        return int(w * self.img.height() / max(1, self.img.width())) + 8 + 20 * self._linhas_leg(w)

    def desenhar(self, p, w, h, pal, alvos=None):
        ih = w * self.img.height() / max(1, self.img.width())
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, w, ih), self.img)
        fm = QFontMetricsF(fonte(11))
        x, y = 0.0, ih + 8
        for nome, cor in self.legenda:
            lw = fm.horizontalAdvance(nome) + 28
            if x + lw > w and x > 0:
                x, y = 0.0, y + 20
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(cor))
            p.drawRoundedRect(QRectF(x, y + 4, 10, 10), 2.5, 2.5)
            texto(p, QRectF(x + 15, y, lw - 15, 18), nome, pal["texto2"], fonte(11))
            x += lw


# ================================ figura (PNG / SVG) ================================
def compor_figura(p, largura, pal, titulo, subtitulo, blocos, margem=28, vao=16):
    """Desenha a figura inteira. blocos: [(título do cartão, gráfico, colunas 1|2)] em grade de 2.
    Devolve a altura total (chamar com p=None só mede)."""
    col_w = (largura - 2 * margem - vao) / 2
    pad = 16
    y = margem + 58
    linhas, atual = [], []
    for b in blocos:
        if b[2] == 2:
            if atual:
                linhas.append(atual)
                atual = []
            linhas.append([b])
        else:
            atual.append(b)
            if len(atual) == 2:
                linhas.append(atual)
                atual = []
    if atual:
        linhas.append(atual)
    geom = []
    for ln in linhas:
        alt = 0
        for tit, g, cols in ln:
            wg = (largura - 2 * margem if cols == 2 else col_w) - 2 * pad
            alt = max(alt, g.altura_para(wg) + 2 * pad + (22 if tit else 0))
        geom.append((y, alt))
        y += alt + vao
    total = int(y - vao + margem)
    if p is None:
        return total
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(QRectF(0, 0, largura, total), QColor(pal["fundo"]))
    texto(p, QRectF(margem, margem, largura - 2 * margem, 28), titulo, pal["texto"], fonte(20, QFont.Weight.DemiBold))
    texto(p, QRectF(margem, margem + 30, largura - 2 * margem, 18), subtitulo, pal["texto2"], fonte(12))
    for ln, (y, alt) in zip(linhas, geom):
        x = margem
        for tit, g, cols in ln:
            cw = largura - 2 * margem if cols == 2 else col_w
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["sup"]))
            p.drawRoundedRect(QRectF(x, y, cw, alt), 10, 10)
            yy = y + pad
            if tit:
                texto(p, QRectF(x + pad, yy, cw - 2 * pad, 16), tit.upper(), pal["mudo"], fonte(10, QFont.Weight.DemiBold))
                yy += 22
            wg = cw - 2 * pad
            p.save()
            p.translate(x + pad, yy)
            g.desenhar(p, wg, g.altura_para(wg), pal, None)
            p.restore()
            x += cw + vao
    return total


def exportar_png(caminho, largura, pal, titulo, subtitulo, blocos, escala=2):
    from PyQt6.QtGui import QImage
    alt = compor_figura(None, largura, pal, titulo, subtitulo, blocos)
    img = QImage(int(largura * escala), int(alt * escala), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDotsPerMeterX(int(96 * escala / 0.0254))
    img.setDotsPerMeterY(int(96 * escala / 0.0254))
    p = QPainter(img)
    p.scale(escala, escala)
    compor_figura(p, largura, pal, titulo, subtitulo, blocos)
    p.end()
    if not img.save(str(caminho), "PNG"):
        raise OSError(f"não foi possível gravar {caminho}")
    return img.width(), img.height()


def exportar_svg(caminho, largura, pal, titulo, subtitulo, blocos):
    from PyQt6.QtCore import QSize as _QSize
    from PyQt6.QtSvg import QSvgGenerator
    alt = compor_figura(None, largura, pal, titulo, subtitulo, blocos)
    gen = QSvgGenerator()
    gen.setFileName(str(caminho))
    gen.setSize(_QSize(int(largura), int(alt)))
    gen.setViewBox(QRectF(0, 0, largura, alt))
    gen.setTitle(titulo)
    gen.setDescription(subtitulo)
    gen.setResolution(96)
    p = QPainter(gen)
    compor_figura(p, largura, pal, titulo, subtitulo, blocos)
    p.end()
    return largura, alt
