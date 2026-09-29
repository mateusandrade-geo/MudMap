"""Mapas de cores (LUT 256x3) sem matplotlib, cores padrão dos elementos e dos clusters."""
import numpy as np

_PARADAS = {
    "viridis": ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725"],
    "magma": ["#000004", "#1c1044", "#4f127b", "#812581", "#b5367a", "#e55064", "#fb8761", "#fec287", "#fcfdbf"],
    "cinza": ["#000000", "#ffffff"],
    "divergente": ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"],
}
NOMES_CMAP = {"viridis": "Viridis", "magma": "Magma", "cinza": "Cinza", "divergente": "Divergente (azul–vermelho)"}

# cores aditivas por elemento (estilo napari: canais puros e distintos)
COR_ELEMENTO = {
    "Si": "#3d7dff", "Al": "#35d0ff", "Fe": "#ff3b30", "Mg": "#2ee86b", "K": "#ff4fd8",
    "Ca": "#ffd23f", "Ti": "#ff8c1a", "S": "#f2f2f2", "Na": "#b28cff",
}
EXTRAS = ["#9be15d", "#ff9f80", "#80b3ff", "#e0b0ff", "#c0c0c0"]
CORES_RGB = ("#ff0000", "#00ff00", "#0000ff")

# clusters k-means (qualitativa, 12 cores)
CORES_CLUSTER = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
                 "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d37295"]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lut(nome):
    """LUT (256, 3) uint8 por interpolação linear das paradas."""
    paradas = np.array([hex_rgb(c) for c in _PARADAS.get(nome, _PARADAS["viridis"])], float)
    x = np.linspace(0, 1, len(paradas))
    t = np.linspace(0, 1, 256)
    return np.stack([np.interp(t, x, paradas[:, k]) for k in range(3)], 1).round().astype(np.uint8)


def cor_elemento(el, i=0):
    return COR_ELEMENTO.get(el, EXTRAS[i % len(EXTRAS)])
