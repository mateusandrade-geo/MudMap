"""Utilidades compartilhadas para os mapas EDS coloridos (AZtec).

Cada mapa de elemento é uma imagem RGBA de matiz fixo, onde o BRILHO codifica
a concentração. Convertemos brilho -> intensidade (canal máximo). Recortamos a
barra de informação inferior (usando os metadados), mascaramos o overlay branco
(barra de escala) queimado dentro do mapa e excluímos a FAIXA DE CABEÇALHO do topo
(título 'X Wt%') via _excluir_cabecalho — tudo sem mudar as dimensões (alinha com rotulos).
"""
import copy
import re
from pathlib import Path
import numpy as np
import yaml
from PIL import Image


def carregar_config(caminho="config/classificacao.yaml"):
    """Lê a config, confere pixel_um com o TIFF do sítio (null/'auto' = usa o do TIFF) e
    converte os parâmetros de tamanho em µm para px (resolver_escala)."""
    cfg = yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))
    px_tiff = None
    try:
        px_tiff = pixel_um_tiff(_achar_arquivo(cfg["pasta_dados"], cfg["elementos"][0]))
    except (KeyError, IndexError, TypeError, FileNotFoundError):
        pass                                          # config sem dados acessíveis: só a config
    px = cfg.get("pixel_um")
    if px in (None, "auto"):
        cfg["pixel_um"] = px_tiff
    elif px_tiff and abs(float(px) / px_tiff - 1) > 0.01:
        raise ValueError(f"pixel_um da config ({px}) ≠ do TIFF ({px_tiff:.6g}) em {cfg['pasta_dados']} "
                         f"— trocou de sítio sem atualizar? (use pixel_um: auto)")
    return resolver_escala(cfg)


def pixel_um_tiff(arq):
    """µm/px gravado pelo AZtec no TIFF (<PixelWidth_um> da tag 270), ou None."""
    try:
        desc = Image.open(arq).tag_v2.get(270, "")
        return float(re.search(r"<PixelWidth_um>([\d.]+)</PixelWidth_um>", desc).group(1))
    except Exception:
        return None


# ---------------------------------------------------------------- escala física
# Parâmetros de TAMANHO podem vir em µm (sufixo _um) e viram px AQUI, num ponto só, pelo
# pixel_um do sítio — o resto do código só vê px. d_min_um = diâmetro equivalente do menor
# grão (área = π(d/2)², a mesma métrica do Wentworth do relatório) -> area_min;
# suavizar_um / close_um = raios -> suavizar / close. Chaves só em px continuam valendo
# (configs arquivadas reproduzem idênticas). Pisos: sem eles, num sítio de pixel grosso o
# limiar físico viraria 0 px e a limpeza de ruído sumiria.
AREA_MIN_PX, RAIO_MIN_PX = 4, 1
_PAR_GLOBAL = (("d_min_um", "area_min", "area"),)
_PAR_SUAV = (("suavizar_um", "suavizar", "raio"),)
_PAR_FORMA = (("close_um", "close", "raio"), ("d_min_um", "area_min", "area"))


def _um_para_px_bruto(v, px, tipo):
    return int(round(v / px)) if tipo == "raio" else int(round(np.pi * (v / 2) ** 2 / px ** 2))


def _um_para_px(v, px, tipo):
    """0 continua 0 (= opção desligada); senão aplica o piso."""
    if v <= 0:
        return 0
    return max(RAIO_MIN_PX if tipo == "raio" else AREA_MIN_PX, _um_para_px_bruto(v, px, tipo))


def _px_para_um(n, px, tipo):
    return round(n * px, 3) if tipo == "raio" else round(2 * np.sqrt(n / np.pi) * px, 3)


def _locais_regra(m, nome):
    yield m, _PAR_SUAV, nome
    for g in m.get("mapas_grupos") or []:
        yield g, _PAR_SUAV, f"{nome}/{g.get('nome')}"
    if isinstance(m.get("forma"), dict):
        yield m["forma"], _PAR_FORMA, f"{nome}/forma"


def _locais(cfg):
    """(dict, pares µm↔px, onde) de cada lugar da config com parâmetro de tamanho."""
    yield cfg, _PAR_GLOBAL, "config"
    for m in cfg.get("minerais") or []:
        yield from _locais_regra(m, m.get("nome"))


def em_um(cfg):
    """True se a config usa parâmetros de tamanho em µm."""
    return any(k in d for d, pares, _o in _locais(cfg) for k, _p, _t in pares)


