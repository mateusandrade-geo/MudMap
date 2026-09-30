"""Diagnóstico do ambiente e do projeto MudMap — rode ao começar (ou retomar) numa máquina.

Só lê; não altera nada. Confere:
  1. Python e pacotes (versões iguais às fixadas em requirements*.txt? PyQt6 só é preciso p/ o app)
  2. projeto: config/classificacao.yaml legível (rodar na raiz do projeto ou usar --projeto)
  3. sítio ativo: pasta_dados, um mapa por elemento, BSE, pixel_um (config × TIFF), escala em µm
  4. regras da config: nomes, fontes, condições bem formadas e canais citados presentes nos mapas
  5. estado/: rotulos.npy com as dimensões dos mapas e ids válidos; progresso.json; clusters da config atual
  6. sítios arquivados (sitios/<s>/) e pacotes saida/mudmap/*.mudmap
Termina com a lista de problemas e o PRÓXIMO PASSO. Código de saída 1 se houver ERRO.

Uso (raiz do projeto): python scripts/diagnostico.py [--projeto <pasta>] [--rapido]
  --rapido: não decodifica os mapas (só confere se os arquivos existem)
"""
import argparse
import json
import os
import re
import sys
import zipfile
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

# módulo de import -> nome no PyPI; os do pipeline são obrigatórios, o PyQt6 só para o app
PACOTES = [("numpy", "numpy"), ("scipy", "scipy"), ("skimage", "scikit-image"), ("sklearn", "scikit-learn"),
           ("PIL", "pillow"), ("yaml", "PyYAML"), ("matplotlib", "matplotlib"), ("pandas", "pandas")]
PACOTES_APP = [("PyQt6", "PyQt6")]
FONTES = ("regra", "mapa", "cluster")


class Relato:
    def __init__(self):
        self.erros, self.avisos = [], []

    def ok(self, msg):
        print(f"  OK     {msg}")

    def aviso(self, msg):
        print(f"  AVISO  {msg}")
        self.avisos.append(msg)

    def erro(self, msg):
        print(f"  ERRO   {msg}")
        self.erros.append(msg)

    @staticmethod
    def secao(titulo):
        print(f"\n{titulo}")


def fixadas():
    """{nome_pypi_minúsculo: versão} lidas de requirements-scripts.txt e requirements.txt."""
    out = {}
    for arq in ("requirements-scripts.txt", "requirements.txt"):
        p = REPO / arq
        if p.exists():
            for linha in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s#;]+)", linha)
                if m:
                    out[m.group(1).lower()] = m.group(2)
    return out


def checar_ambiente(r):
    r.secao("1. Python e pacotes")
    v = sys.version_info
    txt = f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})"
    (r.ok if v >= (3, 12) else r.aviso)(txt + ("" if v >= (3, 12) else
                                              " — as versões fixadas pedem 3.12+; resultados podem diferir"))
    pin = fixadas()
    for mod, dist in PACOTES + PACOTES_APP:
        app = (mod, dist) in PACOTES_APP
        try:
            ver = metadata.version(dist)
        except metadata.PackageNotFoundError:
            if app:
                r.aviso(f"{dist} ausente: o MudMap Studio não abre (os scripts funcionam). "
                        f"pip install -r requirements.txt")
            else:
                r.erro(f"{dist} ausente: pip install -r requirements-scripts.txt")
            continue
        alvo = pin.get(dist.lower())
        if alvo and ver != alvo:
            r.aviso(f"{dist} {ver} (testado: {alvo}) — o k-means pode não ser idêntico ao salvo")
        else:
            r.ok(f"{dist} {ver}")


def _mil(n):
    return f"{n:,}".replace(",", ".")


def _canais(expr):
    for s in "+-/":
        expr = expr.replace(s, " ")
    return [t for t in expr.split() if t]


