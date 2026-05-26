"""Диалог выбора способа создания заказ-наряда."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class NewOrderChoiceDialog(QDialog):
    """
    Диалог выбора способа создания заказ-наряда.
    Предлагает два варианта: загрузка с карты техпаспорта или ввод вручную.
    """
    CHOICE_CARD = "card"
    CHOICE_MANUAL = "manual"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый заказ-наряд")
        self.setMinimumWidth(380)
        self.choice = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 20)

        title = QLabel("Как создать заказ-наряд?")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #4a3321; margin-bottom: 6px;")
        layout.addWidget(title)

        subtitle = QLabel("Выберите способ заполнения данных о клиенте и автомобиле")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7f6e5d; font-size: 12px;")
        layout.addWidget(subtitle)

        # --- Кнопка: карта ---
        btn_card = QPushButton("💳  Загрузить с карты техпаспорта")
        btn_card.setMinimumHeight(65)
        btn_card.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_card.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #4e9fdf, stop:1 #2980b9);
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #5aaee8, stop:1 #3498db);
            }
            QPushButton:pressed {
                background-color: #1a6fa8;
                padding-top: 2px;
            }
        """)
        btn_card.clicked.connect(lambda: self._select(self.CHOICE_CARD))
        layout.addWidget(btn_card)

        lbl_card_hint = QLabel("Вставьте смарт-карту в считыватель — данные заполнятся автоматически")
        lbl_card_hint.setWordWrap(True)
        lbl_card_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_card_hint.setStyleSheet("color: #8a7c6e; font-size: 11px; margin-bottom: 4px;")
        layout.addWidget(lbl_card_hint)

        # --- Кнопка: вручную ---
        btn_manual = QPushButton("✏️  Ввести данные вручную")
        btn_manual.setMinimumHeight(65)
        btn_manual.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_manual.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #48b37e, stop:1 #27ae60);
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #55c48d, stop:1 #2ecc71);
            }
            QPushButton:pressed {
                background-color: #1e8449;
                padding-top: 2px;
            }
        """)
        btn_manual.clicked.connect(lambda: self._select(self.CHOICE_MANUAL))
        layout.addWidget(btn_manual)

        lbl_manual_hint = QLabel("Введите данные клиента, автомобиля и жалобу вручную")
        lbl_manual_hint.setWordWrap(True)
        lbl_manual_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_manual_hint.setStyleSheet("color: #8a7c6e; font-size: 11px; margin-bottom: 4px;")
        layout.addWidget(lbl_manual_hint)

        # --- Кнопка отмены ---
        btn_cancel = QPushButton("Отмена")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #95a5a6;
                border: 1px solid #bdc3c7;
                border-radius: 8px;
                padding: 6px;
                font-weight: normal;
                min-height: 28px;
            }
            QPushButton:hover { color: #7f8c8d; background-color: #f5f0eb; }
        """)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _select(self, choice):
        self.choice = choice
        self.accept()

    def get_choice(self):
        return self.choice
