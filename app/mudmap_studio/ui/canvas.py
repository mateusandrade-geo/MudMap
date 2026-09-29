"""Canvas de imagem: zoom na roda (em torno do cursor), arrastar = mover, pirâmide de
níveis (imagens até 4096² desenham só o trecho visível no nível adequado), camadas de
contorno em coordenadas da imagem, caixas de seleção, régua em µm e barra de escala."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from . import tema
from .comum import num_bonito
from .contraste import fmt_valor

ZMAX = 48.0


def rgb_para_qimage(rgb):
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def construir_niveis(rgb, fator=1):
    """Pirâmide [(QImage, fator)] — só QImage (seguro fora da thread da interface).
    fator = subamostragem da imagem base (prévia progressiva: 1 px = `fator` px da amostra)."""
    img = rgb_para_qimage(rgb)
    niveis, f, cur = [(img, fator)], fator, img
    while max(cur.width(), cur.height()) > 768:
        f *= 2
        cur = cur.scaled(max(1, cur.width() // 2), max(1, cur.height() // 2),
                         Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        niveis.append((cur, f))
    return niveis


def fmt_um(v):
    if v >= 100:
        s = f"{v:.0f}"
    elif v >= 10:
        s = f"{v:.1f}"
    else:
        s = f"{v:.2f}"
    return s.replace(".", ",") + " µm"


FERR_TRACO = {"pincel", "borracha"}
FERR_CLIQUE = {"balde", "contagotas", "remover"}
FERR_ARRASTO = {"retangulo", "elipse"}


class Canvas(QWidget):
    hover = pyqtSignal(int, int)            # -1, -1 = fora da imagem
    clique = pyqtSignal(int, int, object)   # x, y, modificadores
    zoomMudou = pyqtSignal(float)
    reguaMudou = pyqtSignal(object)         # comprimento em µm (float) ou None
    # edição
    tracoInicio = pyqtSignal(float, float, object)
    tracoPonto = pyqtSignal(float, float)
    tracoFim = pyqtSignal()
    cliqueFerramenta = pyqtSignal(int, int, object)
    formaConcluida = pyqtSignal(str, object)    # tipo, [(x, y), ...] em coords da imagem
    pontosMudaram = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(240, 200)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._niveis = []
        self._w = self._h = 0
        self._esc = 1.0
        self._off = QPointF(0, 0)
        self._ajustado = False
        self._press = None
        self._off_ini = None
        self._moveu = False
        self._pan_meio = None
        self._hover = (-1, -1)
        self._camadas = {}
        self._caixas = {}
        self._regua = None
        self._legenda = None
        self.ferramenta = "mao"
        self.pixel_um = None
        self.raio_pincel = 8.0
        self.cor_ferramenta = QColor(tema.C["acento_forte"])
        self._traco = False
        self._forma = None
        self._cursor_img = None
        self.pontos = []
        self.msg_vazio = "Abra um .mudmap ou importe uma pasta do projeto"

    # ---------- imagem ----------
    def set_niveis(self, niveis, manter_vista=True, tamanho=None):
        """tamanho = (L, A) da amostra em px (obrigatório p/ prévias subamostradas)."""
        img, f = niveis[0]
        w, h = tamanho if tamanho else (img.width() * f, img.height() * f)
        novo_tam = (w, h) != (self._w, self._h)
        self._w, self._h = w, h
        self._niveis = niveis
        if novo_tam or not manter_vista or not self._ajustado:
            self.ajustar()
        self.update()

    def atualizar_regiao(self, x0, y0, rgb):
        """Remenda a região editada em todos os níveis da pirâmide (sem recompor a imagem)."""
        if not self._niveis:
            return
        qi = rgb_para_qimage(rgb)
        h, w = rgb.shape[:2]
        for img, f in self._niveis:
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, f > 1)
            p.drawImage(QRectF(x0 / f, y0 / f, w / f, h / f), qi)
            p.end()
        self.update()

    # ---------- ferramentas de edição ----------
    def set_ferramenta(self, nome):
        self.ferramenta = nome
        self._forma = None
        self._traco = False
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def cancelar_forma(self):
        self._forma = None
        self.update()

    def fechar_poligono(self):
        f = self._forma
        if f and f["tipo"] == "poligono" and len(f["pts"]) >= 3:
            self.formaConcluida.emit("poligono", [(q.x(), q.y()) for q in f["pts"]])
        self._forma = None
        self.update()

    def remover_ultimo_vertice(self):
        f = self._forma
        if f and f["tipo"] == "poligono" and f["pts"]:
            f["pts"].pop()
            if not f["pts"]:
                self._forma = None
            self.update()

    def limpar_pontos(self):
        self.pontos = []
        self.pontosMudaram.emit(0)
        self.update()

    def set_legenda(self, legenda=None):
        """None | ("rampa", titulo, lut(256x3), lo, hi) | ("chips", [(rótulo, cor), ...])"""
        self._legenda = legenda
        self.update()

    def limpar(self):
        self._niveis, self._w, self._h = [], 0, 0
        self._camadas.clear()
        self._caixas.clear()
        self._regua = None
        self._legenda = None
        self._ajustado = False
        self.update()

    @property
    def tem_imagem(self):
        return bool(self._niveis)

    @property
    def fator_base(self):
        """1 = imagem em resolução cheia; >1 = ainda é a prévia subamostrada."""
        return self._niveis[0][1] if self._niveis else 1

    @property
    def escala(self):
        return self._esc

    # ---------- camadas vetoriais / contornos ----------
    def set_camada(self, chave, qimage=None, x0=0, y0=0):
        if qimage is None:
            self._camadas.pop(chave, None)
        else:
            self._camadas[chave] = (qimage, x0, y0)
        self.update()

    def set_caixa(self, chave, bbox=None, cor=None, tracejado=False):
        if bbox is None:
            self._caixas.pop(chave, None)
        else:
            self._caixas[chave] = (tuple(int(v) for v in bbox), QColor(cor), tracejado)
        self.update()

    def limpar_regua(self):
        self._regua = None
        self.reguaMudou.emit(None)
        self.update()

    # ---------- vista ----------
    def _esc_ajuste(self):
        if not self._w:
            return 1.0
        m = 16
        return max(1e-3, min((self.width() - 2 * m) / self._w, (self.height() - 2 * m) / self._h))

    def ajustar(self):
        if not self._w:
            return
        self._esc = self._esc_ajuste()
        self._off = QPointF((self.width() - self._w * self._esc) / 2,
                            (self.height() - self._h * self._esc) / 2)
        self._ajustado = True
        self.zoomMudou.emit(self._esc)
        self.update()

    def um_para_um(self):
        c = QPointF(self.width() / 2, self.height() / 2)
        self._zoom_absoluto(1.0, c)

    def _zoom_absoluto(self, esc, centro):
        pi = self.tela_para_img(centro)
        self._esc = float(min(ZMAX, max(self._esc_ajuste() * 0.5, esc)))
        self._off = QPointF(centro.x() - pi.x() * self._esc, centro.y() - pi.y() * self._esc)
        self.zoomMudou.emit(self._esc)
        self.update()

    def zoom_em(self, fator, centro):
        self._zoom_absoluto(self._esc * fator, centro)

    def zoom_para(self, x0, y0, x1, y1, margem=0.6, esc_max=12.0):
        x0, y0, x1, y1 = (float(v) for v in (x0, y0, x1, y1))   # bbox pode vir em numpy
        bw, bh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        esc = min(self.width() / (bw * (1 + 2 * margem)), self.height() / (bh * (1 + 2 * margem)))
        self._esc = min(esc_max, max(self._esc_ajuste() * 0.5, esc))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self._off = QPointF(self.width() / 2 - cx * self._esc, self.height() / 2 - cy * self._esc)
        self.zoomMudou.emit(self._esc)
        self.update()

    def tela_para_img(self, p):
        return QPointF((p.x() - self._off.x()) / self._esc, (p.y() - self._off.y()) / self._esc)

    def img_para_tela(self, p):
        return QPointF(p.x() * self._esc + self._off.x(), p.y() * self._esc + self._off.y())

    def _pixel(self, pos):
        pi = self.tela_para_img(pos)
        x, y = math.floor(pi.x()), math.floor(pi.y())
        if 0 <= x < self._w and 0 <= y < self._h:
            return x, y
        return -1, -1

    # ---------- desenho ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(tema.C["fundo"]))
        if not self._niveis:
            p.setPen(QColor(tema.C["mudo"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.msg_vazio)
            return
        k = 0
        for i, (_img, f) in enumerate(self._niveis):
            if self._esc * f <= 1.0 + 1e-6:
                k = i
        img, f = self._niveis[k]
        en = self._esc * f
        vis = QRectF(-self._off.x() / en, -self._off.y() / en, self.width() / en, self.height() / en)
        src = vis.intersected(QRectF(0, 0, img.width(), img.height()))
        if not src.isEmpty():
            x0, y0 = math.floor(src.left()), math.floor(src.top())
            x1, y1 = math.ceil(src.right()), math.ceil(src.bottom())
            dst = QRectF(self._off.x() + x0 * en, self._off.y() + y0 * en, (x1 - x0) * en, (y1 - y0) * en)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, bool(en < 1.0))
            p.drawImage(dst, img, QRectF(x0, y0, x1 - x0, y1 - y0))
        # contornos (resolução cheia)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, bool(self._esc < 1.0))
        for qi, x0, y0 in self._camadas.values():
            p.drawImage(QRectF(self._off.x() + x0 * self._esc, self._off.y() + y0 * self._esc,
                               qi.width() * self._esc, qi.height() * self._esc), qi)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # caixas de seleção
        for (x0, y0, x1, y1), cor, trac in self._caixas.values():
            r = QRectF(self.img_para_tela(QPointF(x0, y0)), self.img_para_tela(QPointF(x1, y1)))
            r = r.adjusted(-4, -4, 4, 4)
            pen = QPen(cor, 1.6)
            if trac:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 5, 5)
        # pixel sob o cursor (zoom alto)
        if self._esc >= 10 and self._hover[0] >= 0:
            a = self.img_para_tela(QPointF(*self._hover))
            p.setPen(QPen(QColor(255, 255, 255, 170), 1))
            p.drawRect(QRectF(a.x(), a.y(), self._esc, self._esc))
        self._desenha_edicao(p)
        self._desenha_regua(p)
        self._desenha_escala(p)
        self._desenha_legenda(p)

    def _desenha_edicao(self, p):
        cor = QColor(self.cor_ferramenta)
        # pontos (pontos -> regiões)
        if self.pontos:
            p.setPen(QPen(QColor(0, 0, 0, 200), 1.5))
            p.setBrush(QColor(tema.C["selA"]))
            for x, y in self.pontos:
                p.drawEllipse(self.img_para_tela(QPointF(x, y)), 4.5, 4.5)
        # forma em construção
        f = self._forma
        if f:
            pts = [self.img_para_tela(q) for q in f["pts"]]
            fill = QColor(cor)
            fill.setAlpha(55)
            pen = QPen(cor, 1.6, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(fill)
            if f["tipo"] in FERR_ARRASTO and len(pts) >= 2:
                r = QRectF(pts[0], pts[-1]).normalized()
                (p.drawRect if f["tipo"] == "retangulo" else p.drawEllipse)(r)
            elif f["tipo"] == "laco" and len(pts) >= 2:
                p.drawPolygon(QPolygonF(pts))
            elif f["tipo"] == "poligono":
                cur = f.get("cursor")
                seq = pts + ([self.img_para_tela(cur)] if cur is not None else [])
                if len(seq) >= 3:
                    p.drawPolygon(QPolygonF(seq))
                elif len(seq) == 2:
                    p.drawLine(seq[0], seq[1])
                p.setPen(QPen(QColor(0, 0, 0, 200), 1))
                p.setBrush(cor)
                for q in pts:
                    p.drawRect(QRectF(q.x() - 3, q.y() - 3, 6, 6))
        # cursor do pincel/borracha
        if self.ferramenta in FERR_TRACO and self._cursor_img is not None:
            c = self.img_para_tela(self._cursor_img)
            r = max(2.0, self.raio_pincel * self._esc)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 180), 3))
            p.drawEllipse(c, r, r)
            p.setPen(QPen(QColor(255, 255, 255, 230) if self.ferramenta == "pincel" else QColor(tema.C["perigo"]), 1.4))
            p.drawEllipse(c, r, r)

    def _desenha_legenda(self, p):
        if not self._legenda:
            return
        f = QFont(p.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = p.fontMetrics()
        if self._legenda[0] == "rampa":
            _, titulo, lut, lo, hi = self._legenda
            w_bar = 180
            w = max(w_bar, fm.horizontalAdvance(titulo)) + 20
            r = QRectF(self.width() - w - 12, self.height() - 62, w, 50)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 17, 20, 210))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor(tema.C["texto"]))
            p.drawText(QRectF(r.left() + 10, r.top() + 4, w - 20, 16), Qt.AlignmentFlag.AlignLeft, titulo)
            x0, y0 = r.left() + 10, r.top() + 22
            g = QLinearGradient(x0, 0, x0 + w_bar, 0)          # rampa = gradiente com 16 paradas da LUT
            for k in range(16):
                c = lut[round(k * 255 / 15)]
                g.setColorAt(k / 15, QColor(int(c[0]), int(c[1]), int(c[2])))
            p.fillRect(QRectF(x0, y0, w_bar, 9), g)
            p.setPen(QColor(tema.C["texto2"]))
            p.drawText(QRectF(x0, y0 + 11, w_bar / 2, 14), Qt.AlignmentFlag.AlignLeft, fmt_valor(lo, lo, hi))
            p.drawText(QRectF(x0 + w_bar / 2, y0 + 11, w_bar / 2, 14), Qt.AlignmentFlag.AlignRight,
                       fmt_valor(hi, lo, hi))
        else:
            chips = self._legenda[1]
            larg = sum(fm.horizontalAdvance(t) + 26 for t, _ in chips) + 12
            r = QRectF(self.width() - larg - 12, self.height() - 44, larg, 32)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 17, 20, 210))
            p.drawRoundedRect(r, 6, 6)
            x = r.left() + 10
            for t, cor in chips:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(cor))
                p.drawRoundedRect(QRectF(x, r.top() + 10, 12, 12), 3, 3)
                p.setPen(QColor(tema.C["texto"]))
                tw = fm.horizontalAdvance(t)
                p.drawText(QRectF(x + 16, r.top() + 6, tw + 4, 20), Qt.AlignmentFlag.AlignVCenter, t)
                x += tw + 26

    def _caixa_texto(self, p, centro, texto):
        f = QFont(p.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(texto) + 14, fm.height() + 6
        r = QRectF(centro.x() - w / 2, centro.y() - h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 17, 20, 215))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor(tema.C["texto"]))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, texto)

    def _desenha_regua(self, p):
        if not self._regua:
            return
        a, b = (self.img_para_tela(q) for q in self._regua)
        cor = QColor(tema.C["selA"])
        p.setPen(QPen(QColor(0, 0, 0, 140), 4))
        p.drawLine(a, b)
        p.setPen(QPen(cor, 2))
        p.drawLine(a, b)
        p.setBrush(cor)
        for q in (a, b):
            p.drawEllipse(q, 3.5, 3.5)
        comp = self.comprimento_regua()
        if comp is not None:
            meio = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2 - 16)
            self._caixa_texto(p, meio, fmt_um(comp))

    def comprimento_regua(self):
        if not self._regua or not self.pixel_um:
            return None
        a, b = self._regua
        return math.hypot(b.x() - a.x(), b.y() - a.y()) * self.pixel_um

    def _desenha_escala(self, p):
        if not self.pixel_um:
            return
        um_por_px = self.pixel_um / self._esc
        L = num_bonito(110 * um_por_px)
        comp = L / um_por_px
        texto = fmt_um(L)
        f = QFont(p.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(texto)
        w = max(comp, tw) + 20
        r = QRectF(12, self.height() - 44, w, 32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 17, 20, 200))
        p.drawRoundedRect(r, 6, 6)
        x0 = r.left() + (w - comp) / 2
        yb = r.bottom() - 9
        p.setPen(QPen(QColor(tema.C["texto"]), 2))
        p.drawLine(QPointF(x0, yb), QPointF(x0 + comp, yb))
        p.drawLine(QPointF(x0, yb - 4), QPointF(x0, yb + 1))
        p.drawLine(QPointF(x0 + comp, yb - 4), QPointF(x0 + comp, yb + 1))
        p.drawText(QRectF(r.left(), r.top() + 2, w, 16), Qt.AlignmentFlag.AlignCenter, texto)

    # ---------- mouse ----------
    # Meio = mover sempre. Esquerdo depende da ferramenta; direito cancela a forma em curso
    # (no polígono, fecha; nos pontos, remove o ponto mais próximo).
    def mousePressEvent(self, e):
        if not self._niveis:
            return
        pos = e.position()
        pi = self.tela_para_img(pos)
        ferr = self.ferramenta
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_meio = (pos, QPointF(self._off))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() == Qt.MouseButton.RightButton:
            if ferr == "poligono" and self._forma:
                self.fechar_poligono()
            elif ferr == "pontos" and self.pontos:
                d = [math.hypot(x - pi.x(), y - pi.y()) for x, y in self.pontos]
                k = min(range(len(d)), key=d.__getitem__)
                if d[k] * self._esc < 14:
                    self.pontos.pop(k)
                    self.pontosMudaram.emit(len(self.pontos))
                    self.update()
            else:
                self.cancelar_forma()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._press, self._off_ini, self._moveu = pos, QPointF(self._off), False
        if ferr == "regua":
            self._regua = [pi, QPointF(pi)]
            self.update()
        elif ferr in FERR_TRACO:
            if e.modifiers() & Qt.KeyboardModifier.AltModifier:        # Alt+clique = conta-gotas
                self.cliqueFerramenta.emit(*self._pixel(pos), e.modifiers())
                self._press = None
            else:
                self._traco = True
                self.tracoInicio.emit(pi.x(), pi.y(), e.modifiers())
        elif ferr in FERR_CLIQUE:
            x, y = self._pixel(pos)
            if x >= 0:
                self.cliqueFerramenta.emit(x, y, e.modifiers())
        elif ferr in FERR_ARRASTO:
            self._forma = {"tipo": ferr, "pts": [pi, QPointF(pi)]}
        elif ferr == "laco":
            self._forma = {"tipo": "laco", "pts": [pi]}
        elif ferr == "poligono":
            if not self._forma or self._forma["tipo"] != "poligono":
                self._forma = {"tipo": "poligono", "pts": []}
            self._forma["pts"].append(pi)
            self.update()
        elif ferr == "pontos":
            self.pontos.append((pi.x(), pi.y()))
            self.pontosMudaram.emit(len(self.pontos))
            self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        pi = self.tela_para_img(pos)
        ferr = self.ferramenta
        if ferr in FERR_TRACO:
            self._cursor_img = pi
            self.update()
        if self._pan_meio:
            ini, off = self._pan_meio
            self._off = off + (pos - ini)
            self.update()
        elif self._traco:
            self.tracoPonto.emit(pi.x(), pi.y())
        elif self._forma and self._press is not None and self._forma["tipo"] in FERR_ARRASTO:
            self._forma["pts"][1] = pi
            self.update()
        elif self._forma and self._press is not None and self._forma["tipo"] == "laco":
            u = self._forma["pts"][-1]
            if math.hypot(pi.x() - u.x(), pi.y() - u.y()) * self._esc > 2:
                self._forma["pts"].append(pi)
                self.update()
        elif self._forma and self._forma["tipo"] == "poligono":
            self._forma["cursor"] = pi
            self.update()
        elif self._press is not None:
            if ferr == "regua" and self._regua:
                self._regua[1] = pi
                self.reguaMudou.emit(self.comprimento_regua())
                self.update()
            elif ferr == "mao":
                if (pos - self._press).manhattanLength() > 4:
                    self._moveu = True
                if self._moveu:
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    self._off = self._off_ini + (pos - self._press)
                    self.update()
        px = self._pixel(pos) if self._niveis else (-1, -1)
        if px != self._hover:
            self._hover = px
            self.hover.emit(*px)
            if self._esc >= 10:
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and self._pan_meio:
            self._pan_meio = None
        elif e.button() == Qt.MouseButton.LeftButton:
            if self._traco:
                self._traco = False
                self.tracoFim.emit()
            elif self._forma and self._forma["tipo"] in FERR_ARRASTO and self._press is not None:
                a, b = self._forma["pts"]
                if abs(b.x() - a.x()) * self._esc > 2 and abs(b.y() - a.y()) * self._esc > 2:
                    self.formaConcluida.emit(self._forma["tipo"], [(a.x(), a.y()), (b.x(), b.y())])
                self._forma = None
                self.update()
            elif self._forma and self._forma["tipo"] == "laco":
                pts = self._forma["pts"]
                if len(pts) >= 3:
                    self.formaConcluida.emit("laco", [(q.x(), q.y()) for q in pts])
                self._forma = None
                self.update()
            elif self._press is not None and self.ferramenta == "mao" and not self._moveu:
                x, y = self._pixel(e.position())
                self.clique.emit(x, y, e.modifiers())
            self._press = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseDoubleClickEvent(self, e):
        if self.ferramenta == "poligono" and e.button() == Qt.MouseButton.LeftButton:
            self.fechar_poligono()

    def leaveEvent(self, _e):
        self._cursor_img = None
        if self._hover != (-1, -1):
            self._hover = (-1, -1)
            self.hover.emit(-1, -1)
        self.update()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d and self._niveis:
            self.zoom_em(1.15 ** (d / 120), e.position())

    def resizeEvent(self, e):
        if not self._niveis:
            return
        if not self._ajustado:
            self.ajustar()
            return
        old = e.oldSize()
        if old.width() > 0 and old.height() > 0:
            c_old = QPointF(old.width() / 2, old.height() / 2)
            pi = self.tela_para_img(c_old)
            self._off = QPointF(self.width() / 2 - pi.x() * self._esc, self.height() / 2 - pi.y() * self._esc)
