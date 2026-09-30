"""Fixtures comuns: caminhos do repositório e um projeto de EXEMPLO sintético pequeno (gerado uma vez)."""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "app"), str(REPO / "scripts")]


@pytest.fixture(scope="session")
def repo():
    return REPO


@pytest.fixture(scope="session")
def _exemplo_base(tmp_path_factory):
    from mudmap_studio.nucleo import exemplo
    return exemplo.gerar_projeto(tmp_path_factory.mktemp("exemplo") / "projeto", tamanho=256)


@pytest.fixture
def exemplo(_exemplo_base, tmp_path):
    """Cópia descartável do projeto de exemplo (256 px): cada teste pode alterá-la à vontade."""
    destino = tmp_path / "exemplo"
    shutil.copytree(_exemplo_base, destino)
    return destino


def dados_reais():
    return (REPO / "EDS" / "1" / "1.2").is_dir() and (REPO / "estado" / "rotulos.npy").exists()


precisa_dados = pytest.mark.skipif(not dados_reais(), reason="dados da amostra RJS0649RJ ausentes")