def resolver_escala(cfg, pixel_um=None):
    """Cópia da config com as chaves em px preenchidas a partir das em µm (pixel_um: o dado,
    senão o da config). Idempotente; µm e px divergentes no mesmo lugar = erro."""
    cfg = copy.deepcopy(cfg)
    if not em_um(cfg):
        return cfg
    px = float(pixel_um or cfg.get("pixel_um") or 0)
    if px <= 0:
        raise ValueError("pixel_um ausente: necessário para converter os parâmetros em µm.")
    pisos = []
    for d, pares, onde in _locais(cfg):
        for k_um, k_px, tipo in pares:
            if k_um not in d:
                continue
            n = _um_para_px(float(d[k_um]), px, tipo)
            if k_px in d and int(d[k_px]) != n:
                raise ValueError(f"{onde}: '{k_um}: {d[k_um]}' = {n} px, mas '{k_px}: {d[k_px]}' "
                                 f"também foi dado — use só um.")
            if n > _um_para_px_bruto(float(d[k_um]), px, tipo):
                pisos.append(f"{onde}.{k_um}={d[k_um]} → {n} px")
            d[k_px] = n
    if pisos:
        print(f"[escala] pixel {px:.4g} µm: limiar abaixo da resolução, piso aplicado: {'; '.join(pisos)}")
    return cfg


def para_um(regra, regra_original, pixel_um):
    """Inverso p/ GRAVAR uma regra editada em px numa config em µm: troca cada chave em px
    pela em µm; se o px não mudou, mantém o valor µm original (ida e volta exata)."""
    regra, orig, px = copy.deepcopy(regra), regra_original or {}, float(pixel_um)
    grupos_orig = {g.get("nome"): g for g in orig.get("mapas_grupos") or []}
    alvos = [(regra, orig, _PAR_SUAV)]
    alvos += [(g, grupos_orig.get(g.get("nome"), {}), _PAR_SUAV) for g in regra.get("mapas_grupos") or []]
    if isinstance(regra.get("forma"), dict):
        alvos.append((regra["forma"], orig.get("forma") or {}, _PAR_FORMA))
    for d, o, pares in alvos:
        for k_um, k_px, tipo in pares:
            if k_px not in d:
                continue
            n = int(d.pop(k_px))
            igual = k_um in o and _um_para_px(float(o[k_um]), px, tipo) == n
            d[k_um] = o[k_um] if igual else _px_para_um(n, px, tipo)
    return regra


def _achar_arquivo(pasta, el):
    pasta = Path(pasta)
    for padrao in (f"{el}.tif", f"{el} *.tif", f"{el}Wt*.tif"):
        achados = sorted(pasta.glob(padrao))
        if achados:
            return achados[0]
    raise FileNotFoundError(f"Mapa do elemento '{el}' ausente em {pasta}")


def _altura_mapa(im, arr):
    """Altura útil do mapa (exclui barra de info) a partir dos metadados; fallback por deteccao."""
    try:
        desc = im.tag_v2.get(270, "")  # ImageDescription
        pw = float(re.search(r"<PixelWidth_um>([\d.]+)</PixelWidth_um>", desc).group(1))
        ih = float(re.search(r"<ImageHeight_um>([\d.]+)</ImageHeight_um>", desc).group(1))
        return int(round(ih / pw))
    except Exception:
        # fallback: primeira linha (de baixo p/ cima) do bloco final claro e uniforme
        g = arr[..., :3].mean(-1) if arr.ndim == 3 else arr.astype(float)
        bright = (g > 235).mean(axis=1)
        h = g.shape[0]
        r = h
        while r > 0 and bright[r - 1] > 0.4:
            r -= 1
        return r if r < h else h


def _decodificar(path):
    """Retorna (intensidade float HxW, mascara_branco_overlay HxW bool) do mapa colorido, sem a barra."""
    im = Image.open(path)
    arr = np.array(im)
    hmap = _altura_mapa(im, arr)
    arr = arr[:hmap]
    rgb = arr[..., :3].astype(float)
    intensidade = rgb.max(-1)                 # matiz fixo -> valor = concentracao
    branco = rgb.min(-1) > 230                # overlay branco queimado
    return intensidade, branco


def carregar_mapas(pasta, elementos):
    """Empilha um canal de intensidade por elemento -> (stack HxWxN, overlay HxW bool)."""
    canais, overlay = [], None
    for e in elementos:
        inten, branco = _decodificar(_achar_arquivo(pasta, e))
        canais.append(inten)
        overlay = branco if overlay is None else (overlay & branco)
    overlay = _excluir_cabecalho(overlay)
    return np.stack(canais, axis=-1), overlay


