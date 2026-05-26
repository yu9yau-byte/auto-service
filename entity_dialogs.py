from datetime import datetime
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class ClientDialog(QDialog):
    def __init__(self, client=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать клиента" if client else "Добавить клиента")
        self.full_name = QLineEdit((client or {}).get("full_name", ""))
        self.phone = QLineEdit((client or {}).get("phone", ""))
        self.email = QLineEdit((client or {}).get("email", ""))
        self.address = QLineEdit((client or {}).get("address", ""))
        self.notes = QTextEdit((client or {}).get("notes", ""))
        self.notes.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("ФИО*", self.full_name)
        form.addRow("Телефон", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Адрес", self.address)
        form.addRow("Заметки", self.notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "full_name": self.full_name.text().strip(),
            "phone": self.phone.text().strip(),
            "email": self.email.text().strip(),
            "address": self.address.text().strip(),
            "notes": self.notes.toPlainText().strip(),
        }


class VehicleDialog(QDialog):
    def __init__(self, clients, vehicle=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать автомобиль" if vehicle else "Добавить автомобиль")
        vehicle = vehicle or {}
        self.client_combo = QComboBox()
        for client in clients:
            self.client_combo.addItem(client["full_name"], client["id"])
        current_client_id = vehicle.get("client_id")
        if current_client_id:
            index = self.client_combo.findData(current_client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)

        self.vin = QLineEdit(vehicle.get("vin", ""))
        self.brand = QLineEdit(vehicle.get("brand", ""))
        self.model = QLineEdit(vehicle.get("model", ""))
        self.year = QLineEdit(str(vehicle.get("year") or ""))
        self.license_plate = QLineEdit(vehicle.get("license_plate", ""))
        self.color = QLineEdit(vehicle.get("color", ""))

        form = QFormLayout()
        form.addRow("Клиент*", self.client_combo)
        form.addRow("VIN*", self.vin)
        form.addRow("Марка*", self.brand)
        form.addRow("Модель", self.model)
        form.addRow("Год", self.year)
        form.addRow("Номер", self.license_plate)
        form.addRow("Цвет", self.color)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def get_data(self):
        year_text = self.year.text().strip()
        try:
            year = int(year_text)
            if not (1900 <= year <= datetime.now().year + 1):
                year = None
        except ValueError:
            year = None
        return {
            "client_id": self.client_combo.currentData(),
            "vin": self.vin.text().strip(),
            "brand": self.brand.text().strip(),
            "model": self.model.text().strip(),
            "year": year,
            "license_plate": self.license_plate.text().strip(),
            "color": self.color.text().strip(),
        }


class ManualOrderDialog(QDialog):
    """Создание заказа через выбор из существующих клиентов и автомобилей."""

    def __init__(self, clients, vehicles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый заказ — выбор из базы")
        self.vehicles = vehicles
        self.client_combo = QComboBox()
        for client in clients:
            self.client_combo.addItem(client["full_name"], client)

        self.vehicle_combo = QComboBox()
        self.client_combo.currentIndexChanged.connect(self.refresh_vehicles)
        self.refresh_vehicles()

        self.complaint = QTextEdit()
        self.complaint.setPlaceholderText("Опишите жалобу клиента...")
        self.complaint.setMaximumHeight(120)

        form = QFormLayout()
        form.addRow("Клиент", self.client_combo)
        form.addRow("Автомобиль", self.vehicle_combo)
        form.addRow("Жалоба*", self.complaint)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self._update_save_button()

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.button_box)

    def refresh_vehicles(self):
        client = self.client_combo.currentData()
        client_id = client["id"] if client else None
        self.vehicle_combo.clear()
        for vehicle in self.vehicles:
            if vehicle.get("client_id") != client_id:
                continue
            label = (
                f"{vehicle.get('brand', '')} {vehicle.get('model', '')} "
                f"[{vehicle.get('license_plate', '')}]"
            )
            self.vehicle_combo.addItem(label, vehicle)
        self._update_save_button()

    def _update_save_button(self):
        save_btn = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setEnabled(self.vehicle_combo.count() > 0)

    def get_data(self):
        return {
            "client": self.client_combo.currentData(),
            "vehicle": self.vehicle_combo.currentData(),
            "complaint": self.complaint.toPlainText().strip(),
        }


class ManualOrderEntryDialog(QDialog):
    """
    Создание заказа с ручным вводом ВСЕХ данных:
    клиент + автомобиль + жалоба — в одном диалоге.
    Используется когда клиент/авто ещё не в базе.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый заказ — ввод вручную")
        self.setMinimumWidth(500)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Блок: Клиент ---
        client_group = QGroupBox("Клиент")
        client_form = QFormLayout(client_group)
        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText("Иванов Иван Иванович")
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("+381 60 123 4567")
        self.email = QLineEdit()
        self.email.setPlaceholderText("email@example.com")
        self.address = QLineEdit()
        self.notes_client = QLineEdit()
        self.notes_client.setPlaceholderText("Дополнительно...")
        client_form.addRow("ФИО*", self.full_name)
        client_form.addRow("Телефон", self.phone)
        client_form.addRow("Email", self.email)
        client_form.addRow("Адрес", self.address)
        client_form.addRow("Заметки", self.notes_client)
        layout.addWidget(client_group)

        # --- Блок: Автомобиль ---
        vehicle_group = QGroupBox("Автомобиль")
        vehicle_form = QFormLayout(vehicle_group)
        self.vin = QLineEdit()
        self.vin.setPlaceholderText("17 символов VIN")
        self.brand = QLineEdit()
        self.brand.setPlaceholderText("Toyota, BMW, Renault...")
        self.model = QLineEdit()
        self.model.setPlaceholderText("Corolla, X5, Clio...")
        self.year = QLineEdit()
        self.year.setPlaceholderText("2020")
        self.license_plate = QLineEdit()
        self.license_plate.setPlaceholderText("BG 123 AB")
        self.color = QLineEdit()
        self.color.setPlaceholderText("Белый, Чёрный...")
        vehicle_form.addRow("VIN*", self.vin)
        vehicle_form.addRow("Марка*", self.brand)
        vehicle_form.addRow("Модель", self.model)
        vehicle_form.addRow("Год", self.year)
        vehicle_form.addRow("Гос. номер", self.license_plate)
        vehicle_form.addRow("Цвет", self.color)
        layout.addWidget(vehicle_group)

        # --- Блок: Жалоба ---
        complaint_group = QGroupBox("Жалоба клиента *")
        complaint_layout = QVBoxLayout(complaint_group)
        self.complaint = QTextEdit()
        self.complaint.setPlaceholderText("Опишите причину обращения (обязательно)...")
        self.complaint.setMaximumHeight(100)
        complaint_layout.addWidget(self.complaint)
        layout.addWidget(complaint_group)

        # --- Кнопки ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        year_text = self.year.text().strip()
        try:
            year = int(year_text)
            if not (1900 <= year <= datetime.now().year + 1):
                year = None
        except ValueError:
            year = None
        return {
            "full_name": self.full_name.text().strip(),
            "phone": self.phone.text().strip(),
            "email": self.email.text().strip(),
            "address": self.address.text().strip(),
            "notes": self.notes_client.text().strip(),
            "vin": self.vin.text().strip(),
            "brand": self.brand.text().strip(),
            "model": self.model.text().strip(),
            "year": year,
            "license_plate": self.license_plate.text().strip(),
            "color": self.color.text().strip(),
            "complaint": self.complaint.toPlainText().strip(),
        }
