"""Controlador do modo Edição: liga canvas (ferramentas) + painel + Editor (núcleo).

Edições locais (pincel, formas, balde…) remendam só a região alterada na imagem exibida
(compor_regiao + canvas.atualizar_regiao) -> resposta imediata mesmo em 4096². Operações
globais (morfologia, propagar, limpeza) pedem a recomposição inteira em segundo plano.
"""
import numpy as np
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..nucleo.edicao import Editor, capsula, rasterizar
from .canvas import FERR_TRACO
from .comum import fmt
from .comum import sobreposicao as _sobreposicao


class ControleEdicao(QObject):
    def __init__(self, janela):
        super().__init__(janela)
        self.j = janela
        self.c = janela.canvas
        self.p = janela.painel_ed
        self.editor = None
        self.proposta = None
        self._ctx = None
        self._ult = None
        self._val = self._alvo = None
        c, p = self.c, self.p
        c.tracoInicio.connect(self._traco_inicio)
        c.tracoPonto.connect(self._traco_ponto)
        c.tracoFim.connect(self._traco_fim)
        c.cliqueFerramenta.connect(self._clique_ferramenta)
        c.formaConcluida.connect(self._forma)
        c.pontosMudaram.connect(p.set_n_pontos)
        p.ativoMudou.connect(self._ativo)
        p.raioMudou.connect(lambda r: setattr(c, "raio_pincel", r))
        p.protecoesMudaram.connect(self._protecoes)
        p.pedido.connect(self._pedido)

    # ---------- estado ----------
    @property
    def ativo_modo(self):
        """Edição permitida: modo Edição, amostra carregada e nenhuma tarefa em segundo plano."""
        return self.j.modo == "edicao" and self.editor is not None and not self.j._ocupado

    def definir(self, am):
        self.editor = Editor(am)
        self.proposta = None
        self.c.set_camada("prop", None)
        self.c.limpar_pontos()
        self.p.definir(am)
        self._protecoes()
        self._ativo(self.p.ativo())
        self.p.atualizar_historico(self.editor.hist)
        self.p.set_msg("")

    def sair(self):
        """Ao voltar para o Inspetor: cancela forma em curso e descarta proposta pendente."""
        self.c.cancelar_forma()
        if self.proposta:
            self.descartar()

    def _protecoes(self):
        if self.editor:
            self.editor.nao_invadir = self.p.chk_invadir.isChecked()
            self.editor.so_amostra = self.p.chk_amostra.isChecked()

    def _ativo(self, mid):
        self.c.cor_ferramenta = QColor(self.p.cor_ativo())
        self.j.mostrar_ativo(mid)
        self.c.update()

    def nome(self, mid):
        return self.editor.nome(mid) if self.editor else str(mid)

    # ---------- desenho ----------
    def _remendar(self, caixa, margem=3):
        if caixa is None:
            return
        am = self.j.am
        H, W = am.shape
        x0, y0, x1, y1 = caixa
        self.j.render.invalidar()
        if (x1 - x0) * (y1 - y0) > 0.25 * H * W:
            self.j.recompor()
            return
        v = self.j._visual_atual()
        ctx = self._ctx if self._ctx is not None else self.j.comp._preparar(v)
        rgb, (ox, oy) = self.j.comp.compor_regiao(v, x0 - margem, y0 - margem, x1 + margem, y1 + margem, ctx)
        self.c.atualizar_regiao(ox, oy, rgb)
        if self.c.fator_base > 1:
            self.j.recompor()

    def _apos(self, passo, total=False, extra=""):
        self.p.atualizar_historico(self.editor.hist)
        if passo is None:
            self.p.set_msg("Nada mudou — confira as proteções, o alvo ou o filtro." + extra, "aviso")
            return
        self.j.marcar_sujo(True)
        self.p.set_msg(f"{passo.desc} · {fmt(passo.px)} px{extra}", "ok")
        if total:
            self.j.render.invalidar()
            self.j.recompor()
        else:
            self._remendar(passo.caixa())

    # ---------- pincel / borracha ----------
    def _traco_inicio(self, x, y, _mods):
        if not self.ativo_modo:
            return
        a = self.p.ativo()
        r = int(self.c.raio_pincel)
        if self.c.ferramenta == "pincel":
            self._val, self._alvo = a, None
            desc = f"pincel {self.nome(a)} (r={r})"
        else:
            self._val = 0
            self._alvo = a if self.p.chk_borr.isChecked() else -1
            desc = f"borracha {self.nome(a) if self._alvo != -1 else '(todos)'} (r={r})"
        self.editor.iniciar(desc)
        self._ctx = self.j.comp._preparar(self.j._visual_atual())
        self._ult = (x, y)
        self._segmento(self._ult, self._ult)

    def _segmento(self, a, b):
        m, y0, x0 = capsula(a, b, self.c.raio_pincel, self.j.am.shape)
        if m is None:
            return
        if self.editor.aplicar(m, y0, x0, self._val, alvo=self._alvo, fora_ok=self._val == 0):
            self._remendar((x0, y0, x0 + m.shape[1], y0 + m.shape[0]))

    def _traco_ponto(self, x, y):
        if self.editor is None or self.editor._grupo is None:
            return
        self._segmento(self._ult, (x, y))
        self._ult = (x, y)

    def _traco_fim(self):
        if self.editor is None or self.editor._grupo is None:
            return
        passo = self.editor.terminar()
        self._ctx = None
        self.p.atualizar_historico(self.editor.hist)
        if passo:
            self.j.marcar_sujo(True)
            self.p.set_msg(f"{passo.desc} · {fmt(passo.px)} px", "ok")
        else:
            self.p.set_msg("Nada mudou — confira as proteções (não invadir / só dentro da amostra) "
                           "ou o mineral ativo.", "aviso")

    # ---------- cliques ----------
    def pegar(self, x, y):
        mid = int(self.j.am.rotulos[y, x])
        if mid:
            self.p.set_ativo(mid)
            self.p.set_msg(f"Mineral ativo: {self.nome(mid)}", "info")
        else:
            self.p.set_msg("Sem mineral neste pixel.", "aviso")

    def _clique_ferramenta(self, x, y, mods):
        if not self.ativo_modo or x < 0:
            return
        if self.proposta and self.alternar_proposta(x, y):
            return
        f = self.c.ferramenta
        if f == "contagotas" or (f in FERR_TRACO and mods & Qt.KeyboardModifier.AltModifier):
            self.pegar(x, y)
        elif f == "balde":
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._apos(self.editor.balde(x, y, self.p.ativo()))
            finally:
                QApplication.restoreOverrideCursor()
        elif f == "remover":
            self._apos(self.editor.remover_grao(x, y))

    def clique_mao(self, x, y):
        """Clique com a ferramenta Mover no modo edição: alterna regiões da proposta."""
        if self.proposta and x >= 0:
            self.alternar_proposta(x, y)

    # ---------- formas / pontos ----------
    def _forma(self, tipo, pts):
        if not self.ativo_modo:
            return
        if self.proposta:                      # revisão: a forma EXCLUI em bloco as propostas tocadas
            self._excluir_na_forma(tipo, pts)
            return
        try:
            passo = self.editor.forma(tipo, pts, self.p.acao_forma(), self.p.ativo(), self.p.origem(),
                                      self.p.filtro(), self.p.chk_livres.isChecked())
        except ValueError as e:
            self.p.set_msg(str(e), "erro")
            return
        self._apos(passo)

    def converter_pontos(self):
        if not self.ativo_modo:
            return
        pts = list(self.c.pontos)
        if not pts:
            self.p.set_msg("Marque pontos com a ferramenta Pontos (N) ao redor de cada grão.", "aviso")
            return
        modo, eps, raio = self.p.params_pontos()
        passo, n, ign = self.editor.pontos(pts, self.p.ativo(), eps, modo, raio)
        self.c.limpar_pontos()
        extra = f" · {ign} ponto(s) soltos ignorados (grupo < 3)" if ign else ""
        self._apos(passo, extra=extra)

    # ---------- propagar (com revisão) ----------
    def propagar(self):
        if not self.ativo_modo:
            return
        a = self.p.ativo()
        prm = self.p.params_propagar()
        ed = self.editor
        self.j._rodar(f"Propagando {self.nome(a)}", lambda prog: ed.propagar(a, progresso=prog, **prm),
                      lambda r: self._proposta_pronta(r, a))

    def _proposta_pronta(self, r, ativo):
        lab, n, info = r
        if n == 0:
            self.p.set_msg("Nenhuma região nova com a mesma assinatura e tamanho compatível "
                           "(tente aumentar a tolerância ou baixar o portão).", "aviso")
            return
        ids = np.unique(lab[lab > 0])
        self.proposta = {"lab": lab, "incl": set(int(i) for i in ids), "ativo": ativo, "n": n}
        self._desenhar_proposta()
        self.p.set_msg(f"Assinatura aprendida (limiar {info['lim']:.2f}, portão em "
                       f"{', '.join(info['mapas'])}, tamanhos {info['amin']}–{info['amax']} px).", "info")

    def _desenhar_proposta(self):
        pr = self.proposta
        lab = pr["lab"]
        incl = np.isin(lab, list(pr["incl"]))
        excl = (lab > 0) & ~incl
        s = _sobreposicao(incl, excl)
        self.c.set_camada("prop", *(s if s else (None,)))
        k = len(pr["incl"])
        self.p.set_prop(f"{k} de {pr['n']} regiões propostas para {self.nome(pr['ativo'])} (ciano). "
                        "Clique numa região para excluí-la (vermelho) ou incluí-la de volta; "
                        "retângulo/elipse/polígono/laço em volta das falsas exclui em bloco. "
                        "Depois Aceitar.")

    def _excluir_na_forma(self, tipo, pts):
        m, y0, x0 = rasterizar(tipo, pts, self.j.am.shape)
        if m is None:
            return
        janela = self.proposta["lab"][y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
        tocadas = set(int(k) for k in np.unique(janela[m]) if k) & self.proposta["incl"]
        self.proposta["incl"] -= tocadas
        self._desenhar_proposta()
        self.p.set_msg(f"{len(tocadas)} região(ões) excluída(s) da proposta.", "info")

    def todas_propostas(self, incluir):
        if not self.proposta:
            return
        lab = self.proposta["lab"]
        self.proposta["incl"] = set(int(k) for k in np.unique(lab[lab > 0])) if incluir else set()
        self._desenhar_proposta()

    def alternar_proposta(self, x, y):
        k = int(self.proposta["lab"][y, x])
        if not k:
            return False
        incl = self.proposta["incl"]
        incl.symmetric_difference_update({k})
        self._desenhar_proposta()
        return True

    def aceitar(self):
        pr = self.proposta
        if not pr:
            return
        mask = np.isin(pr["lab"], list(pr["incl"]))
        passo = self.editor.aceitar_propagacao(mask, pr["ativo"], len(pr["incl"]))
        self.descartar()
        self._apos(passo, total=True)

    def descartar(self):
        self.proposta = None
        self.c.set_camada("prop", None)
        self.p.set_prop(None)

    # ---------- morfologia / limpeza ----------
    def morf(self, op, param):
        """Em segundo plano (pode levar segundos em 4096² ou com muitos objetos); a edição fica
        travada até terminar (j._ocupado)."""
        a, ed = self.p.ativo(), self.editor
        self.j._rodar(f"Morfologia ({op}) em {self.nome(a)}",
                      lambda _prog: ed.morfologia(a, op, param),
                      lambda passo: self._apos(passo, total=True))

    def limpar_fora(self):
        f, cont = self.editor.fora_da_amostra()
        if not cont:
            self.p.set_msg("Nenhum pixel rotulado fora da amostra.", "ok")
            return
        s = _sobreposicao(f, cor=(229, 83, 75))
        if s:
            self.c.set_camada("fora", *s)
        linhas = "\n".join(f"   • {self.nome(i)}: {fmt(n)} px" for i, n in sorted(cont.items(), key=lambda t: -t[1]))
        r = QMessageBox.question(
            self.j, "Remover rótulos fora da amostra",
            f"{fmt(sum(cont.values()))} px rotulados estão FORA da máscara da amostra (resina) — "
            f"destacados em vermelho:\n\n{linhas}\n\nRemover esses rótulos? (Ctrl+Z desfaz)")
        self.c.set_camada("fora", None)
        if r == QMessageBox.StandardButton.Yes:
            self._apos(self.editor.limpar_fora(), total=True)

    # ---------- histórico ----------
    def _pode_historico(self):
        return self.editor is not None and not self.j._ocupado and self.j.modo in ("edicao", "segmentar")

    def desfazer(self):
        if self._pode_historico():
            self._historico(self.editor.desfazer(), "Desfeito")

    def refazer(self):
        if self._pode_historico():
            self._historico(self.editor.refazer(), "Refeito")

    def _historico(self, passo, verbo):
        self.p.atualizar_historico(self.editor.hist)
        if passo is None:
            self.p.set_msg(f"Nada para {'desfazer' if verbo == 'Desfeito' else 'refazer'}.", "info")
            return
        self.j.marcar_sujo(True)
        self.p.set_msg(f"{verbo}: {passo.desc}", "info")
        self._remendar(passo.caixa())
        if self.j.modo == "segmentar":
            self.j.painel_seg.set_msg(f"{verbo}: {passo.desc}", "info")
            self.j.seg.gerar()

    # ---------- pedidos do painel ----------
    def _pedido(self, acao, arg):
        if self.editor is None or self.j._ocupado:
            return
        {"pontos": self.converter_pontos, "limpar_pontos": self.c.limpar_pontos,
         "propagar": self.propagar, "aceitar_prop": self.aceitar, "descartar_prop": self.descartar,
         "prop_todas": lambda: self.todas_propostas(bool(arg)),
         "morf": lambda: self.morf(*arg), "limpar_fora": self.limpar_fora,
         "desfazer": self.desfazer, "refazer": self.refazer,
         "salvar": self.j.salvar, "exportar": self.j.exportar_estado}[acao]()
