"""Diálogo de escolha do sítio ao importar e o Servico (tarefas em segundo plano)."""
import traceback

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
                             QVBoxLayout)


class DialogoSitios(QDialog):
    def __init__(self, fontes, raiz, preferido=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar sítio do projeto")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        t = QLabel("Escolha o sítio")
        t.setObjectName("titulo")
        lay.addWidget(t)
        s = QLabel(f"Projeto: {raiz}")
        s.setObjectName("mudo")
        s.setWordWrap(True)
        lay.addWidget(s)
        self.lista = QListWidget()
        for f in fontes:
            rot = "com rótulos" if f.tem_rotulos else "sem rótulos (só mapas)"
            it = QListWidgetItem(f"Sítio {f.sitio}   ·   {f.rotulo}\n{f.pasta_dados}   ·   {rot}")
            it.setData(256, f)
            self.lista.addItem(it)
            if preferido and f.sitio == preferido and self.lista.currentRow() < 0:
                self.lista.setCurrentItem(it)
        if self.lista.currentRow() < 0 and self.lista.count():
            self.lista.setCurrentRow(0)
        self.lista.itemDoubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.lista)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Importar")
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primario")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def escolhida(self):
        it = self.lista.currentItem()
        return it.data(256) if it else None


class _Executor(QObject):
    pronto = pyqtSignal(int, object)
    falhou = pyqtSignal(int, str, str)          # nº, mensagem curta, traceback ("" = erro de usuário)
    progresso = pyqtSignal(int, float, str)

    @pyqtSlot(int, object)
    def rodar(self, n, fn):
        try:
            self.pronto.emit(n, fn(lambda f, m: self.progresso.emit(n, float(f), str(m))))
        except ValueError as e:                  # mensagem pensada para o usuário
            self.falhou.emit(n, str(e), "")
        except Exception as e:  # noqa: BLE001 — mostrado ao usuário com os detalhes
            self.falhou.emit(n, str(e) or type(e).__name__, traceback.format_exc())


class Servico(QObject):
    """Thread de fundo PERSISTENTE que executa uma tarefa por vez; os retornos chegam na thread
    da interface. pedir(fn(progresso), pronto(res), erro(curta, detalhe), progresso(f, msg)).
    coalescer=True descarta os pedidos pendentes (cálculo ao vivo: só o mais novo interessa)."""
    _rodar = pyqtSignal(int, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.th = QThread()
        self.ex = _Executor()
        self.ex.moveToThread(self.th)
        self._rodar.connect(self.ex.rodar)
        self.ex.pronto.connect(lambda n, r: self._fim(n, 0, r))
        self.ex.falhou.connect(lambda n, c, d: self._fim(n, 1, c, d))
        self.ex.progresso.connect(lambda n, f, m: (self._cb.get(n, (None,) * 3)[2] or (lambda *_: None))(f, m))
        self.th.start()
        self._n, self._atual, self._fila, self._cb = 0, None, [], {}

    @property
    def ocupado(self):
        return self._atual is not None or bool(self._fila)

    def pedir(self, fn, pronto, erro=None, progresso=None, coalescer=False):
        if coalescer:
            for n, _fn in self._fila:
                self._cb.pop(n, None)
            self._fila = []
        self._n += 1
        self._cb[self._n] = (pronto, erro, progresso)
        self._fila.append((self._n, fn))
        self._proximo()
        return self._n

    def _proximo(self):
        if self._atual is None and self._fila:
            self._atual, fn = self._fila.pop(0)
            self._rodar.emit(self._atual, fn)

    def _fim(self, n, k, *args):
        self._atual = None
        cb = self._cb.pop(n, (None,) * 3)[k]
        if cb is not None:
            cb(*args)
        self._proximo()

    def parar(self):
        self._fila = []
        self.th.quit()
        self.th.wait(5000)
