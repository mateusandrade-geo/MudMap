"""Formato .mudmap — pacote ÚNICO de uma amostra/sítio (arquivo ZIP).

Conteúdo:
  manifest.json      metadados (amostra, sítio, pixel_um, elementos, minerais+cores, area_min…)
  config.yaml        snapshot da config de classificação (regras p/ o modo Segmentar)
  mapas/<El>.png     intensidade decodificada por elemento (uint8, sem barra/cabeçalho)
  bse.png            Electron Image (uint8), alinhada aos mapas
  mascara.png        máscara da amostra (0/255; com resgate Si/Fe/Ti)
  rotulos.npy        id do mineral por pixel (= estado/rotulos.npy)
  clusters.npy/.json (opcional) k-means do reconhecer.py (= estado/clusters.*)
  historico/rotulos_<data>.npy  versões anteriores dos rótulos (as 5 últimas, 1 por salvamento
                     em que os rótulos mudaram) — listadas em manifest["versoes"]
manifest["edicoes"] = registro das edições feitas no MudMap Studio (proveniência).
Salvar é atômico: grava num .tmp e troca no fim.
"""
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .amostra import Amostra, Mineral

EXT = ".mudmap"
FORMATO = "mudmap"
VERSAO = 1
MAX_VERSOES = 5


def _png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def _npy(arr):
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return buf.getvalue()


def _ler_png(z, nome):
    with z.open(nome) as f:
        return np.array(Image.open(io.BytesIO(f.read())))


def _ler_npy(z, nome):
    with z.open(nome) as f:
        return np.load(io.BytesIO(f.read()), allow_pickle=False)


def _versoes_anteriores(caminho, rot_novo):
    """Versões de rótulos a carregar para o novo arquivo: o rotulos.npy atual do arquivo em disco
    (se diferente do novo) + as versões que ele já guardava. -> [(nome, bytes, meta)]"""
    out = []
    if not (caminho.exists() and zipfile.is_zipfile(caminho)):
        return out
    try:
        with zipfile.ZipFile(caminho) as z:
            man = json.loads(z.read("manifest.json").decode("utf-8"))
            if man.get("formato") != FORMATO:
                return out
            nomes = set(z.namelist())
            antigo = z.read("rotulos.npy")
            if antigo != rot_novo:
                quando = man.get("salvo_em", "sem-data")
                nome = "historico/rotulos_" + quando.replace(":", "").replace("-", "") + ".npy"
                out.append((nome, antigo, {"arquivo": nome, "salvo_em": quando,
                                           "app": man.get("app")}))
            for meta in man.get("versoes", []):
                if meta.get("arquivo") in nomes and all(meta["arquivo"] != o[0] for o in out):
                    out.append((meta["arquivo"], z.read(meta["arquivo"]), meta))
    except Exception:  # noqa: BLE001 — arquivo antigo ilegível: salva sem histórico
        return []
    return out[:MAX_VERSOES]


def salvar(am, caminho, progresso=None):
    from .. import __version__
    prog = progresso or (lambda f, msg: None)
    caminho = Path(caminho)
    if caminho.suffix.lower() != EXT:
        caminho = caminho.with_suffix(EXT)
    tmp = caminho.with_name(caminho.name + ".tmp")
    rot = am.rotulos
    rot = rot.astype(np.uint8 if int(rot.max(initial=0)) < 256 else np.uint16)
    rot_bytes = _npy(rot)
    versoes = _versoes_anteriores(caminho, rot_bytes)
    manifest = {
        "formato": FORMATO, "versao": VERSAO, "app": f"MudMap Studio {__version__}",
        "salvo_em": datetime.now().isoformat(timespec="seconds"),
        "amostra": am.amostra, "sitio": am.sitio, "pixel_um": am.pixel_um,
        "shape": list(am.shape), "fov_um": [round(v, 3) for v in am.fov_um],
        "elementos": am.elementos, "area_min": am.area_min,
        "minerais": [{"id": m.id, "nome": m.nome, "cor": m.cor} for m in am.minerais],
        "tem_bse": am.bse is not None, "origem": am.origem,
        "versoes": [meta for _n, _b, meta in versoes],
        "edicoes": am.log_edicoes[-2000:],
    }
    armazenar = zipfile.ZIP_STORED            # PNG já é comprimido
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if am.config_yaml:
            z.writestr("config.yaml", am.config_yaml)
        for i, (el, mapa) in enumerate(zip(am.elementos, am.mapas)):
            prog(0.8 * i / len(am.mapas), f"gravando mapa {el}")
            z.writestr(f"mapas/{el}.png", _png(mapa), compress_type=armazenar)
        prog(0.85, "gravando BSE e rótulos")
        if am.bse is not None:
            z.writestr("bse.png", _png(am.bse), compress_type=armazenar)
        z.writestr("mascara.png", _png(am.mascara.astype(np.uint8) * 255), compress_type=armazenar)
        z.writestr("rotulos.npy", rot_bytes)
        for nome, dados, _meta in versoes:
            z.writestr(nome, dados)
        if am.clusters is not None:
            z.writestr("clusters.npy", _npy(am.clusters))
            z.writestr("clusters.json", json.dumps(am.clusters_info or {}, ensure_ascii=False, indent=2))
    os.replace(tmp, caminho)
    am.caminho = caminho
    prog(1.0, "salvo")
    return caminho


def abrir(caminho, progresso=None):
    prog = progresso or (lambda f, msg: None)
    caminho = Path(caminho)
    with zipfile.ZipFile(caminho) as z:
        man = json.loads(z.read("manifest.json").decode("utf-8"))
        if man.get("formato") != FORMATO:
            raise ValueError("Este arquivo não é um pacote .mudmap.")
        if int(man.get("versao", 0)) > VERSAO:
            raise ValueError("Este .mudmap foi criado por uma versão mais nova do MudMap Studio.")
        nomes = set(z.namelist())
        mapas = []
        for i, el in enumerate(man["elementos"]):
            prog(0.8 * i / len(man["elementos"]), f"lendo mapa {el}")
            mapas.append(_ler_png(z, f"mapas/{el}.png"))
        prog(0.85, "lendo BSE e rótulos")
        bse = _ler_png(z, "bse.png") if "bse.png" in nomes else None
        if bse is not None and bse.ndim == 3:
            bse = bse[..., :3].mean(-1).astype(np.uint8)
        mascara = _ler_png(z, "mascara.png") > 0
        rotulos = _ler_npy(z, "rotulos.npy")
        config_yaml = z.read("config.yaml").decode("utf-8") if "config.yaml" in nomes else None
        clusters = _ler_npy(z, "clusters.npy") if "clusters.npy" in nomes else None
        clusters_info = (json.loads(z.read("clusters.json").decode("utf-8"))
                         if "clusters.json" in nomes else None)
    prog(1.0, "aberto")
    am = Amostra(
        amostra=man["amostra"], sitio=man["sitio"], pixel_um=man["pixel_um"],
        elementos=man["elementos"],
        minerais=[Mineral(int(m["id"]), m["nome"], m["cor"]) for m in man["minerais"]],
        area_min=man.get("area_min", 30), mapas=mapas, bse=bse, mascara=mascara,
        rotulos=rotulos, config_yaml=config_yaml, origem=man.get("origem"), caminho=caminho,
        clusters=clusters, clusters_info=clusters_info,
    )
    am.log_edicoes = list(man.get("edicoes", []))
    am.versoes = list(man.get("versoes", []))
    return am
