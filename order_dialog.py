# order_dialog.py - Диалог создания заказ-наряда

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
                             QTextEdit, QPushButton, QHBoxLayout, QLabel, QMessageBox)
from PyQt6.QtCore import Qt
from database import ServiceDatabase

class OrderDialog(QDialog):
    def __init__(self, db: ServiceDatabase, client: dict, vehicle: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.client = client
        self.vehicle = vehicle
        self.setWindowTitle("🆕 Новый заказ-наряд")
        self.setMinimumWidth(500)
        self.order_created = False   # флаг успеха
        self.order_id = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Блок информации о клиенте и авто ---
        info_group = QFormLayout()
        info_group.addRow("Клиент:", QLabel(f"<b>{self.client['full_name']}</b>"))
        info_group.addRow("Телефон:", QLabel(self.client.get('phone', '—')))
        info_group.addRow("Автомобиль:", QLabel(f"{self.vehicle.get('brand','')} {self.vehicle.get('model','')}"))
        info_group.addRow("Гос. номер:", QLabel(self.vehicle.get('license_plate','—')))
        info_group.addRow("VIN:", QLabel(self.vehicle['vin']))
        layout.addLayout(info_group)

        # --- Жалоба (обязательное поле) ---
        layout.addWidget(QLabel("<b style='color:#c0392b;'>* Жалоба клиента:</b>"))
        self.complaint_edit = QTextEdit()
        self.complaint_edit.setPlaceholderText("Опишите причину обращения (обязательно)...")
        self.complaint_edit.setMinimumHeight(80)
        layout.addWidget(self.complaint_edit)

        # --- Кнопки ---
        button_box = QHBoxLayout()
        self.btn_create = QPushButton("✅ Создать заказ")
        self.btn_create.clicked.connect(self.create_order)
        self.btn_cancel = QPushButton("❌ Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        button_box.addWidget(self.btn_create)
        button_box.addWidget(self.btn_cancel)
        layout.addLayout(button_box)

        self.setLayout(layout)

    def create_order(self):
        complaint = self.complaint_edit.toPlainText().strip()
        if not complaint:
            QMessageBox.warning(self, "Пустая жалоба", "Пожалуйста, опишите жалобу клиента. Это поле обязательно.")
            self.complaint_edit.setFocus()
            return

        # Блокируем кнопку, чтобы избежать двойного нажатия
        self.btn_create.setEnabled(False)
        self.btn_create.setText("⏳ Создание...")

        try:
            order_id, order_num = self.db.create_order(
                vehicle_id=self.vehicle['id'],
                client_id=self.client['id'],
                complaint=complaint
            )
            self.order_id = order_id
            self.order_created = True
            QMessageBox.information(self, "Успех", 
                f"Заказ-наряд {order_num} успешно создан!")
            self.accept()
        except Exception as e:
            self.btn_create.setEnabled(True)
            self.btn_create.setText("✅ Создать заказ")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать заказ:\n{e}")
