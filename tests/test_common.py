"""Funções de regra do pipeline (scripts/common.py): expressões, canais, frações e escala µm↔px."""
import numpy as np
import pytest

import common


def test_avaliar_expr_maior_menor_e_faixa():
    v = np.array([0.0, 0.1, 0.2, 0.3])
    assert common.avaliar_expr(v, ">0.15").tolist() == [False, False, True, True]
    assert common.avaliar_expr(v, "<0.15").tolist() == [True, True, False, False]
    assert common.avaliar_expr(v, "0.1 - 0.2").tolist() == [False, True, True, False]   # faixa inclusiva


def test_canal_elemento_soma_diferenca_razao():
    els = ["Si", "Al", "Mg"]
    frac = np.array([[[0.5, 0.25, 0.25], [0.0, 0.0, 1.0]]])
    assert np.allclose(common.canal(frac, els, "Si"), [[0.5, 0.0]])
    assert np.allclose(common.canal(frac, els, "Al+Mg"), [[0.5, 1.0]])
    assert np.allclose(common.canal(frac, els, "Si-Mg"), [[0.25, -1.0]])
    assert np.allclose(common.canal(frac, els, "Al/Si"), [[0.5, 0.0]])      # divisão por zero -> 0


def test_fracao_cations_normaliza_e_zera_fundo():
    stack = np.array([[[2.0, 2.0], [0.0, 0.0]]])
    frac, soma = common.fracao_cations(stack)
    assert np.allclose(frac[0, 0], [0.5, 0.5]) and np.allclose(frac[0, 1], [0, 0])
    assert soma.tolist() == [[4.0, 0.0]]


def test_mascara_mineral_e_logico():
    els = ["Si", "Al"]
    frac = np.array([[[0.9, 0.05], [0.9, 0.2], [0.1, 0.05]]])
    m = common.mascara_mineral(frac, els, {"Si": ">0.40", "Al": "<0.10"})
    assert m.tolist() == [[True, False, False]]


def test_resolver_escala_reproduz_calibracao_do_1_1():
    """Documentado na config: no 1.1 (0,1089 µm/px) os valores em µm dão exatamente os px antigos."""
    cfg = {"pixel_um": 0.108898, "d_min_um": 0.67,
           "minerais": [{"nome": "x", "suavizar_um": 1.63, "forma": {"close_um": 0.11, "d_min_um": 0.67}}]}
    r = common.resolver_escala(cfg)
    assert r["area_min"] == 30
    assert r["minerais"][0]["suavizar"] == 15
    assert r["minerais"][0]["forma"]["close"] == 1 and r["minerais"][0]["forma"]["area_min"] == 30
    assert "suavizar" not in cfg["minerais"][0]           # não altera a config original


def test_resolver_escala_piso_e_conflito():
    r = common.resolver_escala({"pixel_um": 10.0, "d_min_um": 0.67, "minerais": []})
    assert r["area_min"] == common.AREA_MIN_PX            # abaixo da resolução -> piso
    with pytest.raises(ValueError):
        common.resolver_escala({"pixel_um": 0.1, "d_min_um": 0.67, "area_min": 999, "minerais": []})
    with pytest.raises(ValueError):
        common.resolver_escala({"d_min_um": 0.67, "minerais": []})    # sem pixel_um


def test_para_um_ida_e_volta_exata():
    orig = {"nome": "q", "suavizar_um": 1.63, "forma": {"close_um": 0.33, "d_min_um": 2.748}}
    px = 0.108898
    editada = common.resolver_escala({"pixel_um": px, "minerais": [orig]})["minerais"][0]
    volta = common.para_um(editada, orig, px)
    assert volta["suavizar_um"] == 1.63 and volta["forma"] == {"close_um": 0.33, "d_min_um": 2.748}
    editada["suavizar"] = 20                               # mudou em px -> novo valor em µm
    assert common.para_um(editada, orig, px)["suavizar_um"] == round(20 * px, 3)