def validar_config(cfg, elementos_disponiveis=None):
    """-> (erros, avisos) das regras da config. elementos_disponiveis = elementos com mapa na pasta
    (para mapas_seg extras, como o Na do feldspato); None = não conferir arquivos."""
    import numpy as np
    from common import avaliar_expr
    erros, avisos = [], []
    els = list(cfg.get("elementos") or [])
    for chave in ("amostra", "elementos", "sitio", "pasta_dados", "minerais"):
        if not cfg.get(chave):
            erros.append(f"config sem '{chave}'")
    if {"C", "O"} & set(els):
        erros.append("C/O em 'elementos' (não entram na fração de cátions)")
    nomes = [m.get("nome") for m in cfg.get("minerais") or []]
    for n in {n for n in nomes if nomes.count(n) > 1}:
        erros.append(f"mineral '{n}' repetido (o id é a posição na lista)")
    teste = np.linspace(0, 1, 5)
    for i, m in enumerate(cfg.get("minerais") or [], start=1):
        nome = m.get("nome") or f"#{i}"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(m.get("cor", "#888888"))):
            avisos.append(f"{nome}: cor '{m.get('cor')}' não é #rrggbb")
        if m.get("fonte_default") and m["fonte_default"] not in FONTES:
            erros.append(f"{nome}: fonte_default '{m['fonte_default']}' (use {'|'.join(FONTES)})")
        for canal, expr in (m.get("condicoes") or {}).items():
            falta = [e for e in _canais(canal) if e not in els]
            if falta:
                erros.append(f"{nome}: condição '{canal}' usa {falta}, fora de 'elementos'")
            try:
                avaliar_expr(teste, str(expr))
            except Exception:
                erros.append(f"{nome}: condição {canal}: '{expr}' inválida (use '>0.1', '<0.1' ou '0.1 - 0.3')")
        for e in m.get("mapas_seg") or []:
            if e not in els and elementos_disponiveis is not None and e not in elementos_disponiveis:
                erros.append(f"{nome}: mapas_seg usa '{e}', sem mapa na pasta de dados")
        for g in m.get("mapas_grupos") or []:
            for c in g.get("cond") or []:
                onde = f"{nome}/{g.get('nome')}"
                falta = [e for e in _canais(str(c.get("canal", ""))) if e not in els]
                if falta:
                    erros.append(f"{onde}: canal '{c.get('canal')}' usa {falta}, fora de 'elementos'")
                if c.get("op") not in (">", "<"):
                    erros.append(f"{onde}: op '{c.get('op')}' (use '>' ou '<')")
                if c.get("tipo", "raw") not in ("raw", "frac"):
                    erros.append(f"{onde}: tipo '{c.get('tipo')}' (use raw|frac)")
                if ("q" in c) == ("v" in c):
                    erros.append(f"{onde}: cada condição precisa de 'q' (quantil) OU 'v' (valor)")
                elif "q" in c and not 0 <= float(c["q"]) <= 1:
                    erros.append(f"{onde}: q={c['q']} fora de [0, 1]")
        if not (m.get("condicoes") or m.get("mapas_seg") or m.get("mapas_grupos")):
            avisos.append(f"{nome}: sem condicoes/mapas_seg/mapas_grupos (só dá para segmentar à mão ou por cluster)")
    return erros, avisos


