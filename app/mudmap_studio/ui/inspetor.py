"""Painel do modo Inspetor: ficha do grão (ou média do mineral para pixel fino),
composição em fração/bruta, ternário Na-K-Ca do feldspato e comparação A × B."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from ..nucleo.objetos import CLASSES, classificar_feldspato
from . import tema
from .comum import fmt
from .graficos import TernarioFicha


def escala_frac(vmax):
    return 0.55 if vmax <= 0.55 else math.ceil(vmax * 10) / 10


def escala_raw(vmax):
    for s in (10, 20, 25, 50, 75, 100, 150, 200, 255):
        if vmax <= s:
            return s
    return 255


class BarrasComposicao(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.els, self.a, self.b, self.modo = [], None, None, "frac"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def definir(self, els, a, b=None, modo="frac"):
        self.els, self.a, self.b, self.modo = list(els), a, b, modo
        self.setFixedHeight(len(self.els) * (27 if b is not None else 21) + 4)
        self.update()

    def dominio(self):
        vals = list(self.a) + (list(self.b) if self.b is not None else [])
        vmax = max(vals) if vals else 1
        return escala_frac(vmax) if self.modo == "frac" else escala_raw(vmax)

    def paintEvent(self, _e):
        if self.a is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        comp = self.b is not None
        rh = 27 if comp else 21
        lab_w, val_w = 30, (58 if comp else 50)
        tw = self.width() - lab_w - val_w - 6
        dom = self.dominio()
        top = max(range(len(self.a)), key=lambda i: self.a[i])
        fm = tema.fonte_mono(8)
        p.setFont(fm)
        for i, el in enumerate(self.els):
            y = 2 + i * rh
            destaque = (i == top) and not comp
            p.setPen(QColor(tema.C["texto"] if destaque else tema.C["texto2"]))
            p.drawText(QRectF(0, y, lab_w, rh - 4), Qt.AlignmentFlag.AlignVCenter, el)
            if comp:
                barras = [(self.a[i], tema.C["selA"], y + 4), (self.b[i], tema.C["selB"], y + 13)]
                hb = 7
            else:
                barras = [(self.a[i], tema.C["acento"] if destaque else "#7d848c", y + 4)]
                hb = 11
            for v, cor, yy in barras:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(tema.C["painel3"]))
                p.drawRoundedRect(QRectF(lab_w, yy, tw, hb), 3, 3)
                w = max(0.0, min(1.0, float(v) / dom)) * tw
                if w > 0.5:
                    p.setBrush(QColor(cor))
                    p.drawRoundedRect(QRectF(lab_w, yy, w, hb), 3, 3)
            p.setPen(QColor(tema.C["texto"]))
            if comp:
                d = float(self.b[i]) - float(self.a[i])
                txt = (f"{d:+.3f}" if self.modo == "frac" else f"{d:+.0f}").replace(".", ",")
                cor = tema.C["texto2"] if abs(d) < (0.01 if self.modo == "frac" else 2) else \
                    (tema.C["selB"] if d > 0 else tema.C["selA"])
                p.setPen(QColor(cor))
            else:
                v = float(self.a[i])
                txt = (f"{v:.3f}" if self.modo == "frac" else f"{v:.0f}").replace(".", ",")
            p.drawText(QRectF(lab_w + tw + 4, y, val_w, rh - 4),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, txt)
        # grade
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        marcas = (0.25, 0.5) if self.modo == "frac" else (dom / 2,)
        for m in marcas:
            if m < dom:
                x = lab_w + tw * m / dom
                p.drawLine(QPointF(x, 2), QPointF(x, self.height() - 2))


def _pill(nome_obj):
    l = QLabel()
    l.setObjectName(nome_obj)
    return l


class _Stat(QFrame):
    def __init__(self, titulo):
        super().__init__()
        self.setObjectName("cartao")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 7)
        lay.setSpacing(0)
        self.k = QLabel(titulo)
        self.k.setObjectName("mudo")
        self.k.setStyleSheet("font-size: 8pt;")
        self.v = QLabel()
        self.v.setStyleSheet("font-size: 12pt; font-weight: 600;")
        lay.addWidget(self.k)
        lay.addWidget(self.v)

    def set(self, titulo, valor):
        self.k.setText(titulo)
        self.v.setText(valor)


class FichaGrao(QWidget):
    modoMudou = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.modo = "frac"
        self._ult = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 14, 16, 14)
        raiz.setSpacing(10)

        self.vazio = QLabel("Passe o mouse sobre um grão\nou clique para fixar.\n\n"
                            "⇧ clique compara dois grãos.")
        self.vazio.setObjectName("mudo")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vazio.setMinimumHeight(220)
        raiz.addWidget(self.vazio)

        self.corpo = QWidget()
        c = QVBoxLayout(self.corpo)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(9)
        cab = QHBoxLayout()
        cab.setSpacing(8)
        self.sw = QLabel()
        self.sw.setFixedSize(15, 15)
        self.nome = QLabel()
        self.nome.setObjectName("titulo")
        cab.addWidget(self.sw)
        cab.addWidget(self.nome)
        cab.addStretch()
        self.p_fix = _pill("pillAcento")
        self.p_fix.setText("fixado")
        cab.addWidget(self.p_fix)
        c.addLayout(cab)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.p_classe = _pill("pill")
        self.p_fino = _pill("pillAviso")
        self.p_fino.setText("fino < area_min")
        self.sub = QLabel()
        self.sub.setObjectName("texto2")
        pills.addWidget(self.p_classe)
        pills.addWidget(self.p_fino)
        pills.addWidget(self.sub)
        pills.addStretch()
        c.addLayout(pills)

        self.grade = QGridLayout()
        self.grade.setSpacing(6)
        self.stats = [_Stat("") for _ in range(4)]
        for i, s in enumerate(self.stats):
            self.grade.addWidget(s, i // 2, i % 2)
        c.addLayout(self.grade)

        linha = QFrame()
        linha.setObjectName("linha")
        c.addWidget(linha)

        hc = QHBoxLayout()
        self.t_comp = QLabel("COMPOSIÇÃO")
        self.t_comp.setObjectName("secao")
        hc.addWidget(self.t_comp)
        hc.addStretch()
        self.b_frac = QPushButton("fração")
        self.b_frac.setObjectName("segE")
        self.b_raw = QPushButton("bruta")
        self.b_raw.setObjectName("segD")
        for b in (self.b_frac, self.b_raw):
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hc.addWidget(b)
        hc.setSpacing(0)
        self.b_frac.setChecked(True)
        self.b_frac.clicked.connect(lambda: self.set_modo("frac"))
        self.b_raw.clicked.connect(lambda: self.set_modo("raw"))
        c.addLayout(hc)
        self.legenda_comp = QLabel()
        self.legenda_comp.setObjectName("mudo")
        self.legenda_comp.setStyleSheet("font-size: 8pt;")
        c.addWidget(self.legenda_comp)
        self.barras = BarrasComposicao()
        c.addWidget(self.barras)
        self.escala = QLabel()
        self.escala.setObjectName("mudo")
        self.escala.setStyleSheet("font-size: 8pt;")
        self.escala.setAlignment(Qt.AlignmentFlag.AlignRight)
        c.addWidget(self.escala)

        self.fsp = QFrame()
        self.fsp.setObjectName("cartao")
        fl = QVBoxLayout(self.fsp)
        fl.setContentsMargins(12, 10, 12, 10)
        t = QLabel("FELDSPATO — TERNÁRIO Na-K-Ca")
        t.setObjectName("secao")
        fl.addWidget(t)
        self.fsp_cls = QLabel()
        self.fsp_cls.setStyleSheet("font-size: 11pt; font-weight: 600;")
        fl.addWidget(self.fsp_cls)
        fb = QHBoxLayout()
        self.tern = TernarioFicha()
        fb.addWidget(self.tern)
        self.fsp_vals = QLabel()
        self.fsp_vals.setFont(tema.fonte_mono(9))
        fb.addWidget(self.fsp_vals)
        fb.addStretch()
        fl.addLayout(fb)
        c.addWidget(self.fsp)

        self.dica = QLabel("Clique fixa · ⇧ clique compara · Esc solta")
        self.dica.setObjectName("mudo")
        self.dica.setStyleSheet("font-size: 8pt;")
        c.addWidget(self.dica)
        raiz.addWidget(self.corpo)
        raiz.addStretch()
        self.corpo.hide()

    def set_modo(self, modo):
        self.modo = modo
        self.b_frac.setChecked(modo == "frac")
        self.b_raw.setChecked(modo == "raw")
        self.modoMudou.emit(modo)
        if self._ult:
            self.mostrar(*self._ult)

    # ---- dados ----
    @staticmethod
    def info(am, ob, sel):
        tipo, i = sel
        if tipo == "obj":
            mid = int(ob.mineral[i])
            m = am.mineral(mid)
            return dict(tipo="obj", id=i, nome=m.nome if m else f"id {mid}", cor=m.cor if m else "#888",
                        area=int(ob.area[i]), um2=float(ob.um2[i]), d=float(ob.diam[i]),
                        classe="matriz → argila" if ob.matriz[i] else CLASSES[int(ob.classe[i])],
                        sub=bool(ob.sub[i]),
                        frac=ob.frac[i], raw=ob.raw[i],
                        nk=ob.nk(i) if mid == am.id_feldspato else None)
        m = am.mineral(i)
        return dict(tipo="min", id=i, nome=m.nome if m else f"id {i}", cor=m.cor if m else "#888",
                    npx=int(ob.min_npx[i]), pct=float(ob.min_pct[i]),
                    frac=ob.min_frac[i], raw=ob.min_raw[i],
                    nk=ob.nk_mineral(i) if i == am.id_feldspato else None)

    def limpar(self):
        self._ult = None
        self.corpo.hide()
        self.vazio.show()

    def mostrar(self, am, ob, sel_a, sel_b=None, fixado=False):
        self._ult = (am, ob, sel_a, sel_b, fixado)
        if sel_a is None:
            self.corpo.hide()
            self.vazio.show()
            return
        self.vazio.hide()
        self.corpo.show()
        A = self.info(am, ob, sel_a)
        B = self.info(am, ob, sel_b) if sel_b is not None else None
        self.sw.setStyleSheet(f"background:{A['cor']}; border-radius:4px; border:1px solid rgba(0,0,0,0.4);")
        self.nome.setText(A["nome"].replace("_", " "))
        self.p_fix.setVisible(fixado)
        if A["tipo"] == "obj":
            self.p_classe.setText(A["classe"])
            self.p_classe.show()
            self.p_fino.setVisible(A["sub"])
            self.sub.setText(f"objeto #{A['id']}")
        else:
            self.p_classe.hide()
            self.p_fino.hide()
            self.sub.setText("pixel fino · média do mineral")

        if B is None:
            if A["tipo"] == "obj":
                vals = [("Área", f"{fmt(A['um2'], 3)} µm²"), ("Diâmetro eq.", f"{fmt(A['d'], 3)} µm"),
                        ("Pixels", fmt(A["area"])), ("Objeto", f"#{A['id']}")]
            else:
                vals = [("Escopo", "mineral inteiro"), ("Pixels (total)", fmt(A["npx"])),
                        ("% da amostra", f"{fmt(A['pct'], 2)} %"), ("", "")]
        else:
            def v(X, chave, d, suf=""):
                if X["tipo"] != "obj":
                    return "—"
                return f"{fmt(X[chave], d)}{suf}"
            vals = [("Área A → B (µm²)", f"{v(A, 'um2', 2)} → {v(B, 'um2', 2)}"),
                    ("Diâm. A → B (µm)", f"{v(A, 'd', 2)} → {v(B, 'd', 2)}"),
                    ("A", f"{A['nome'].replace('_', ' ')}" + (f" #{A['id']}" if A['tipo'] == 'obj' else "")),
                    ("B", f"{B['nome'].replace('_', ' ')}" + (f" #{B['id']}" if B['tipo'] == 'obj' else ""))]
        for s, (k, val) in zip(self.stats, vals):
            s.set(k, val)
            s.setVisible(bool(k))
        if B is not None:
            self.stats[2].v.setStyleSheet(f"font-size: 10pt; font-weight: 600; color: {tema.C['selA']};")
            self.stats[3].v.setStyleSheet(f"font-size: 10pt; font-weight: 600; color: {tema.C['selB']};")
            self.stats[0].v.setStyleSheet("font-size: 10pt; font-weight: 600;")
            self.stats[1].v.setStyleSheet("font-size: 10pt; font-weight: 600;")
        else:
            for s in self.stats:
                s.v.setStyleSheet("font-size: 12pt; font-weight: 600;")

        chave = "frac" if self.modo == "frac" else "raw"
        self.barras.definir(am.elementos, A[chave], B[chave] if B else None, self.modo)
        self.legenda_comp.setText(
            ("fração de cátions" if self.modo == "frac" else "intensidade bruta dos mapas (0–255)")
            + (" · barras amarela = A, azul = B, valor = B − A" if B else ""))
        dom = self.barras.dominio()
        self.escala.setText(f"escala 0 – {str(dom).replace('.', ',')}")

        pts = []
        for X, cor in ((A, tema.C["selA"] if B else tema.C["acento"]), (B, tema.C["selB"])):
            if X and X.get("nk"):
                pts.append((*X["nk"], cor))
        if pts:
            self.fsp.show()
            na, k, ca = pts[0][:3]
            self.fsp_cls.setText(classificar_feldspato(na, k, ca))
            self.fsp_vals.setText(f"Na  {na:.2f}\nK   {k:.2f}\nCa  {ca:.2f}".replace(".", ","))
            self.tern.definir(pts)
        else:
            self.fsp.hide()
