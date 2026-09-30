"""Exemplo sintético (determinismo, leitura pelo pipeline e pelo app), troca de sítio e diagnóstico."""
import filecmp
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import yaml

import ativar_sitio
import common
import diagnostico
from conftest import REPO


def test_exemplo_deterministico(_exemplo_base, tmp_path):
    from mudmap_studio.nucleo import exemplo
    outro = exemplo.gerar_projeto(tmp_path / "de_novo", tamanho=256)
    for arq in sorted((_exemplo_base / "EDS" / "demo").glob("*.tif")):
        a, b = common._decodificar(arq)[0], common._decodificar(outro / "EDS" / "demo" / arq.name)[0]
        assert (a == b).all(), arq.name
    assert filecmp.cmp(_exemplo_base / "estado" / "rotulos.npy", outro / "estado" / "rotulos.npy", shallow=False)


def test_exemplo_lido_pelo_pipeline_e_pelo_app(exemplo, monkeypatch):
    monkeypatch.chdir(exemplo)
    cfg = common.carregar_config()
    assert cfg["pixel_um"] == 0.1 and cfg["area_min"] == 35          # pixel_um: auto (lido do TIFF)
    stack, overlay = common.carregar_mapas(cfg["pasta_dados"], cfg["elementos"])
    assert stack.shape == (256, 256, len(cfg["elementos"]))
    assert overlay[:5].all()                                          # faixa de título fora da amostra
    from mudmap_studio.nucleo import importar, objetos
    am = importar.importar_sitio(next(f for f in importar.listar_sitios(exemplo) if f.ativo))
    rot = np.load(exemplo / "estado" / "rotulos.npy")
    assert am.shape == (256, 256) and (am.rotulos == rot).all()
    assert objetos.calcular(am).n > 0


def test_pacote_mudmap_ida_e_volta(exemplo, tmp_path):
    from mudmap_studio.nucleo import importar, pacote
    am = importar.importar_sitio(next(f for f in importar.listar_sitios(exemplo) if f.ativo))
    arq = pacote.salvar(am, tmp_path / "x.mudmap")
    am.rotulos[:4, :4] = 1
    pacote.salvar(am, arq)
    b = pacote.abrir(arq)
    assert (b.rotulos == am.rotulos).all() and len(b.versoes) == 1
    assert all((x == y).all() for x, y in zip(b.mapas, am.mapas)) and (b.mascara == am.mascara).all()


def test_ativar_sitio_ida_e_volta(exemplo, monkeypatch):
    monkeypatch.chdir(exemplo)
    # um 2º sítio arquivado: mesma pasta de dados, rótulos vazios
    d = exemplo / "sitios" / "demo2"
    (d / "estado").mkdir(parents=True)
    cfg = yaml.safe_load((exemplo / "config" / "classificacao.yaml").read_text(encoding="utf-8"))
    texto = (exemplo / "config" / "classificacao.yaml").read_text(encoding="utf-8").replace(
        'sitio: "demo"', 'sitio: "demo2"')
    (d / "classificacao_demo2.yaml").write_text(texto, encoding="utf-8")
    (d / "info.json").write_text(json.dumps({"sitio": "demo2", "pasta_dados": cfg["pasta_dados"]}), encoding="utf-8")
    np.save(d / "estado" / "rotulos.npy", np.zeros((256, 256), np.int16))
    rot_demo = np.load("estado/rotulos.npy")
    monkeypatch.setattr(sys, "argv", ["ativar_sitio.py", "demo2"])
    ativar_sitio.main()
    assert yaml.safe_load(open("config/classificacao.yaml", encoding="utf-8"))["sitio"] == "demo2"
    assert not np.load("estado/rotulos.npy").any()
    assert (np.load("sitios/demo/estado/rotulos.npy") == rot_demo).all()      # o ativo foi guardado
    monkeypatch.setattr(sys, "argv", ["ativar_sitio.py", "demo"])
    ativar_sitio.main()
    assert (np.load("estado/rotulos.npy") == rot_demo).all()
    assert [s for s, *_ in ativar_sitio.sitios()] == ["demo", "demo2"]


def _diag(pasta):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "diagnostico.py"), "--projeto", str(pasta)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_diagnostico_ok_no_exemplo(exemplo):
    r = _diag(exemplo)
    assert "RESUMO: 0 erro(s)" in r.stdout, r.stdout
    assert "reconhecer.py" in r.stdout                                  # sem clusters -> próximo passo
    assert r.returncode == 0


def test_diagnostico_acusa_mapa_e_regra_quebrados(exemplo):
    cfg_p = exemplo / "config" / "classificacao.yaml"
    txt = cfg_p.read_text(encoding="utf-8").replace("condicoes: { Ti: \">0.18\" }", "condicoes: { Zr: \">0.18\" }")
    cfg_p.write_text(txt, encoding="utf-8")
    os.remove(exemplo / "EDS" / "demo" / "S Wt%.tif")
    r = _diag(exemplo)
    assert r.returncode == 1
    assert "sem mapa para ['S']" in r.stdout and "'Zr'" in r.stdout, r.stdout


def test_validar_config_pega_erros_de_forma():
    cfg = {"amostra": "a", "sitio": "1", "pasta_dados": "x", "elementos": ["Si", "Al"],
           "minerais": [{"nome": "m", "cor": "verde", "fonte_default": "olho", "condicoes": {"Si": "muito"},
                         "mapas_grupos": [{"nome": "g", "cond": [{"canal": "Si", "op": "=", "q": 2}]}]},
                        {"nome": "m", "condicoes": {"Si": ">0.1"}}]}
    erros, avisos = diagnostico.validar_config(cfg)
    texto = " | ".join(erros)
    for trecho in ("repetido", "fonte_default", "inválida", "op '='", "fora de [0, 1]"):
        assert trecho in texto, (trecho, erros)
    assert any("cor" in a for a in avisos)


def test_gerar_exemplo_cli(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "gerar_exemplo.py"), "--destino",
                        str(tmp_path / "ex"), "--tamanho", "128", "--sem-rotulos"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "ex" / "config" / "classificacao.yaml").exists()
    assert not (tmp_path / "ex" / "estado").exists()
    shutil.rmtree(tmp_path / "ex")