def checar_sitio_ativo(r, rapido):
    """-> (cfg, shape dos mapas ou None)."""
    import yaml
    import common
    r.secao("2. Projeto e sítio ativo")
    cfg_p = Path("config/classificacao.yaml")
    if not cfg_p.exists():
        r.erro(f"config/classificacao.yaml não encontrado em {Path.cwd()} — rode na raiz do projeto "
               f"(ou --projeto <pasta>)")
        return None, None
    try:
        cfg = yaml.safe_load(cfg_p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        r.erro(f"config/classificacao.yaml ilegível: {e}")
        return None, None
    r.ok(f"amostra {cfg.get('amostra')} · sítio ATIVO {cfg.get('sitio')} · {len(cfg.get('minerais') or [])} minerais")
    pasta = Path(cfg.get("pasta_dados", ""))
    if not pasta.is_dir():
        r.erro(f"pasta de dados '{pasta}' não existe — copie os mapas do AZtec para ela ou ative um sítio "
               f"que tenha mapas (python scripts/ativar_sitio.py --listar)")
        return cfg, None
    faltam, achados = [], {}
    for el in cfg.get("elementos") or []:
        try:
            achados[el] = common._achar_arquivo(pasta, el)
        except FileNotFoundError:
            faltam.append(el)
    if faltam:
        r.erro(f"sem mapa para {faltam} em {pasta} (tire-os de 'elementos' ou copie os .tif)")
    else:
        r.ok(f"{len(achados)} mapas em {pasta}")
    bse = Path(cfg["bse"]) if cfg.get("bse") else next(iter(sorted(pasta.glob("Electron Image*.tif"))), None)
    if bse is None or not Path(bse).exists():
        r.aviso(f"BSE não encontrada ({cfg.get('bse') or 'Electron Image*.tif'}): relatório e app ficam sem fundo")
    else:
        r.ok(f"BSE {bse}")
    try:
        cfg_px = common.carregar_config(str(cfg_p))
        r.ok(f"pixel {cfg_px.get('pixel_um')} µm/px (config: {cfg.get('pixel_um')}) · area_min "
             f"{cfg_px.get('area_min')} px")
    except Exception as e:  # noqa: BLE001
        r.erro(f"config × TIFF: {e}")
    disponiveis = {m.group(1) for a in pasta.glob("*.tif") if (m := re.match(r"^([A-Z][a-z]?)\s", a.name))}
    r.secao("3. Regras da config")
    erros, avisos = validar_config(cfg, disponiveis)
    for a in avisos:
        r.aviso(a)
    for e in erros:
        r.erro(e)
    if not erros:
        r.ok("condições, fontes e canais coerentes com os elementos")
    shape = None
    if achados and not rapido:
        try:
            inten, _ = common._decodificar(next(iter(achados.values())))
            shape = inten.shape
            r.ok(f"mapas decodificados: {shape[1]}×{shape[0]} px")
        except Exception as e:  # noqa: BLE001
            r.erro(f"não consegui decodificar {next(iter(achados.values()))}: {e}")
    return cfg, shape


def checar_estado(r, cfg, shape):
    import numpy as np
    r.secao("4. estado/ (segmentação do sítio ativo)")
    est = Path("estado")
    rot_p = est / "rotulos.npy"
    if not rot_p.exists():
        r.ok("sem rotulos.npy — sítio sem segmentação ainda (comece por reconhecer.py)")
        return {"rotulos": False, "clusters": (est / "clusters.npy").exists()}
    rot = np.load(rot_p)
    n = len(cfg.get("minerais") or [])
    if shape is not None and rot.shape != shape:
        r.erro(f"rotulos.npy {rot.shape} ≠ mapas {shape}: estado/ é de outro sítio? (ativar_sitio.py --listar)")
    ids = [int(i) for i in np.unique(rot) if i]
    fora = [i for i in ids if i > n]
    if fora:
        r.erro(f"rotulos.npy tem ids {fora} > nº de minerais ({n}) — a config foi reordenada/encurtada?")
    nomes = {i: m.get("nome") for i, m in enumerate(cfg.get("minerais") or [], start=1)}
    r.ok(f"rotulos.npy {rot.shape[1]}×{rot.shape[0]}, {_mil(int((rot > 0).sum()))} px rotulados: "
         + ", ".join(f"{nomes.get(i, i)} {_mil(int((rot == i).sum()))}" for i in ids))
    prog_p = est / "progresso.json"
    if prog_p.exists():
        try:
            prog = json.loads(prog_p.read_text(encoding="utf-8"))
            sem = [p.get("mineral") for p in prog if p.get("id") not in ids]
            if sem:
                r.aviso(f"progresso.json cita {sem} sem pixels em rotulos.npy (removidos depois?)")
        except Exception as e:  # noqa: BLE001
            r.aviso(f"progresso.json ilegível: {e}")
    if not (est / "rotulos_prev.npy").exists():
        r.aviso("sem rotulos_prev.npy (backup de 1 passo) — o próximo commit cria")
    cl_p, clj_p = est / "clusters.npy", est / "clusters.json"
    if cl_p.exists():
        cl = np.load(cl_p)
        info = json.loads(clj_p.read_text(encoding="utf-8")) if clj_p.exists() else {}
        if cl.shape != rot.shape:
            r.erro(f"clusters.npy {cl.shape} ≠ rotulos {rot.shape} — rode reconhecer.py de novo")
        elif info.get("elementos") and info["elementos"] != cfg.get("elementos"):
            r.aviso("clusters.json é de outra lista de elementos — rode reconhecer.py de novo")
        else:
            r.ok(f"clusters.npy: k={int(cl.max())}")
    return {"rotulos": True, "clusters": cl_p.exists()}


def checar_arquivados(r):
    r.secao("5. Sítios arquivados e pacotes")
    sd = Path("sitios")
    for d in sorted(p for p in sd.iterdir() if p.is_dir()) if sd.is_dir() else []:
        info_p = d / "info.json"
        if not info_p.exists():
            r.aviso(f"{d} sem info.json (não aparece no ativar_sitio/app)")
            continue
        info = json.loads(info_p.read_text(encoding="utf-8"))
        s = info.get("sitio", d.name)
        pasta = Path(info.get("pasta_dados", ""))
        tem_cfg = (d / f"classificacao_{s}.yaml").exists()
        tem_rot = (d / "estado" / "rotulos.npy").exists()
        msg = (f"sítio {s}: mapas {'OK' if pasta.is_dir() and any(pasta.glob('*.tif')) else 'FALTAM'} "
               f"({pasta}) · config {'OK' if tem_cfg else 'FALTA'} · rótulos {'OK' if tem_rot else 'não'}")
        (r.ok if tem_cfg else r.aviso)(msg)
    pacotes = sorted(Path("saida/mudmap").glob("*.mudmap")) if Path("saida/mudmap").is_dir() else []
    for arq in pacotes:
        try:
            with zipfile.ZipFile(arq) as z:
                man = json.loads(z.read("manifest.json"))
            r.ok(f"{arq}: {man.get('amostra')} sítio {man.get('sitio')} ({man.get('app')}, {man.get('salvo_em')})")
        except Exception as e:  # noqa: BLE001
            r.erro(f"{arq} ilegível: {e}")
    if not pacotes:
        print("  (nenhum pacote em saida/mudmap/ — gere com exportar_mudmap.py)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projeto", default=None, help="pasta do projeto (default: a pasta atual)")
    ap.add_argument("--rapido", action="store_true", help="não decodifica os mapas")
    args = ap.parse_args()
    try:                                   # console/pipe do Windows (cp1252) não quebra com µ, ×, …
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if args.projeto:
        os.chdir(args.projeto)
    r = Relato()
    print(f"MudMap — diagnóstico de {Path.cwd()}")
    checar_ambiente(r)
    if any(e.endswith("requirements-scripts.txt") for e in r.erros):
        print("\nInstale as dependências e rode de novo.")
        return 1
    cfg, shape = checar_sitio_ativo(r, args.rapido)
    est = checar_estado(r, cfg, shape) if cfg else {}
    if cfg:
        checar_arquivados(r)

    print(f"\nRESUMO: {len(r.erros)} erro(s), {len(r.avisos)} aviso(s)")
    if r.erros:
        print("PRÓXIMO PASSO: corrigir os ERROs acima (o /S_MudMap explica cada item) e rodar de novo.")
    elif not est.get("clusters"):
        print("PRÓXIMO PASSO: python scripts/reconhecer.py  (depois candidatos.py) — seção Fluxo do /S_MudMap")
    elif not est.get("rotulos"):
        print("PRÓXIMO PASSO: python scripts/candidatos.py e escolher o 1º mineral — seção Fluxo do /S_MudMap")
    else:
        print("PRÓXIMO PASSO: ambiente e dados OK — seguir o '▶ PRÓXIMO PASSO' do /S_MudMap (Estado atual)")
    return 1 if r.erros else 0


if __name__ == "__main__":
    sys.exit(main())
