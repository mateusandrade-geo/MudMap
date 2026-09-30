"""Exemplo SINTÉTICO: um projeto MudMap completo gerado por código (sem dados reais).

Serve para experimentar o app e o pipeline logo depois de baixar, e para os testes
automáticos. Gera, numa pasta:
  config/classificacao.yaml   regras dos minerais (cópia das calibradas; ver recursos/)
  EDS/demo/<El> Wt%.tif       mapas no formato do AZtec: TIFF colorido de matiz fixo (brilho =
                              concentração), faixa de título "X Wt%" no topo, barra de escala
                              branca, barra de informação embaixo e metadados <PixelWidth_um> /
                              <ImageHeight_um> na tag 270 — o mesmo que scripts/common.py decodifica
  EDS/demo/Electron Image 1.tif   imagem de elétrons (BSE), alinhada aos mapas
  estado/rotulos.npy + progresso.json   (opcional) rótulos de REFERÊNCIA da cena: os grãos
                              que o gerador desenhou; a matriz argilosa fica livre (0) p/ segmentar

A cena imita um lamito: matriz argilosa (domínios de ilita e esmectita) com lâminas de biotita,
grãos de quartzo e feldspato (K e Na), pirita, óxidos de Fe e Ti, titanita, carbonatos, cimento
disseminado de sulfato de Ca e epóxi na borda. Determinística: mesma semente -> mesmos arquivos.

    from mudmap_studio.nucleo import exemplo
    raiz = exemplo.gerar_projeto("exemplo")
"""
import json
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

ELEMENTOS = ("Si", "Al", "Fe", "Mg", "K", "Ca", "Na", "Ti", "S")
PIXEL_UM = 0.1
SITIO = "demo"
PASTA_DADOS = "EDS/demo"
CONFIG = Path(__file__).resolve().parents[1] / "recursos" / "exemplo_classificacao.yaml"
VERSAO = 1                     # sobe quando a cena muda (o app regenera o exemplo em cache)

# matiz fixo de cada mapa (canal máximo = 1 -> intensidade = max(R,G,B), como no AZtec)
MATIZ = {"Si": (0.0, 0.6, 1.0), "Al": (1.0, 0.2, 0.2), "Fe": (1.0, 0.5, 0.0), "Mg": (0.0, 1.0, 0.3),
         "K": (0.8, 0.0, 1.0), "Ca": (1.0, 1.0, 0.0), "Na": (1.0, 0.0, 0.6), "Ti": (0.0, 1.0, 1.0),
         "S": (1.0, 0.9, 0.2)}

# fase: (mineral na config | None, fração de cátions Si Al Fe Mg K Ca Na Ti S, intensidade total, cinza BSE)
FASES = {
    "epoxi":       (None,           (.20, .10, .05, .05, .05, .05, .40, .05, .05), 40, 25),
    "ilita":       ("ilita",        (.27, .31, .08, .015, .16, .03, .07, .02, .02), 230, 95),
    "esmectita":   ("esmectita",    (.27, .33, .09, .015, .04, .09, .12, .02, .02), 215, 88),
    "biotita":     ("biotita",      (.27, .22, .17, .20, .11, .01, .01, .005, .005), 280, 122),
    "quartzo":     ("quartzo",      (.88, .03, .02, .01, .02, .01, .01, .01, .01), 190, 105),
    "k_feldspato": ("feldspato",    (.28, .24, .01, .01, .40, .01, .03, .01, .01), 360, 128),
    "albita":      ("feldspato",    (.28, .14, .01, .01, .02, .03, .49, .01, .01), 360, 112),
    "pirita":      ("pirita",       (.03, .02, .45, .01, .01, .02, .01, .01, .44), 350, 235),
    "oxido_fe":    ("oxido_fe",     (.10, .05, .75, .02, .01, .02, .02, .02, .01), 260, 215),
    "oxido_ti":    ("oxido_ti",     (.04, .03, .04, .01, .01, .02, .02, .82, .01), 170, 178),
    "titanita":    ("titanita",     (.30, .04, .03, .01, .01, .27, .02, .30, .02), 300, 160),
    "anquerita":   ("anquerita",    (.05, .03, .18, .22, .01, .47, .02, .01, .01), 260, 150),
    "calcita":     ("carbonato_ca", (.04, .03, .02, .02, .01, .85, .01, .01, .01), 230, 140),
    "gipsita":     ("sulfato_ca",   (.04, .03, .02, .01, .01, .44, .02, .01, .42), 250, 135),
}
MATRIZ = ("ilita", "esmectita")           # domínios de fundo: ficam livres nos rótulos de referência

# grãos por campo de 640 px: (fase, quantidade, raio mín, raio máx (px), alongamento, irregularidade)
GRAOS = [("pirita", 1, 13, 13, 1.0, .10), ("titanita", 1, 9, 9, 1.3, .15),
         ("oxido_ti", 1, 7, 7, 1.2, .15), ("anquerita", 2, 12, 16, 1.4, .10),
         ("calcita", 2, 14, 18, 1.2, .20), ("k_feldspato", 4, 18, 38, 1.4, .20),
         ("albita", 3, 16, 32, 1.5, .20), ("quartzo", 16, 8, 45, 1.3, .25),
         ("oxido_fe", 10, 3, 6, 1.0, .05)]


