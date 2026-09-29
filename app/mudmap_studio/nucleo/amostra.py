"""Amostra (um sítio) em memória.

Os mapas ficam em uint8, UM array HxW por elemento — nunca uma pilha float HxWxN: em
4096² ela passaria de 1 GB. A fração de cátions é calculada canal a canal, sob demanda;
as funções do pipeline recebem uma Vista (pilha virtual indexada por [..., i]).
"""
from dataclasses import dataclass
from functools import cached_property

import numpy as np


class Vista:
    """Imita a pilha H×W×N do pipeline (stack / frac) chamando fn(i) canal a canal."""

    def __init__(self, fn, shape=None):
        self.fn, self.shape = fn, shape

    def __getitem__(self, chave):
        return self.fn(chave[-1])


def elementos_da_expr(expr):
    """'Si-Mg' -> ['Si', 'Mg'] (um elemento, A-B, A/B ou A+B+C)."""
    for s in "+-/":
        expr = expr.replace(s, " ")
    return [t for t in expr.split() if t]


@dataclass(frozen=True)
class Mineral:
    id: int          # = posição no config (1..N), igual ao valor gravado em rotulos
    nome: str
    cor: str         # "#rrggbb"


class Amostra:
    def __init__(self, *, amostra, sitio, pixel_um, elementos, minerais, area_min,
                 mapas, bse, mascara, rotulos, config_yaml=None, origem=None,
                 caminho=None, clusters=None, clusters_info=None):
        self.amostra = str(amostra)
        self.sitio = str(sitio)
        self.pixel_um = float(pixel_um)
        self.elementos = list(elementos)
        self.minerais = list(minerais)
        self.area_min = int(area_min)
        self.mapas = [np.ascontiguousarray(m, dtype=np.uint8) for m in mapas]
        self.bse = None if bse is None else np.ascontiguousarray(bse, dtype=np.uint8)
        self.mascara = np.ascontiguousarray(mascara, dtype=bool)
        self.rotulos = np.ascontiguousarray(rotulos)
        self.config_yaml = config_yaml
        self.origem = dict(origem or {})
        self.caminho = caminho
        # k-means do reconhecer.py (id 1..k por pixel; 0 = fora) + {"nomes": {id: nome}, ...}
        self.clusters = None
        if clusters is not None and clusters.shape == self.mapas[0].shape:
            self.clusters = np.ascontiguousarray(clusters.astype(np.uint8 if clusters.max() < 256 else np.uint16))
        self.clusters_info = clusters_info if self.clusters is not None else None
        self.log_edicoes = []     # proveniência: [{quando, o_que, px}] (gravado no manifest)
        self.versoes = []         # versões anteriores dos rótulos guardadas no .mudmap
        if len(self.mapas) != len(self.elementos):
            raise ValueError("número de mapas diferente do número de elementos")
        for arr, nome in [(self.mascara, "máscara"), (self.rotulos, "rótulos")] + \
                [(m, f"mapa {e}") for m, e in zip(self.mapas, self.elementos)]:
            if arr.shape != self.shape:
                raise ValueError(f"{nome} com dimensões {arr.shape}, esperado {self.shape}")
        if self.bse is not None and self.bse.shape != self.shape:
            raise ValueError(f"BSE com dimensões {self.bse.shape}, esperado {self.shape}")

    # ---- geometria ----
    @property
    def shape(self):
        return self.mapas[0].shape

    @property
    def fov_um(self):
        h, w = self.shape
        return (w * self.pixel_um, h * self.pixel_um)

    @property
    def titulo(self):
        return f"{self.amostra} · sítio {self.sitio}"

    # ---- química ----
    @cached_property
    def soma(self):
        """Soma de cátions por pixel (uint16: até 255 x nº de elementos)."""
        s = np.zeros(self.shape, np.uint16)
        for m in self.mapas:
            s += m
        return s

    @cached_property
    def inv_soma(self):
        inv = np.zeros(self.shape, np.float32)
        np.divide(1.0, self.soma, out=inv, where=self.soma > 0)
        return inv

    def indice(self, el):
        return self.elementos.index(el)

    def frac(self, i):
        """Fração de cátions do elemento i (float32 HxW)."""
        return self.mapas[i] * self.inv_soma

    def vista(self, tipo="frac", exata=False):
        """Pilha virtual 'frac' (fração de cátions) ou 'raw' (intensidade). exata=True = float64
        como o pipeline (regras, calibração, k-means); senão float32 (desenho, mais leve)."""
        forma = (*self.shape, len(self.elementos))
        if tipo == "raw":
            dt = np.float64 if exata else np.float32
            return Vista(lambda i: self.mapas[i].astype(dt), forma)
        if not exata:
            return Vista(self.frac, forma)
        soma = self.soma.astype(np.float64)

        def frac64(i):
            m = self.mapas[i].astype(np.float64)
            return np.divide(m, soma, out=np.zeros_like(m), where=soma > 0)
        return Vista(frac64, forma)

    def raw_pixel(self, y, x):
        return np.array([m[y, x] for m in self.mapas], np.float32)

    def frac_pixel(self, y, x):
        r = self.raw_pixel(y, x)
        s = r.sum()
        return r / s if s > 0 else np.zeros_like(r)

    # ---- minerais ----
    @cached_property
    def _por_id(self):
        return {m.id: m for m in self.minerais}

    def mineral(self, mid):
        return self._por_id.get(int(mid))

    @property
    def max_id(self):
        return max((m.id for m in self.minerais), default=0)

    @cached_property
    def config(self):
        """Config de classificação (snapshot do .mudmap) já interpretada, com os parâmetros
        em µm convertidos para px pelo pixel desta amostra; {} se ausente."""
        if not self.config_yaml:
            return {}
        import yaml
        from .pipeline import common
        return common.resolver_escala(yaml.safe_load(self.config_yaml) or {}, self.pixel_um)

    def regra(self, mid):
        """Dict do mineral na config (id = posição+1) ou {}."""
        ms = self.config.get("minerais", [])
        return ms[mid - 1] if 0 < mid <= len(ms) else {}

    @property
    def tem_na(self):
        return "Na" in self.elementos

    @property
    def id_feldspato(self):
        """Como o relatorio_final.py: 1º mineral com `feldspato: true` na config ou chamado feldspato."""
        return next((m.id for m in self.minerais
                     if self.regra(m.id).get("feldspato") or m.nome == "feldspato"), None)
