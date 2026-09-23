"""Visual system shared by the main window and settings dialog."""

APP_STYLE = r"""
QMainWindow, QDialog, QWidget#appRoot {
    background: #F3F5FA;
    color: #172033;
}
QToolTip {
    background: #172033;
    color: #FFFFFF;
    border: 0;
    padding: 6px 8px;
}
QLabel#eyebrow {
    color: #6558D3;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel#brandTitle {
    color: #11182A;
    font-size: 24px;
    font-weight: 700;
}
QLabel#brandSubtitle, QLabel#mutedLabel, QLabel#panelCaption {
    color: #707991;
    font-size: 12px;
}
QLabel#panelTitle {
    color: #172033;
    font-size: 15px;
    font-weight: 700;
}
QLabel#statusLabel {
    color: #344056;
    font-weight: 600;
}
QLabel#livePartial {
    color: #788197;
    background: #F7F8FB;
    border: 1px solid #E8EAF1;
    border-radius: 9px;
    padding: 8px 10px;
    font-size: 12px;
}
QLabel#livePartial[state="active"] {
    color: #5146BB;
    background: #F1EFFF;
    border-color: #DCD7FF;
}
QLabel#miniTitle {
    color: #8A92A5;
    font-size: 10px;
    font-weight: 700;
}
QLabel#contextLine {
    color: #626D82;
    font-size: 11px;
    padding: 1px 0;
}
QLabel#preview {
    background: #F1F3F8;
    color: #8A93A6;
    border: 1px dashed #C9CFDB;
    border-radius: 8px;
}
QLabel#warningLabel {
    color: #B3472D;
    background: #FFF1EC;
    border: 1px solid #FFD4C7;
    border-radius: 7px;
    padding: 7px 10px;
}
QFrame#topBar {
    background: transparent;
}
QFrame#softDivider {
    color: #E8EAF1;
    background: #E8EAF1;
    max-height: 1px;
    border: 0;
}
QFrame#contextSurface {
    background: #F7F8FB;
    border: 1px solid #E9EBF2;
    border-radius: 9px;
}
QFrame#actionBar, QFrame#statusBar {
    background: #FFFFFF;
    border: 1px solid #E1E5EE;
    border-radius: 12px;
}
QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E1E5EE;
    border-radius: 12px;
    margin-top: 14px;
    padding: 18px 13px 13px 13px;
    color: #172033;
    font-size: 14px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 5px;
    color: #172033;
    background: #FFFFFF;
}
QGroupBox#statusCard {
    background: #FFFFFF;
    border-color: #E4E7EF;
}
QGroupBox#answerCard {
    background: #FDFCFF;
    border: 1px solid #DCD8F6;
    border-radius: 14px;
}
QGroupBox#answerCard::title {
    color: #5146BB;
    background: #FDFCFF;
}
QGroupBox#transcriptCard {
    border-color: #E5E8F0;
}
QFrame[sourceCard="true"] {
    background: #F7F8FC;
    border: 1px solid #E7EAF1;
    border-radius: 8px;
}
QPushButton {
    min-height: 24px;
    padding: 4px 10px;
    border: 1px solid #D8DDE8;
    border-radius: 7px;
    background: #FFFFFF;
    color: #344056;
    font-weight: 600;
}
QPushButton:hover {
    background: #F6F7FB;
    border-color: #BFC6D6;
}
QPushButton:pressed {
    background: #ECEFF5;
}
QPushButton:disabled {
    color: #AEB5C4;
    background: #F4F5F8;
    border-color: #E8EAF0;
}
QPushButton[role="primary"] {
    color: #FFFFFF;
    background: #6558D3;
    border-color: #6558D3;
}
QPushButton[role="primary"]:hover { background: #584BC7; }
QPushButton[role="accent"] {
    color: #FFFFFF;
    background: #168A80;
    border-color: #168A80;
}
QPushButton[role="accent"]:hover { background: #117A71; }
QPushButton[role="danger"] {
    color: #A44235;
    background: #FFF5F2;
    border-color: #F1C9C1;
}
QPushButton[role="quiet"] {
    background: transparent;
    border-color: transparent;
    color: #626D82;
}
QPushButton[role="soft"] {
    color: #626D82;
    background: #F5F6F9;
    border-color: #E5E8EF;
    border-radius: 9px;
    padding: 4px 11px;
}
QPushButton[role="soft"]:hover {
    color: #3E485E;
    background: #ECEEF4;
    border-color: #D9DDE7;
}
QPushButton[role="focus"] {
    color: #5B50BF;
    background: #F0EEFF;
    border-color: #DDD8FF;
    border-radius: 9px;
    padding: 4px 11px;
}
QPushButton[role="focus"]:hover,
QPushButton[role="focus"]:checked {
    color: #FFFFFF;
    background: #6558D3;
    border-color: #6558D3;
}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser {
    background: #FBFCFE;
    color: #202A3D;
    border: 1px solid #D9DEE9;
    border-radius: 7px;
    padding: 6px 8px;
    selection-background-color: #DCD8FA;
    selection-color: #172033;
}
QTextBrowser#answerBrowser {
    background: #F7F8FC;
    border: 1px solid #E6E8F0;
    border-radius: 10px;
    font-size: 15px;
    padding: 10px 12px;
}
QPlainTextEdit#transcriptEditor {
    background: #F8F9FC;
    border-color: #E3E6EE;
    border-radius: 9px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit:focus, QTextBrowser:focus {
    border: 1px solid #7669DD;
    background: #FFFFFF;
}
QComboBox, QSpinBox { min-height: 27px; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #D9DEE9;
    selection-background-color: #ECE9FF;
    selection-color: #27204C;
    padding: 4px;
}
QCheckBox { color: #465168; spacing: 7px; }
QProgressBar {
    background: #E8EBF2;
    border: 0;
    border-radius: 3px;
}
QProgressBar::chunk {
    background: #27A79A;
    border-radius: 3px;
}
QProgressBar[source="mic"]::chunk { background: #7669DD; }
QProgressBar[source="system"]::chunk { background: #27A79A; }
QScrollArea { background: transparent; border: 0; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #C8CEDA;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 10px; }
QSplitter::handle:vertical {
    height: 8px;
    background: transparent;
    margin: 0;
}
QTabWidget::pane {
    border: 1px solid #E1E5EE;
    border-radius: 10px;
    background: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #707991;
    padding: 10px 15px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: #5146BB;
    border-bottom: 2px solid #6558D3;
}
"""