def _excluir_cabecalho(overlay, frac_min=0.3, margem=3):
    """Exclui a FAIXA DE CABEÇALHO no topo (título 'X Wt%' dos mapas AZtec): as linhas
    superiores contíguas dominadas por branco (fundo do título). O texto colorido do
    título vaza para a amostra e, suavizado, é segmentado por engano; aqui marcamos a
    faixa inteira como overlay (não-amostra). NÃO altera as dimensões (mantém alinhado
    com rotulos.npy)."""
    if overlay is None:
        return overlay
    frac_branco = overlay.mean(axis=1)
    h = 0
    while h < len(frac_branco) and frac_branco[h] > frac_min:
        h += 1
    if 0 < h < 0.1 * overlay.shape[0]:          # só uma faixa fina no topo
        overlay = overlay.copy()
        overlay[:h + margem, :] = True
    return overlay


def fracao_cations(stack):
    """Normaliza cada pixel para fração. Retorna (frac, soma_total)."""
    soma = stack.sum(axis=-1, keepdims=True)
    frac = np.divide(stack, soma, out=np.zeros_like(stack), where=soma > 0)
    return frac, soma[..., 0]


def mascara_amostra(soma_total, overlay=None, corte=None, stack=None, elementos=None,
                    resgate=("Si", "Fe", "Ti")):
    """Separa amostra do fundo (epóxi). corte=None estima por Otsu. Remove overlay.

    RESGATE: minerais cujo sinal TOTAL de cátions é baixo (parecido com epóxi) e que o
    Otsu da soma descarta. Casos: quartzo (SiO2, O não contado -> soma baixa), óxido de Fe
    FINO ("buraco de baixo Si": pouca sílica -> soma baixa) e óxido de Ti (TiO2: só O e Ti,
    O não contado -> soma baixa). Se `stack`/`elementos` forem dados, pixels com um elemento
    diagnóstico forte (default Si, Fe e Ti; limiar Otsu do próprio elemento) são resgatados
    para a amostra.
    """
    valido = soma_total > 0
    if overlay is not None:
        valido = valido & ~overlay
    from skimage.filters import threshold_otsu
    if corte is None:
        corte = threshold_otsu(soma_total[valido])
    m = soma_total > corte
    if stack is not None and elementos is not None:
        for e in resgate:
            ch = stack[..., elementos.index(e)]
            m = m | (valido & (ch > threshold_otsu(ch[valido])))
    if overlay is not None:
        m = m & ~overlay
    return m


def canal(frac, elementos, chave):
    """Canal para elemento isolado, soma 'A+B', razão 'A/B' ou diferença 'A-B'.
    (Nomes de elemento não têm +,-,/ então a divisão do texto é inequívoca.)"""
    chave = chave.strip()
    idx = lambda e: elementos.index(e.strip())
    if "/" in chave:
        a, b = chave.split("/")
        num, den = frac[..., idx(a)], frac[..., idx(b)]
        return np.divide(num, den, out=np.zeros_like(num), where=den > 0)
    if "-" in chave:
        a, b = chave.split("-")
        return frac[..., idx(a)] - frac[..., idx(b)]
    if "+" in chave:
        return sum(frac[..., idx(p)] for p in chave.split("+"))
    return frac[..., idx(chave)]


def avaliar_expr(vals, expr):
    """Avalia '>0.85', '<0.05' ou faixa '0.25 - 0.45' sobre um array."""
    expr = expr.strip()
    if expr[0] not in "<>":
        lo, hi = (float(x) for x in expr.split("-"))
        return (vals >= lo) & (vals <= hi)
    return vals > float(expr[1:]) if expr[0] == ">" else vals < float(expr[1:])


def mascara_mineral(frac, elementos, condicoes):
    """Combina todas as condições de um mineral com E lógico -> máscara booleana."""
    m = np.ones(frac.shape[:2], dtype=bool)
    for chave, expr in condicoes.items():
        m &= avaliar_expr(canal(frac, elementos, chave), expr)
    return m


def id_e_regra(cfg, nome):
    """id (posição+1) e dict do mineral pelo nome."""
    for i, m in enumerate(cfg["minerais"], start=1):
        if m["nome"] == nome:
            return i, m
    raise KeyError(f"Mineral '{nome}' não está no config.")
