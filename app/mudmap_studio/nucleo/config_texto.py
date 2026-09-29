"""Grava os parâmetros de UM mineral na config YAML preservando todo o resto do texto
(comentários de calibração, ordem, outros minerais).

Só as chaves de regra (CHAVES_REGRA) do bloco "  - nome: <mineral>" são reescritas; nome, cor,
feldspato e as linhas de comentário ficam. O resultado é VERIFICADO com yaml.safe_load: as
chaves de regra do mineral têm de sair iguais às pedidas e todo o resto da config igual ao
original — senão nada é gravado.
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from .pipeline import common
from .segmentacao import CHAVES_REGRA

IND = "    "        # chaves do mineral (4 espaços), como na config do projeto


def _escalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return format(v, "g")
    s = str(v)
    return s if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s) and s not in ("true", "false", "null") \
        else json.dumps(s, ensure_ascii=False)


def _fluxo(d):
    if isinstance(d, dict):
        return "{ " + ", ".join(f"{k}: {_fluxo(v)}" for k, v in d.items()) + " }"
    if isinstance(d, list):
        return "[" + ", ".join(_fluxo(v) for v in d) + "]"
    return _escalar(d)


def _presente(params, k):
    return k in params and (params[k] not in (None, [], {}) or k == "condicoes")


def _linhas_cond_antigas(linhas):
    """Linhas '- { ... }  # comentário' antigas indexadas pelo dict que representam."""
    out = []
    for l in linhas:
        s = l.strip()
        if s.startswith("- {"):
            try:
                out.append((yaml.safe_load(s[1:].split("#")[0].strip()), l))
            except yaml.YAMLError:
                pass
    return out


def _comentario(linha):
    """Comentário de fim de linha (depois do valor), ou ''."""
    corpo = linha.rstrip()
    fecho = max(corpo.rfind("}"), corpo.rfind("]"))
    resto = corpo[fecho + 1:] if fecho >= 0 else corpo.split(":", 1)[-1]
    i = resto.find("#")
    return resto[i:].strip() if i >= 0 else ""


def serializar_chave(k, v, antigas=()):
    """Linhas YAML de UMA chave de regra. Em mapas_grupos, cada condição igual a uma antiga
    reaproveita a linha original; uma condição ALTERADA herda o comentário da linha que ocupava
    a mesma posição. Chave de 1 linha alterada herda o comentário da linha antiga."""
    if k == "mapas_grupos":
        antigas_c = _linhas_cond_antigas(antigas)
        usadas, pos = set(), 0
        out = [f"{IND}mapas_grupos:"]
        for g in v:
            out.append(f"{IND}  - nome: {_escalar(g.get('nome', 'grupo'))}")
            for kr in ("suavizar", "suavizar_um"):
                if kr in g:
                    out.append(f"{IND}    {kr}: {_escalar(g[kr])}")
            out.append(f"{IND}    cond:")
            for c in g.get("cond", []):
                i = next((j for j, (d, _l) in enumerate(antigas_c) if j not in usadas and d == c), None)
                if i is not None:
                    usadas.add(i)
                    out.append(antigas_c[i][1])
                else:
                    linha = f"{IND}      - {_fluxo(c)}"
                    if pos < len(antigas_c) and pos not in usadas:
                        usadas.add(pos)
                        com = _comentario(antigas_c[pos][1])
                        linha += f"   {com}" if com else ""
                    out.append(linha)
                pos += 1
        return out
    linha = f"{IND}{k}: {_fluxo(v)}" if isinstance(v, (dict, list)) else f"{IND}{k}: {_escalar(v)}"
    if len(antigas) == 1 and _comentario(antigas[0]):
        linha += f"   {_comentario(antigas[0])}"
    return [linha]


def _bloco(linhas, nome):
    ini = next((i for i, l in enumerate(linhas) if re.match(rf"^  - nome:\s*{re.escape(nome)}\s*(#.*)?$", l)), None)
    if ini is None:
        raise ValueError(f"Mineral '{nome}' não encontrado na config.")
    fim = ini + 1
    while fim < len(linhas) and not re.match(r"^(  - |\S)", linhas[fim]):
        fim += 1
    return ini, fim


def substituir(texto, nome, params, pixel_um=None):
    """-> (novo texto, bloco antigo, bloco novo). Chave inalterada mantém as linhas originais;
    chave alterada é reescrita no MESMO lugar; chave removida sai; chave nova entra após a
    última chave de regra. Config em µm: os tamanhos editados em px voltam a µm pelo
    pixel_um da amostra (senão o da config). Levanta ValueError se a verificação falhar."""
    linhas = texto.split("\n")
    ini, fim = _bloco(linhas, nome)
    bloco = linhas[ini:fim]
    cfg = yaml.safe_load(texto)
    antigo = next(m for m in cfg["minerais"] if m["nome"] == nome)
    if common.em_um(cfg):
        params = common.para_um(params, antigo, pixel_um or cfg.get("pixel_um"))
    novas, i, ult = [bloco[0]], 1, None
    vistas = set()
    while i < len(bloco):
        l = bloco[i]
        m = re.match(rf"^{IND}([A-Za-z_]+):", l)
        if m and m.group(1) in CHAVES_REGRA:
            k = m.group(1)
            j = i + 1
            while j < len(bloco) and (not bloco[j].strip() or
                                      (len(bloco[j]) - len(bloco[j].lstrip()) > len(IND)
                                       and not bloco[j].lstrip().startswith("#"))):
                j += 1
            span = bloco[i:j]
            while span and not span[-1].strip():          # linhas vazias finais não pertencem à chave
                span.pop()
                j -= 1
            vistas.add(k)
            if _presente(params, k):
                igual = _norm(params[k]) == _norm(antigo.get(k))
                novas += span if igual else serializar_chave(k, params[k], span)
                ult = len(novas)
            i = j
            continue
        novas.append(l)
        i += 1
    extras = [k for k in CHAVES_REGRA if _presente(params, k) and k not in vistas]
    if extras:
        pos = ult
        if pos is None:                                   # sem chaves de regra: antes das vazias finais
            pos = len(novas)
            while pos > 1 and not novas[pos - 1].strip():
                pos -= 1
        novas[pos:pos] = sum((serializar_chave(k, params[k]) for k in extras), [])
    novo = "\n".join(linhas[:ini] + novas + linhas[fim:])
    _verificar(texto, novo, nome, params)
    return novo, "\n".join(bloco).rstrip(), "\n".join(novas).rstrip()


def _verificar(antigo, novo, nome, params):
    a, b = yaml.safe_load(antigo), yaml.safe_load(novo)
    ma = next(m for m in a["minerais"] if m["nome"] == nome)
    mb = next(m for m in b["minerais"] if m["nome"] == nome)
    esperado = {k: params[k] for k in CHAVES_REGRA if _presente(params, k)}
    obtido = {k: mb[k] for k in CHAVES_REGRA if k in mb}
    if _norm(esperado) != _norm(obtido):
        raise ValueError(f"Verificação falhou: {obtido} ≠ {esperado}")
    if {k: v for k, v in ma.items() if k not in CHAVES_REGRA} != {k: v for k, v in mb.items() if k not in CHAVES_REGRA}:
        raise ValueError("Verificação falhou: campos fora da regra mudaram.")
    a2 = {k: v for k, v in a.items() if k != "minerais"}
    b2 = {k: v for k, v in b.items() if k != "minerais"}
    outros_a = [m for m in a["minerais"] if m["nome"] != nome]
    outros_b = [m for m in b["minerais"] if m["nome"] != nome]
    if a2 != b2 or outros_a != outros_b or [m["nome"] for m in a["minerais"]] != [m["nome"] for m in b["minerais"]]:
        raise ValueError("Verificação falhou: outras partes da config mudaram.")


def _norm(x):
    return json.loads(json.dumps(x, sort_keys=True, default=str))


def gravar_arquivo(caminho, nome, params, pixel_um=None):
    """Grava no arquivo com backup <arquivo>.bak_<data>. -> (caminho do backup, bloco antigo, novo)."""
    caminho = Path(caminho)
    texto = caminho.read_text(encoding="utf-8")
    novo, antigo_b, novo_b = substituir(texto, nome, params, pixel_um)
    bak = caminho.with_name(caminho.name + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(caminho, bak)
    caminho.write_text(novo, encoding="utf-8")
    return bak, antigo_b, novo_b
