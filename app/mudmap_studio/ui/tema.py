"""Tema escuro (padrão de software de imagem) — paleta Qt + folha de estilo."""
from PyQt6.QtGui import QColor, QFont, QPalette

C = {
    "fundo": "#15171a",
    "painel": "#1c1f23",
    "painel2": "#23272c",
    "painel3": "#2b3036",
    "borda": "#30353b",
    "borda2": "#41474f",
    "texto": "#e7e9eb",
    "texto2": "#a5abb2",
    "mudo": "#6f767e",
    "acento": "#4fb58a",
    "acento_forte": "#63c99c",
    "acento_suave": "rgba(79, 181, 138, 0.18)",   # QSS: #RRGGBBAA não existe (Qt lê #AARRGGBB)
    "selA": "#ffcc3f",       # grão A (fixado)
    "selB": "#3fc8ff",       # grão B (comparação)
    "perigo": "#e5534b",
    "aviso": "#d9a441",
}
# classes granulométricas (Wentworth): argila, silte, areia
CORES_WENTWORTH = ("#6b9de8", "#e8c36b", "#e8846b")

FONTE_UI = "Segoe UI"


def fonte_mono(pt=9):
    f = QFont("Consolas", pt)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


QSS = f"""
* {{ font-family: "{FONTE_UI}"; font-size: 9.5pt; color: {C['texto']}; }}
QMainWindow, QDialog {{ background: {C['fundo']}; }}
QWidget#painel, QWidget#barraModos {{ background: {C['painel']}; }}
QWidget#barraModos {{ border-right: 1px solid {C['borda']}; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolBar {{ background: {C['painel']}; border: 0; border-bottom: 1px solid {C['borda']};
    spacing: 4px; padding: 4px 6px; }}
QToolBar::separator {{ background: {C['borda']}; width: 1px; margin: 4px 6px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 4px 8px; color: {C['texto2']}; }}
QToolButton:hover {{ background: {C['painel3']}; color: {C['texto']}; }}
QToolButton:checked {{ background: {C['acento_suave']}; border-color: {C['acento']}; color: {C['acento_forte']}; }}
QToolButton:disabled {{ color: {C['mudo']}; }}
QToolButton#modo {{ padding: 6px; border-radius: 8px; }}
QPushButton {{ background: {C['painel2']}; border: 1px solid {C['borda2']}; border-radius: 6px;
    padding: 5px 12px; }}
QPushButton:hover {{ background: {C['painel3']}; border-color: {C['mudo']}; }}
QPushButton:pressed {{ background: {C['borda']}; }}
QPushButton:checked {{ background: {C['acento_suave']}; border-color: {C['acento']}; color: {C['acento_forte']}; }}
QPushButton#primario {{ background: {C['acento']}; border-color: {C['acento']}; color: #0d1a14; font-weight: 600; }}
QPushButton#primario:hover {{ background: {C['acento_forte']}; }}
QPushButton#seg {{ border-radius: 0; padding: 3px 10px; font-size: 8.5pt; }}
QPushButton#segE {{ border-top-right-radius: 0; border-bottom-right-radius: 0; padding: 3px 10px; font-size: 8.5pt; }}
QPushButton#segD {{ border-top-left-radius: 0; border-bottom-left-radius: 0; padding: 3px 10px; font-size: 8.5pt; border-left: 0; }}
QPushButton#segM {{ border-radius: 0; border-left: 0; padding: 3px 10px; font-size: 8.5pt; }}
QPushButton#mini {{ padding: 0; border-radius: 4px; font-size: 9pt; font-weight: 600; }}
QToolButton#secao {{ border: 0; padding: 4px 0; color: {C['texto2']}; font-size: 8pt; font-weight: 600; }}
QToolButton#secao:hover, QToolButton#secao:checked {{ color: {C['texto']}; background: transparent; border: 0; }}
QLabel#erro {{ color: {C['perigo']}; font-size: 8.5pt; }}
QComboBox {{ background: {C['painel2']}; border: 1px solid {C['borda2']}; border-radius: 6px; padding: 3px 8px; }}
QComboBox:hover {{ border-color: {C['mudo']}; }}
QComboBox QAbstractItemView {{ background: {C['painel2']}; border: 1px solid {C['borda2']};
    selection-background-color: {C['acento_suave']}; selection-color: {C['texto']}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {C['painel2']}; border: 1px solid {C['borda2']};
    border-radius: 6px; padding: 3px 6px; selection-background-color: {C['acento']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C['acento']}; }}
QCheckBox {{ spacing: 7px; color: {C['texto2']}; }}
QCheckBox:hover {{ color: {C['texto']}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {C['borda2']};
    background: {C['painel2']}; }}
QCheckBox::indicator:checked {{ background: {C['acento']}; border-color: {C['acento']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {C['painel3']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {C['acento']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {C['texto']}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QLabel#titulo {{ font-size: 13pt; font-weight: 600; }}
QLabel#secao {{ color: {C['mudo']}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; padding-top: 6px; }}
QLabel#mudo {{ color: {C['mudo']}; }}
QLabel#texto2 {{ color: {C['texto2']}; }}
QLabel#pill {{ background: {C['painel3']}; color: {C['texto2']}; border-radius: 9px; padding: 1px 8px; font-size: 8pt; }}
QLabel#pillAcento {{ background: {C['acento_suave']}; color: {C['acento_forte']}; border-radius: 9px; padding: 1px 8px; font-size: 8pt; }}
QLabel#pillAviso {{ background: rgba(217, 164, 65, 0.15); color: {C['aviso']}; border-radius: 9px; padding: 1px 8px; font-size: 8pt; }}
QLabel#pillModo {{ background: {C['acento_suave']}; color: {C['acento_forte']}; border-radius: 10px; padding: 2px 10px; font-weight: 600; }}
QFrame#cartao {{ background: {C['painel2']}; border-radius: 8px; }}
QFrame#linha {{ background: {C['borda']}; max-height: 1px; min-height: 1px; border: 0; }}
QTableView {{ background: {C['painel']}; alternate-background-color: {C['painel2']}; border: 0;
    gridline-color: transparent; selection-background-color: {C['acento_suave']}; selection-color: {C['texto']}; }}
QTableView::item {{ padding: 2px 6px; }}
QHeaderView::section {{ background: {C['painel2']}; color: {C['texto2']}; border: 0;
    border-right: 1px solid {C['borda']}; border-bottom: 1px solid {C['borda']}; padding: 4px 6px; font-size: 8.5pt; }}
QTableCornerButton::section {{ background: {C['painel2']}; border: 0; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C['borda2']}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {C['borda2']}; border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {C['borda']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {C['painel']}; border-top: 1px solid {C['borda']}; color: {C['texto2']}; }}
QStatusBar QLabel {{ color: {C['texto2']}; padding: 0 6px; }}
QProgressBar {{ background: {C['painel3']}; border: 0; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {C['acento']}; border-radius: 3px; }}
QListWidget {{ background: {C['painel']}; border: 1px solid {C['borda']}; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {C['painel3']}; }}
QListWidget::item:selected {{ background: {C['acento_suave']}; color: {C['texto']}; }}
QMenu {{ background: {C['painel2']}; border: 1px solid {C['borda2']}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C['acento_suave']}; }}
QToolTip {{ background: {C['painel3']}; color: {C['texto']}; border: 1px solid {C['borda2']}; padding: 4px 6px; }}
QMessageBox QLabel {{ color: {C['texto']}; }}
"""


def aplicar(app):
    app.setStyle("Fusion")
    p = QPalette()
    cor = lambda k: QColor(C[k])
    p.setColor(QPalette.ColorRole.Window, cor("fundo"))
    p.setColor(QPalette.ColorRole.WindowText, cor("texto"))
    p.setColor(QPalette.ColorRole.Base, cor("painel"))
    p.setColor(QPalette.ColorRole.AlternateBase, cor("painel2"))
    p.setColor(QPalette.ColorRole.Text, cor("texto"))
    p.setColor(QPalette.ColorRole.Button, cor("painel2"))
    p.setColor(QPalette.ColorRole.ButtonText, cor("texto"))
    p.setColor(QPalette.ColorRole.Highlight, cor("acento"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#0d1a14"))
    p.setColor(QPalette.ColorRole.ToolTipBase, cor("painel3"))
    p.setColor(QPalette.ColorRole.ToolTipText, cor("texto"))
    p.setColor(QPalette.ColorRole.PlaceholderText, cor("mudo"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, cor("mudo"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, cor("mudo"))
    app.setPalette(p)
    app.setStyleSheet(QSS)
