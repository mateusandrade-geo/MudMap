"""Integridade dos dados reais do repositório (amostra RJS0649RJ): ids dos minerais, regras × elementos e
pacotes .mudmap = estado. Pulados se os dados não estiverem presentes."""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml

import diagnostico
from conftest import REPO, precisa_dados

# "Decisões duráveis" do /S_MudMap: o id gravado em rotulos.npy = posição do mineral na config
IDS = ["quartzo", "sulfato_ca", "pirita", "titanita", "oxido_ti", "oxido_fe", "anquerita", "carbonato_ca",
       "biotita", "ilita", "esmectita", "feldspato", "clorita"]


def _configs():
    return [REPO / "config" / "classificacao.yaml", *sorted(REPO.glob("sitios/*/classificacao_*.yaml")),
            REPO / "app" / "mudmap_studio" / "recursos" / "exemplo_classificacao.yaml"]


@pytest.mark.parametrize("arq", _configs(), ids=lambda p: str(p.relative_to(REPO)))
def test_configs_ids_e_regras(arq):
    cfg = yaml.safe_load(arq.read_text(encoding="utf-8"))
    assert [m["nome"] for m in cfg["minerais"]][:len(IDS)] == IDS, "minerais reordenados/removidos"
    erros, _avisos = diagnostico.validar_config(cfg)
    assert not erros, erros


@precisa_dados
def test_pacotes_iguais_ao_estado():
    cfg = yaml.safe_load((REPO / "config" / "classificacao.yaml").read_text(encoding="utf-8"))
    pacotes = sorted((REPO / "saida" / "mudmap").glob("*.mudmap"))
    assert pacotes, "nenhum pacote em saida/mudmap/"
    for arq in pacotes:
        with zipfile.ZipFile(arq) as z:
            man = json.loads(z.read("manifest.json"))
            rot = np.load(io.BytesIO(z.read("rotulos.npy")))
            cfg_pacote = z.read("config.yaml").decode("utf-8")
        s = str(man["sitio"])
        if s == str(cfg["sitio"]):
            est, cfg_arq = REPO / "estado", REPO / "config" / "classificacao.yaml"
        else:
            est, cfg_arq = REPO / "sitios" / s / "estado", REPO / "sitios" / s / f"classificacao_{s}.yaml"
        assert (np.load(est / "rotulos.npy") == rot).all(), f"{arq.name}: rótulos ≠ {est}"
        assert cfg_arq.read_text(encoding="utf-8") == cfg_pacote, f"{arq.name}: config ≠ {cfg_arq}"


@precisa_dados
def test_relatorios_finais_versionados():
    for s in ("1.1", "1.2"):
        d = json.loads((REPO / "saida" / f"relatorio_final_{s}.json").read_text(encoding="utf-8"))
        assert d["n_graos"] > 0 and abs(sum(d["fracoes_area"].values()) - 100) < 0.2