def _forma(r, rng, alongamento, irreg, angulo):
    """Máscara (recorte quadrado) de um grão: raio com harmônicos de baixa ordem, alongado e girado."""
    R = int(np.ceil(r * alongamento * (1 + 2 * irreg))) + 2
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1].astype(float)
    c, s = np.cos(angulo), np.sin(angulo)
    u, v = (xx * c + yy * s) / alongamento, -xx * s + yy * c
    th, rho = np.arctan2(v, u), np.hypot(u, v)
    borda = np.ones_like(th)
    for k in range(2, 6):
        borda += rng.uniform(-irreg, irreg) / k * 2 * np.cos(k * th + rng.uniform(0, 2 * np.pi))
    return rho <= r * borda


def _colocar(fase_map, livre_de, forma, rng, codigo, tentativas=300):
    """Põe `forma` num lugar em que só há fases de `livre_de` (sem sobrepor outros grãos)."""
    H, W = fase_map.shape
    h, w = forma.shape
    if h >= H or w >= W:                       # campo pequeno (--tamanho baixo): o grão não cabe
        return False
    for _ in range(tentativas):
        y, x = int(rng.integers(0, H - h)), int(rng.integers(0, W - w))
        janela = fase_map[y:y + h, x:x + w]
        if np.isin(janela[forma], livre_de).all():
            janela[forma] = codigo
            return True
    return False


def cena(tamanho=640, semente=649):
    """-> (fases HxW uint8 com o índice em FASES, nomes das fases). Determinística."""
    rng = np.random.default_rng(semente)
    nomes = list(FASES)
    cod = {n: i for i, n in enumerate(nomes)}
    H = W = int(tamanho)
    esc = (H * W) / 640 ** 2
    # domínios da matriz (ruído suave) e borda de epóxi irregular à esquerda + poros
    campo = ndi.gaussian_filter(rng.normal(size=(H, W)), 40)
    fase = np.where(campo > 0, cod["ilita"], cod["esmectita"]).astype(np.uint8)
    borda = ndi.gaussian_filter(rng.normal(size=H), 12)
    borda = 0.10 * W + borda / (np.abs(borda).max() or 1) * 0.04 * W
    fase[np.arange(W)[None, :] < borda[:, None]] = cod["epoxi"]
    matriz = [cod[n] for n in MATRIZ]
    for _ in range(max(1, round(3 * esc))):
        _colocar(fase, matriz, _forma(rng.uniform(7, 14), rng, 1.2, .15, rng.uniform(0, np.pi)),
                 rng, cod["epoxi"])
    # lâminas de biotita alinhadas (trama do lamito)
    for _ in range(max(1, round(9 * esc))):
        comp, larg = rng.uniform(35, 60), rng.uniform(4, 6)
        _colocar(fase, matriz, _forma(larg, rng, comp / larg, .03, np.deg2rad(15 + rng.normal(0, 8))),
                 rng, cod["biotita"])
    for nome, n, rmin, rmax, along, irreg in GRAOS:
        for _ in range(max(1, round(n * esc))):
            r = rng.uniform(rmin, rmax)
            _colocar(fase, matriz, _forma(r, rng, along, irreg, rng.uniform(0, np.pi)), rng, cod[nome])
    # cimento disseminado de sulfato de Ca (manchas de 1–3 px na matriz)
    for _ in range(round(220 * esc)):
        _colocar(fase, matriz, _forma(rng.uniform(1.0, 2.5), rng, 1.0, 0, 0), rng, cod["gipsita"], 20)
    return fase, nomes


def sintetizar(fase, nomes, semente=649):
    """Fases -> (mapas de intensidade uint8 por elemento, BSE uint8). Borda borrada (volume de
    interação do feixe) + ruído de contagem, como num mapa EDS."""
    rng = np.random.default_rng(semente + 1)
    comp = np.array([FASES[n][1] for n in nomes], float)
    comp /= comp.sum(1, keepdims=True)
    total = np.array([FASES[n][2] for n in nomes], float)
    mapas = {}
    for i, el in enumerate(ELEMENTOS):
        ideal = ndi.gaussian_filter((comp[:, i] * total)[fase].astype(np.float32), 1.0)
        ruido = rng.normal(size=fase.shape).astype(np.float32) * np.sqrt(ideal + 1) * 1.2
        mapas[el] = np.clip(np.rint(ideal + ruido), 0, 255).astype(np.uint8)
    cinza = np.array([FASES[n][3] for n in nomes], np.float32)
    bse = ndi.gaussian_filter(cinza[fase], 0.8) + rng.normal(0, 5, fase.shape)
    return mapas, np.clip(np.rint(bse), 0, 255).astype(np.uint8)


