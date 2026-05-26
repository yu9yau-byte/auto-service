from enum import StrEnum


class OrderStatus(StrEnum):
    WAITING = "Ожидание"
    IN_PROGRESS = "В работе"
    WAITING_PARTS = "Ждём запчасти"
    DONE = "Готово"


class PartStatus(StrEnum):
    NEEDS_ORDER = "Требуется заказ"
    ORDERED = "Заказано"
    RECEIVED = "Получено"
    INSTALLED = "Установлено"


ORDER_STATUSES = [status.value for status in OrderStatus]
STATUS_COLORS = {
    OrderStatus.WAITING.value: "#f39c12",
    OrderStatus.IN_PROGRESS.value: "#3498db",
    OrderStatus.WAITING_PARTS.value: "#e74c3c",
    OrderStatus.DONE.value: "#2ecc71",
}

VAT_RATE = 0.20
VAT_MULTIPLIER = 1 + VAT_RATE
CURRENCY = "RSD"


class PaymentStatus(StrEnum):
    UNPAID = "Не оплачено"
    PARTIAL = "Частично"
    PAID = "Оплачено"


class CardField(StrEnum):
    VIN = "VIN номер"
    OWNER = "Владелец"
    BRAND = "Марка (Make)"
    MODEL = "Модель"
    PLATE = "Номер авто"
    COLOR = "Цвет"
    YEAR = "Год выпуска"
