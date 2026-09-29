"""Composição da imagem numa thread de fundo: progressiva e cancelável.

Cada pedido: (1) em imagens grandes (>1600 px) sai primeiro uma PRÉVIA subamostrada
(~0,1–0,2 s em 4096²), suficiente para a vista ajustada à janela; (2) depois a resolução
cheia. Um pedido novo cancela o anterior entre blocos de linhas (fila de UM pendente):
arrastar contraste/opacidade fica fluido e a interface nunca trava.
"""
import math
import traceback

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .canvas import construir_niveis

LIMIAR_PREVIA = 1600      # px (lado maior) a partir do qual há prévia
LADO_PREVIA = 1400


class _Trabalhador(QObject):
    pronto = pyqtSignal(int, object, object)     # geração, níveis, info
    falhou = pyqtSignal(int, str)
    terminou = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.comp = None
        self.ultima = 0          # geração mais nova pedida (escrita pela thread da interface)

    def _cancelado(self, g):
        return g < self.ultima

    @pyqtSlot(int, object)
    def trabalhar(self, g, visual):
        comp = self.comp
        try:
            H, W = comp.am.shape
            if max(H, W) > LIMIAR_PREVIA:
                p = math.ceil(max(H, W) / LADO_PREVIA)
                rgb, info = comp.compor(visual, passo=p)
                info.update(visual=visual, previa=True)
                self.pronto.emit(g, construir_niveis(rgb, p), info)
                if self._cancelado(g):
                    return
            rgb, info = comp.compor(visual, cancelar=lambda: self._cancelado(g))
            if rgb is None:
                return
            info.update(visual=visual, previa=False)
            self.pronto.emit(g, construir_niveis(rgb), info)
        except ValueError as e:                  # erro "de usuário" (ex.: expressão inválida)
            self.falhou.emit(g, str(e))
        except Exception:  # noqa: BLE001
            self.falhou.emit(g, traceback.format_exc())
        finally:
            self.terminou.emit(g)


class Renderizacao(QObject):
    resultado = pyqtSignal(object, object)   # níveis, info
    erro = pyqtSignal(str, object)           # mensagem, visual
    ocupado = pyqtSignal(bool)
    _pedir = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.th = QThread()
        self.tb = _Trabalhador()
        self.tb.moveToThread(self.th)
        self._pedir.connect(self.tb.trabalhar)
        self.tb.pronto.connect(self._pronto)
        self.tb.falhou.connect(self._falhou)
        self.tb.terminou.connect(self._terminou)
        self.th.start()
        self._gen = 0
        self._em_curso = False
        self._pendente = None
        self._visuais = {}

    @property
    def ativo(self):
        return self._em_curso or self._pendente is not None

    def definir(self, comp):
        self.tb.comp = comp
        self._gen += 1
        self.tb.ultima = self._gen
        self._pendente = None

    def invalidar(self):
        """Uma edição local mudou os rótulos: descarta o que estiver em curso ou pendente."""
        self._gen += 1
        self.tb.ultima = self._gen
        self._pendente = None

    def solicitar(self, visual):
        if self.tb.comp is None:
            return
        self._gen += 1
        self.tb.ultima = self._gen
        self._visuais = {self._gen: visual}
        if self._em_curso:
            self._pendente = (self._gen, visual)
        else:
            self._enviar(self._gen, visual)

    def _enviar(self, g, visual):
        self._em_curso = True
        self.ocupado.emit(True)
        self._pedir.emit(g, visual)

    def _terminou(self, _g):
        self._em_curso = False
        if self._pendente is not None:
            g, v = self._pendente
            self._pendente = None
            self._enviar(g, v)
        else:
            self.ocupado.emit(False)

    def _pronto(self, g, niveis, info):
        if g == self._gen:
            self.resultado.emit(niveis, info)

    def _falhou(self, g, msg):
        if g == self._gen:
            self.erro.emit(msg, self._visuais.get(g))

    def parar(self):
        self.tb.ultima = 1 << 60                 # cancela o que estiver em curso
        self.th.quit()
        self.th.wait(5000)
