"""Exporta os rótulos editados de volta ao pipeline (estado/rotulos.npy), como o napari fazia:
backup do atual em rotulos_prev.npy (regra 7 "Backup/desfazer" do runbook /S_MudMap) e progresso.json atualizado para os
minerais cuja contagem mudou (metodo = "mudmap_studio")."""
import json
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from . import importar


def destino_padrao(am):
    d = (am.origem or {}).get("estado")
    return Path(d) if d and Path(d).is_dir() else None


def sitio_ativo(estado_dir):
    """(sítio ativo do projeto, raiz) acima de estado_dir, ou (None, None)."""
    raiz = importar.raiz_do_projeto(estado_dir)
    if raiz is None:
        return None, None
    cfg = yaml.safe_load((raiz / "config" / "classificacao.yaml").read_text(encoding="utf-8"))
    return str(cfg.get("sitio")), raiz


def comparar(am, estado_dir):
    """Prévia: {nome: (px no estado, px no app)} só dos minerais que mudam."""
    rot_path = Path(estado_dir) / "rotulos.npy"
    antigo = np.load(rot_path) if rot_path.exists() else np.zeros(am.shape, np.int64)
    if antigo.shape != am.shape:
        raise ValueError(f"rotulos.npy do destino tem {antigo.shape}, a amostra {am.shape}.")
    M = max(am.max_id, int(antigo.max(initial=0)), int(am.rotulos.max(initial=0))) + 1
    a = np.bincount(antigo.ravel().astype(np.int64), minlength=M)
    n = np.bincount(am.rotulos.ravel().astype(np.int64), minlength=M)
    out = {}
    for mid in np.nonzero(a != n)[0]:
        if mid == 0:
            continue
        m = am.mineral(int(mid))
        out[m.nome if m else f"id {mid}"] = (int(a[mid]), int(n[mid]))
    difere = int((antigo != am.rotulos).sum())
    return out, difere


def exportar(am, estado_dir):
    estado_dir = Path(estado_dir)
    estado_dir.mkdir(parents=True, exist_ok=True)
    rot_path = estado_dir / "rotulos.npy"
    mudancas, difere = comparar(am, estado_dir)
    if rot_path.exists():
        np.save(estado_dir / "rotulos_prev.npy", np.load(rot_path))
    np.save(rot_path, am.rotulos.astype(np.int64))           # o pipeline grava int64
    prog_path = estado_dir / "progresso.json"
    prog = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else []
    ids = {m.nome: m.id for m in am.minerais}
    hoje = str(date.today())
    for nome, (_antes, depois) in mudancas.items():
        mid = ids.get(nome)
        prog = [p for p in prog if p.get("id") != mid]
        if depois > 0 and mid is not None:
            prog.append({"id": mid, "mineral": nome, "metodo": "mudmap_studio", "data": hoje})
    prog.sort(key=lambda p: p.get("id", 0))
    prog_path.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"destino": str(rot_path), "backup": rot_path.with_name("rotulos_prev.npy").exists(),
            "mudancas": mudancas, "px_diferentes": difere}
