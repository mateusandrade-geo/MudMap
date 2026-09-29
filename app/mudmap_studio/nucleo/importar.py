"""Importa uma amostra direto das pastas do projeto MudMap (sem passar por .mudmap).

Reaproveita o decodificador do pipeline (scripts/common.py: recorte da barra de info,
overlay branco, exclusão do cabeçalho, máscara com resgate Si/Fe/Ti) — o app vê
exatamente os mesmos mapas/máscara que os scripts. Carrega canal a canal em uint8.

Fontes aceitas:
  - sítio ATIVO do projeto: config/classificacao.yaml + estado/rotulos.npy
  - sítio ARQUIVADO: sitios/<s>/info.json + sitios/<s>/estado/ (+ classificacao_<s>.yaml)
  - pasta EDS avulsa (só mapas; rótulos vazios)
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from .amostra import Amostra, Mineral, Vista
from .pipeline import common

ELEMENTOS_IGNORADOS = {"C", "O"}          # fora da fração de cátions (decisão do projeto)


@dataclass
class FonteSitio:
    sitio: str
    rotulo: str
    raiz: Path
    config: Path
    pasta_dados: str
    estado: Path = None
    ativo: bool = False

    @property
    def tem_rotulos(self):
        return self.estado is not None and (self.estado / "rotulos.npy").exists()


def raiz_do_projeto(pasta):
    p = Path(pasta).resolve()
    for q in [p, *p.parents]:
        if (q / "config" / "classificacao.yaml").exists():
            return q
    return None


def listar_sitios(raiz):
    raiz = Path(raiz)
    fontes = []
    cfg_path = raiz / "config" / "classificacao.yaml"
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        est = raiz / "estado"
        fontes.append(FonteSitio(
            sitio=str(cfg.get("sitio", "?")), rotulo="ativo — estado/", raiz=raiz,
            config=cfg_path, pasta_dados=cfg["pasta_dados"],
            estado=est if (est / "rotulos.npy").exists() else None, ativo=True))
    sd = raiz / "sitios"
    if sd.is_dir():
        for d in sorted(p for p in sd.iterdir() if p.is_dir()):
            info_p = d / "info.json"
            if not info_p.exists():
                continue
            info = json.loads(info_p.read_text(encoding="utf-8"))
            s = str(info.get("sitio", d.name))
            cfg_s = d / f"classificacao_{s}.yaml"
            fontes.append(FonteSitio(
                sitio=s, rotulo=f"arquivado — sitios/{d.name}", raiz=raiz,
                config=cfg_s if cfg_s.exists() else cfg_path,
                pasta_dados=info.get("pasta_dados", ""),
                estado=d / "estado" if (d / "estado" / "rotulos.npy").exists() else None))
    return fontes


def _estica_uint8(gray, mascara=None):
    ref = gray[mascara] if mascara is not None and mascara.any() else gray
    lo, hi = np.percentile(ref, [0.5, 99.5])
    if hi <= lo:
        hi = lo + 1
    return np.clip((gray - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)


def _carregar_bse(pasta, shape):
    arqs = sorted(Path(pasta).glob("Electron Image*.tif"))
    if not arqs:
        return None
    im = Image.open(arqs[0])
    arr = np.array(im)
    arr = arr[:common._altura_mapa(im, arr)]
    gray = arr[..., :3].mean(-1) if arr.ndim == 3 else arr.astype(np.float64)
    # faixa de título no topo ("Electron Image N" sobre branco) — mesma regra dos mapas
    fb = ((arr[..., :3].min(-1) if arr.ndim == 3 else gray) > 230).mean(axis=1)
    faixa = np.nonzero(fb[:int(0.05 * len(fb))] > 0.3)[0]   # linhas do título (texto quebra a faixa)
    if faixa.size and faixa[0] < 3:
        topo = int(faixa[-1]) + 4
        gray = gray.copy()
        gray[:topo] = np.median(gray[topo:topo + 20])
    if gray.shape != shape:
        dh, dw = abs(gray.shape[0] - shape[0]), abs(gray.shape[1] - shape[1])
        if dh <= 0.02 * shape[0] and dw <= 0.02 * shape[1]:
            g = np.zeros(shape, gray.dtype)                # recorta/completa poucas linhas
            r, c = min(shape[0], gray.shape[0]), min(shape[1], gray.shape[1])
            g[:r, :c] = gray[:r, :c]
            gray = g
        else:                                              # outra resolução -> reamostra
            gray = np.array(Image.fromarray(gray.astype(np.float32)).resize(
                (shape[1], shape[0]), Image.BILINEAR))
    return _estica_uint8(gray)


def _carregar_mapas(pasta, elementos, prog):
    mapas, overlay, pixel_um = [], None, None
    for i, e in enumerate(elementos):
        prog(0.05 + 0.6 * i / len(elementos), f"decodificando mapa {e}")
        arq = common._achar_arquivo(pasta, e)
        inten, branco = common._decodificar(arq)
        mapas.append(np.clip(np.rint(inten), 0, 255).astype(np.uint8))
        overlay = branco if overlay is None else (overlay & branco)
        if pixel_um is None:
            pixel_um = common.pixel_um_tiff(arq)
        del inten
    overlay = common._excluir_cabecalho(overlay)
    # faixa de título ("X Wt%") = linhas inteiras de overlay no topo: fora da máscara (o pipeline
    # nunca usa) -> zera nos mapas para não aparecer nas camadas de elementos
    topo = 0
    while topo < overlay.shape[0] and overlay[topo].all():
        topo += 1
    if 0 < topo < 0.1 * overlay.shape[0]:
        for m in mapas:
            m[:topo] = 0
    return mapas, overlay, pixel_um


def _mascara(mapas, overlay, elementos, corte):
    soma = np.zeros(mapas[0].shape, np.float64)
    for m in mapas:
        soma += m
    resgate = tuple(e for e in ("Si", "Fe", "Ti") if e in elementos)
    pilha = Vista(lambda i: mapas[i].astype(np.float64))
    return common.mascara_amostra(soma, overlay, corte, pilha, elementos, resgate=resgate)


def _ler_pasta(pasta, elementos, cfg, prog):
    """Mapas + máscara + BSE da pasta EDS -> (mapas, mascara, bse, pixel_um)."""
    mapas, overlay, px_tiff = _carregar_mapas(pasta, elementos, prog)
    prog(0.7, "máscara da amostra")
    mascara = _mascara(mapas, overlay, elementos, cfg.get("corte_fundo"))
    prog(0.8, "BSE")
    return mapas, mascara, _carregar_bse(pasta, mapas[0].shape), px_tiff or cfg.get("pixel_um", 1.0)


def _amostra(cfg, cfg_txt, amostra, sitio, elementos, lidos, rotulos, origem, **kw):
    mapas, mascara, bse, px = lidos
    return Amostra(
        amostra=cfg.get("amostra") or amostra, sitio=sitio, pixel_um=px, elementos=elementos,
        minerais=[Mineral(i, m["nome"], m.get("cor", "#888888")) for i, m in enumerate(cfg.get("minerais", []), start=1)],
        # area_min (px) da config: d_min_um convertido pelo pixel DESTA amostra
        area_min=common.resolver_escala(cfg, px).get("area_min", 30),
        mapas=mapas, bse=bse, mascara=mascara, rotulos=rotulos, config_yaml=cfg_txt, origem=origem, **kw)


def importar_sitio(fonte, progresso=None):
    prog = progresso or (lambda f, msg: None)
    cfg_txt = Path(fonte.config).read_text(encoding="utf-8")
    cfg = yaml.safe_load(cfg_txt)
    elementos = list(cfg["elementos"])
    pasta = Path(fonte.raiz) / fonte.pasta_dados
    if not pasta.is_dir():
        raise FileNotFoundError(f"Pasta de dados não encontrada: {pasta}")
    lidos = _ler_pasta(pasta, elementos, cfg, prog)
    shape = lidos[0][0].shape
    prog(0.9, "rótulos")
    if fonte.tem_rotulos:
        rot = np.load(fonte.estado / "rotulos.npy")
        if rot.shape != shape:
            raise ValueError(f"rotulos.npy {rot.shape} não bate com os mapas {shape}.")
    else:
        rot = np.zeros(shape, np.uint8)
    rot = rot.astype(np.uint8 if int(rot.max(initial=0)) < 256 else np.uint16)
    clusters = clusters_info = None
    if fonte.estado is not None and (fonte.estado / "clusters.npy").exists():
        c = np.load(fonte.estado / "clusters.npy")
        if c.shape == shape:
            clusters = c
            cj = fonte.estado / "clusters.json"
            clusters_info = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {}
    prog(1.0, "importado")
    return _amostra(cfg, cfg_txt, Path(fonte.raiz).name, fonte.sitio, elementos, lidos, rot,
                    {"raiz": str(fonte.raiz), "pasta_dados": fonte.pasta_dados,
                     "estado": str(fonte.estado) if fonte.estado else None,
                     "config": str(fonte.config), "fonte": fonte.rotulo},
                    clusters=clusters, clusters_info=clusters_info)


def elementos_da_pasta(pasta):
    els = []
    for arq in sorted(Path(pasta).glob("*.tif")):
        m = re.match(r"^([A-Z][a-z]?)\s", arq.name)
        if m and m.group(1) not in ELEMENTOS_IGNORADOS and m.group(1) not in els \
                and not arq.name.startswith(("EDS", "Electron")):
            els.append(m.group(1))
    return els


def importar_pasta_eds(pasta, progresso=None):
    """Pasta EDS avulsa (só mapas AZtec): rótulos vazios, minerais da config do projeto
    se houver um projeto acima da pasta."""
    pasta = Path(pasta)
    raiz = raiz_do_projeto(pasta)
    cfg, cfg_txt = {}, None
    if raiz:
        cfg_txt = (raiz / "config" / "classificacao.yaml").read_text(encoding="utf-8")
        cfg = yaml.safe_load(cfg_txt)
    disponiveis = elementos_da_pasta(pasta)
    elementos = [e for e in cfg.get("elementos", disponiveis) if e in disponiveis] or disponiveis
    if not elementos:
        raise FileNotFoundError("Nenhum mapa elemental (.tif) encontrado nesta pasta.")
    lidos = _ler_pasta(pasta, elementos, cfg, progresso or (lambda f, msg: None))
    return _amostra(cfg, cfg_txt, pasta.parent.name, pasta.name, elementos, lidos,
                    np.zeros(lidos[0][0].shape, np.uint8), {"pasta_dados": str(pasta), "fonte": "pasta EDS"})