def _faixas(img, titulo, cor_titulo, px, barra=40):
    """Acrescenta ao mapa (H×W×3) o que o AZtec queima na imagem: faixa de título branca no topo,
    barra de escala branca e barra de informação embaixo (fora do mapa; recortada pelos metadados)."""
    H, W = img.shape[:2]
    out = np.full((H + barra, W, 3), 238, np.uint8)
    out[:H] = img
    im = Image.fromarray(out)
    d = ImageDraw.Draw(im)
    topo = max(12, round(0.028 * H))
    d.rectangle((0, 0, W - 1, topo - 1), fill=(255, 255, 255))
    d.text((6, max(0, topo // 2 - 6)), titulo, fill=cor_titulo)
    L = round(10 / px)                                   # barra de 10 µm
    x1, y1 = W - 24, H - 22
    d.rectangle((x1 - L, y1, x1, y1 + 4), fill=(255, 255, 255))
    d.text((x1 - L, y1 - 14), "10 µm", fill=(255, 255, 255))
    d.text((8, H + 12), f"MudMap · exemplo sintético · {titulo}", fill=(60, 60, 60))
    return im


def _salvar_tiff(im, caminho, px, h_mapa):
    desc = (f"<Data><PixelWidth_um>{px}</PixelWidth_um>"
            f"<ImageHeight_um>{h_mapa * px:.6f}</ImageHeight_um></Data>")
    im.save(caminho, tiffinfo={270: desc})


def gerar_projeto(destino, tamanho=640, semente=649, rotulos=True, progresso=None):
    """Escreve o projeto de exemplo em `destino` (criado se preciso) e devolve o Path da raiz.
    rotulos=True grava estado/rotulos.npy com os grãos de referência (matriz livre)."""
    prog = progresso or (lambda f, msg: None)
    raiz = Path(destino)
    pasta = raiz / PASTA_DADOS
    pasta.mkdir(parents=True, exist_ok=True)
    (raiz / "config").mkdir(exist_ok=True)
    cfg_txt = CONFIG.read_text(encoding="utf-8")
    (raiz / "config" / "classificacao.yaml").write_text(cfg_txt, encoding="utf-8")
    prog(0.05, "desenhando a cena")
    fase, nomes = cena(tamanho, semente)
    prog(0.3, "sintetizando os mapas")
    mapas, bse = sintetizar(fase, nomes, semente)
    H = fase.shape[0]
    for k, el in enumerate(ELEMENTOS):
        prog(0.4 + 0.5 * k / len(ELEMENTOS), f"gravando mapa {el}")
        rgb = np.rint(mapas[el][..., None] * np.array(MATIZ[el])).astype(np.uint8)
        cor = tuple(int(255 * c) for c in MATIZ[el])
        _salvar_tiff(_faixas(rgb, f"{el} Wt%", cor, PIXEL_UM), pasta / f"{el} Wt%.tif", PIXEL_UM, H)
    _salvar_tiff(_faixas(np.repeat(bse[..., None], 3, -1), "Electron Image 1", (0, 0, 0), PIXEL_UM),
                 pasta / "Electron Image 1.tif", PIXEL_UM, H)
    if rotulos:
        prog(0.95, "rótulos de referência")
        cfg = yaml.safe_load(cfg_txt)
        ids = {m["nome"]: i for i, m in enumerate(cfg["minerais"], start=1)}
        lut = np.array([0 if (FASES[n][0] is None or n in MATRIZ) else ids[FASES[n][0]] for n in nomes],
                       np.int16)
        rot = lut[fase]
        topo = max(12, round(0.028 * H)) + 3                      # faixa de título = fora da amostra
        rot[:topo] = 0
        est = raiz / "estado"
        est.mkdir(exist_ok=True)
        np.save(est / "rotulos.npy", rot)
        hoje = str(date.today())
        feitos = [dict(id=int(i), mineral=cfg["minerais"][i - 1]["nome"],
                       condicoes=cfg["minerais"][i - 1].get("condicoes", {}), data=hoje,
                       origem="referência do exemplo sintético")
                  for i in sorted(int(v) for v in np.unique(rot) if v)]
        (est / "progresso.json").write_text(json.dumps(feitos, ensure_ascii=False, indent=2), encoding="utf-8")
    (raiz / "LEIA-ME.txt").write_text(
        "Projeto de EXEMPLO do MudMap, gerado por código (dados sintéticos, não é uma amostra real).\n"
        "Regerar: python scripts/gerar_exemplo.py  (na raiz do repositório)\n"
        f"versão da cena: {VERSAO} · semente {semente} · {tamanho}x{tamanho} px · {PIXEL_UM} µm/px\n",
        encoding="utf-8")
    prog(1.0, "exemplo pronto")
    return raiz


def garantir(destino, progresso=None):
    """Gera o exemplo em `destino` só se faltar ou for de outra versão da cena (preserva o que
    o usuário já fez nele, ex.: rótulos exportados p/ estado/). -> Path da raiz."""
    raiz = Path(destino)
    leia = raiz / "LEIA-ME.txt"
    if not (leia.exists() and f"versão da cena: {VERSAO} " in leia.read_text(encoding="utf-8")
            and (raiz / "config" / "classificacao.yaml").exists()):
        gerar_projeto(raiz, progresso=progresso)
    return raiz
