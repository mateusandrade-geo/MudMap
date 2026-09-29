"""Ícones de traço (SVG 24x24) desenhados para o app, recoloridos pelo tema."""
from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_P = {
    "inspetor": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4 20.5 20.5"/>'
                '<circle cx="10.5" cy="10.5" r="2.2"/>',
    "edicao": '<path d="M14.5 5.5 18.5 9.5"/><path d="M4 20l1.2-4.6L16.2 4.4a1.9 1.9 0 0 1 2.7 0l.7.7'
              'a1.9 1.9 0 0 1 0 2.7L8.6 18.8z"/>',
    "segmentar": '<path d="M4 20 15 9"/><path d="M13.5 7.5 16.5 10.5"/><path d="M17 3v3M15.5 4.5h3'
                 'M20 9v2M19 10h2M10 4v1.6M9.2 4.8h1.6"/>',
    "relatorio": '<path d="M4 20h16"/><path d="M7 16v-4M12 16V7M17 16v-7"/>',
    "abrir": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2h7.2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "importar": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2h7.2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'
                '<path d="M12 10.5v5M9.8 13.4 12 15.6l2.2-2.2"/>',
    "salvar": '<path d="M5.5 4h10.2L19.5 7.8V19a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/>'
              '<path d="M8 4v4.5h6.5V4"/><rect x="8" y="13" width="8" height="7"/>',
    "mao": '<path d="M12 3v18M3 12h18"/><path d="M9.7 5.3 12 3l2.3 2.3M9.7 18.7 12 21l2.3-2.3'
           'M5.3 9.7 3 12l2.3 2.3M18.7 9.7 21 12l-2.3 2.3"/>',
    "regua": '<path d="M3.8 16.2 16.2 3.8l4 4L7.8 20.2z"/><path d="M7.2 12.8l1.8 1.8M10 10l1.8 1.8'
             'M12.8 7.2l1.8 1.8"/>',
    "ajustar": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "tabela": '<rect x="3.5" y="4.5" width="17" height="15" rx="1.8"/><path d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10"/>',
    "comparar": '<rect x="3" y="5.5" width="10" height="13" rx="1.6"/><rect x="11" y="5.5" width="10" height="13" rx="1.6"/>',
    "camadas": '<path d="M12 4 3.5 8.5 12 13l8.5-4.5z"/><path d="M3.5 12.5 12 17l8.5-4.5M3.5 16 12 20.5l8.5-4.5"/>',
    "fechar": '<path d="M6 6l12 12M18 6 6 18"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.4"/>',
    "alvo": '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3"/>',
    "pincel": '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="1.2"/>',
    "borracha": '<path d="M8.5 19.5h11"/><path d="M4.6 14.8 13.8 5.6a2 2 0 0 1 2.8 0l2.8 2.8a2 2 0 0 1 0 2.8'
                'l-7.7 7.7a2 2 0 0 1-1.4.6H8.2l-3.6-3.6a1.2 1.2 0 0 1 0-1.1z"/><path d="M9.2 10.2l5.6 5.6"/>',
    "balde": '<path d="M5 11.5 11.5 5l7 7-6.5 6.5a1.5 1.5 0 0 1-2.1 0L5 13.6a1.5 1.5 0 0 1 0-2.1z"/>'
             '<path d="M5.2 12h13.3"/><path d="M19.5 15.5s1.6 2.1 1.6 3.1a1.6 1.6 0 0 1-3.2 0c0-1 1.6-3.1 1.6-3.1z"/>',
    "contagotas": '<path d="M13.8 6.2 17.8 10.2"/><path d="M15 4.8a2.4 2.4 0 0 1 3.4 0l.8.8a2.4 2.4 0 0 1 0 3.4'
                  'l-1.4 1.4-4.2-4.2z"/><path d="M13.2 8.6 5.8 16l-.9 3.1 3.1-.9 7.4-7.4"/>',
    "remover": '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.9 12.2a1 1 0 0 0 1 .8h7.2a1 1 0 0 0 1-.8L17.5 7"/>'
               '<path d="M10.2 10.5v6M13.8 10.5v6"/>',
    "retangulo": '<rect x="4" y="6" width="16" height="12" rx="1.2"/>',
    "elipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6"/>',
    "poligono": '<path d="M12 3.8 20 9.6 16.9 19.5H7.1L4 9.6z"/><circle cx="12" cy="3.8" r="1.2"/>'
                '<circle cx="20" cy="9.6" r="1.2"/><circle cx="16.9" cy="19.5" r="1.2"/>'
                '<circle cx="7.1" cy="19.5" r="1.2"/><circle cx="4" cy="9.6" r="1.2"/>',
    "laco": '<path d="M7.5 17.5c-3-1.2-4.5-3.3-4-5.8C4.2 7.4 9.2 4.6 14 5.2c4.5.6 7.2 3.6 6.2 7'
            '-.9 3.2-5 5.2-9.6 5.1"/><path d="M7.5 17.5c-.4 1.6.4 2.9 2 3.2"/><circle cx="8.6" cy="16.3" r="1.5"/>',
    "pontos": '<circle cx="6" cy="7" r="1.8"/><circle cx="17" cy="5.5" r="1.8"/><circle cx="19" cy="15" r="1.8"/>'
              '<circle cx="9" cy="18" r="1.8"/><circle cx="12" cy="11.5" r="1.8"/>',
    "desfazer": '<path d="M9 7 4.5 11.5 9 16"/><path d="M4.5 11.5h10a5 5 0 0 1 0 10h-2"/>',
    "refazer": '<path d="M15 7l4.5 4.5L15 16"/><path d="M19.5 11.5h-10a5 5 0 0 0 0 10h2"/>',
    "propagar": '<circle cx="7" cy="12" r="3"/><circle cx="17.5" cy="6.5" r="2.2"/><circle cx="17.5" cy="17.5" r="2.2"/>'
                '<path d="M9.7 10.6 15.4 7.6M9.7 13.4l5.7 3"/>',
    "exportar": '<path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v5.5a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5V13"/>',
    "limpar": '<path d="M4 20h16"/><path d="M14.5 4.5l5 5-8.5 8.5H6v-5z"/>',
}


def svg(nome, cor="#a5abb2", largura=1.7):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{cor}" stroke-width="{largura}" stroke-linecap="round" '
            f'stroke-linejoin="round">{_P[nome]}</svg>')


def pixmap(nome, cor="#a5abb2", tam=20, escala=2):
    r = QSvgRenderer(QByteArray(svg(nome, cor).encode()))
    pm = QPixmap(tam * escala, tam * escala)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, tam * escala, tam * escala))
    p.end()
    pm.setDevicePixelRatio(escala)
    return pm


def icone(nome, cor="#a5abb2", cor_ativa="#63c99c", cor_off="#6f767e", tam=20):
    ic = QIcon()
    ic.addPixmap(pixmap(nome, cor, tam), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(nome, cor_ativa, tam), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(nome, "#e7e9eb", tam), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(pixmap(nome, cor_ativa, tam), QIcon.Mode.Active, QIcon.State.On)
    ic.addPixmap(pixmap(nome, cor_off, tam), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic
