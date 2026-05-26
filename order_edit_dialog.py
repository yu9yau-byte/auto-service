# order_edit_dialog.py - Редактор заказ-наряда (запчасти + услуги, поиск, автоширина)

import csv
import io
import logging
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QComboBox, QLabel,
                             QMessageBox, QHeaderView, QAbstractItemView,
                             QAbstractItemDelegate, QStyledItemDelegate, QApplication,
                             QTabWidget, QWidget, QGridLayout, QInputDialog, QLineEdit, QFileDialog,
                             QTextEdit, QFormLayout, QSizePolicy)
from PyQt6.QtCore import Qt, QEvent, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QBrush, QFont, QDoubleValidator, QKeyEvent
from constants import CURRENCY, VAT_RATE, VAT_MULTIPLIER
from database import ServiceDatabase

logger = logging.getLogger(__name__)


class PaymentLineEdit(QLineEdit):
    """QLineEdit для ввода платежа, которая перехватывает Enter и не распространяет его далее"""
    returnPressed = pyqtSignal()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()
            event.accept()  # Поглощаем событие, не распространяем дальше
        else:
            super().keyPressEvent(event)


class EnterNavigableTable(QTableWidget):
    """QTableWidget, в котором Enter переводит фокус на следующую ячейку."""
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                row = index.row()
                col = index.column() + 1
                if col >= self.columnCount():
                    col = 0
                    row += 1
                if row >= self.rowCount():
                    self.insertRow(self.rowCount())

                self.setCurrentCell(row, col)
                next_item = self.item(row, col)
                if next_item is None:
                    next_item = QTableWidgetItem("")
                    self.setItem(row, col, next_item)
                if next_item.flags() & Qt.ItemFlag.ItemIsEditable:
                    self.editItem(next_item)
                return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        try:
            super().focusInEvent(event)
            if self.state() != QAbstractItemView.EditState.EditingState:
                index = self.currentIndex()
                if index.isValid():
                    item = self.item(index.row(), index.column())
                    if item and item.flags() & Qt.ItemFlag.ItemIsEditable:
                        try:
                            # defer and only edit if the table actually has focus to avoid races
                            QTimer.singleShot(50, lambda it=item, t=self: t.editItem(it) if t.hasFocus() else None)
                        except Exception:
                            logger.exception('Failed to schedule edit on focusInEvent')
        except Exception:
            logger.exception('Error in EnterNavigableTable.focusInEvent')


def parse_number(text: str) -> float:
    """Безопасно преобразует строку в число, понимая разные форматы."""
    if not text or not isinstance(text, str):
        return 0.0
    text = text.strip().replace('\u00A0', ' ').replace(' ', '')
    if not text:
        return 0.0
    text = text.replace('RSD', '').replace('rsd', '').replace('дин', '').replace('€', '').replace('$', '')
    if ',' in text and '.' not in text:
        if text.count(',') == 1 and len(text.split(',')[1]) <= 2:
            text = text.replace(',', '.')
        else:
            text = text.replace(',', '')
    elif ',' in text and '.' in text:
        last_dot = text.rfind('.')
        last_comma = text.rfind(',')
        if last_comma > last_dot:
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    try:
        return float(text)
    except ValueError:
        return 0.0


class SupplierDelegate(QStyledItemDelegate):
    def __init__(self, suppliers, parent=None):
        super().__init__(parent)
        self.suppliers = [""] + [s['name'] for s in suppliers]

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self.suppliers)
        combo.setEditable(True)
        return combo

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.EditRole)
        if value:
            idx = editor.findText(value)
            if idx >= 0:
                editor.setCurrentIndex(idx)
            else:
                editor.setCurrentText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip(), Qt.ItemDataRole.EditRole)


class PaymentEditDialog(QDialog):
    def __init__(self, amount: float, note: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование платежа")
        self.setModal(True)
        self.resize(360, 140)

        self.amount_input = QLineEdit(f"{amount:.2f}")
        self.amount_input.setValidator(QDoubleValidator(0.0, 10000000.0, 2, self.amount_input))
        self.note_input = QLineEdit(note or '')

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Сумма платежа:", self.amount_input)
        form.addRow("Примечание:", self.note_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Отмена")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(btn_ok)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)

    def get_values(self):
        return parse_number(self.amount_input.text()), self.note_input.text().strip()


class PaymentHistoryDialog(QDialog):
    def __init__(self, db, order_id, client_id, refresh_callback=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.order_id = order_id
        self.client_id = client_id
        self.refresh_callback = refresh_callback
        self.setWindowTitle("История платежей")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Дата", "Сумма", "Применено", "Кредит", "Примечание"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        controls = QHBoxLayout()
        self.btn_edit = QPushButton("Редактировать")
        self.btn_delete = QPushButton("Удалить")
        self.btn_reset_balance = QPushButton("Сбросить баланс клиента")
        self.btn_close = QPushButton("Закрыть")
        controls.addWidget(self.btn_edit)
        controls.addWidget(self.btn_delete)
        controls.addWidget(self.btn_reset_balance)
        controls.addStretch()
        controls.addWidget(self.btn_close)
        layout.addLayout(controls)

        self.btn_edit.clicked.connect(self.edit_payment)
        self.btn_delete.clicked.connect(self.delete_payment)
        self.btn_reset_balance.clicked.connect(self.reset_balance)
        self.btn_close.clicked.connect(self.accept)

        self.load_payments()

    def load_payments(self):
        payments = self.db.get_order_payments(self.order_id)
        self.table.setRowCount(len(payments))
        for row, payment in enumerate(payments):
            values = [
                payment.get('paid_at', ''),
                f"{payment.get('amount', 0):.2f}",
                f"{payment.get('applied_amount', 0):.2f}",
                f"{payment.get('credit_amount', 0):.2f}",
                payment.get('note', ''),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.ItemDataRole.UserRole, payment['id'])
                self.table.setItem(row, col, item)

    def selected_payment_id(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if not item:
                continue
            payment_id = item.data(Qt.ItemDataRole.UserRole)
            if payment_id is None:
                continue
            try:
                return int(payment_id)
            except (TypeError, ValueError):
                continue
        return None

    def edit_payment(self):
        try:
            logger.info("edit_payment: starting")
            payment_id = self.selected_payment_id()
            logger.info(f"edit_payment: selected payment_id={payment_id}")
            if not payment_id:
                QMessageBox.information(self, "Платеж", "Выберите платеж для редактирования.")
                return
            payments = [p for p in self.db.get_order_payments(self.order_id) if p['id'] == payment_id]
            logger.info(f"edit_payment: found {len(payments)} payments")
            if not payments:
                QMessageBox.warning(self, "Платеж", "Платеж не найден.")
                return
            payment = payments[0]
            logger.info(f"edit_payment: opening dialog with amount={payment.get('amount')}")
            dialog = PaymentEditDialog(float(payment.get('amount', 0)), payment.get('note', ''), parent=self)
            result = dialog.exec()
            logger.info(f"edit_payment: dialog result={result}, Accepted={QDialog.DialogCode.Accepted}")
            if result != QDialog.DialogCode.Accepted:
                logger.info("edit_payment: dialog rejected")
                return
            amount, note = dialog.get_values()
            logger.info(f"edit_payment: got values amount={amount}, note={note}")
            if amount <= 0:
                QMessageBox.information(self, "Платеж", "Введите сумму больше нуля.")
                return
            if amount > 10000000:
                QMessageBox.information(self, "Платеж", f"Сумма платежа не может превышать 10 000 000. Введите корректную сумму.")
                return

            selected_rows = self.table.selectionModel().selectedRows()
            selected_row = selected_rows[0].row() if selected_rows else None
            logger.info(f"edit_payment: selected_row={selected_row}")

            logger.info(f"edit_payment: calling db.edit_order_payment({payment_id}, {amount}, {note})")
            self.db.edit_order_payment(payment_id, amount, note)
            logger.info(f"edit_payment: db call succeeded")
            
            logger.info(f"edit_payment: reloading payments")
            self.load_payments()
            logger.info(f"edit_payment: payments reloaded")
            
            if selected_row is not None and selected_row < self.table.rowCount():
                self.table.selectRow(selected_row)
            QMessageBox.information(self, "Платеж", f"Платеж сохранён: {amount:.2f} {CURRENCY}")
            logger.info(f"edit_payment: shown success message")
            
            if self.refresh_callback:
                logger.info(f"edit_payment: calling refresh_callback")
                self.refresh_callback()
                logger.info(f"edit_payment: refresh_callback done")
            logger.info("edit_payment: completed successfully")
        except Exception as e:
            logger.exception(f"edit_payment: caught exception: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить платеж:\n{e}")

    def delete_payment(self):
        payment_id = self.selected_payment_id()
        if not payment_id:
            QMessageBox.information(self, "Платеж", "Выберите платеж для удаления.")
            return
        if QMessageBox.question(self, "Платеж", "Удалить выбранный платеж?") != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_order_payment(payment_id)
        self.load_payments()
        if self.refresh_callback:
            self.refresh_callback()

    def reset_balance(self):
        if QMessageBox.question(self, "Баланс клиента", "Обнулить баланс клиента? Это действие нельзя отменить.") != QMessageBox.StandardButton.Yes:
            return
        self.db.update_client_balance(self.client_id, 0)
        QMessageBox.information(self, "Баланс клиента", "Баланс клиента сброшен.")
        if self.refresh_callback:
            self.refresh_callback()


class OrderEditDialog(QDialog):
    VAT_RATE = VAT_RATE

    def __init__(self, db: ServiceDatabase, order_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.order_id = order_id
        self.deleted_ids = []  # (section, id)
        self.modified = False

        self.setWindowTitle("📝 Редактирование заказ-наряда")
        self.setMinimumSize(1250, 750)

        self.suppliers = self.db.get_all_suppliers()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)

        status_box = QHBoxLayout()
        self.label_payment_status = QLabel("Статус оплаты: —")
        self.label_payment_status.setStyleSheet("font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #fdfefe;")
        status_box.addWidget(self.label_payment_status)
        status_box.addStretch()
        layout.addLayout(status_box)

        # Вкладки
        self.tab_widget = QTabWidget()
        self.tab_parts = QWidget()
        self.tab_services = QWidget()
        self.tab_widget.addTab(self.tab_parts, "🔩 Запчасти")
        self.tab_widget.addTab(self.tab_services, "🛠️ Услуги / Работы")

        # Запчасти
        parts_layout = QVBoxLayout(self.tab_parts)
        self.parts_table = self.create_parts_table()
        parts_layout.addWidget(self.parts_table)
        parts_btn = QHBoxLayout()
        btn_add_part = QPushButton("➕ Добавить строку")
        btn_add_part.clicked.connect(lambda: self.add_row('parts'))
        btn_del_part = QPushButton("🗑️ Удалить выбранную строку")
        btn_del_part.clicked.connect(lambda: self.delete_row('parts'))
        parts_btn.addWidget(btn_add_part)
        parts_btn.addWidget(btn_del_part)
        parts_btn.addStretch()
        parts_layout.addLayout(parts_btn)

        # Услуги
        services_layout = QVBoxLayout(self.tab_services)
        self.services_table = self.create_services_table()
        services_layout.addWidget(self.services_table)
        serv_btn = QHBoxLayout()
        btn_add_serv = QPushButton("➕ Добавить строку")
        btn_add_serv.clicked.connect(lambda: self.add_row('services'))
        btn_del_serv = QPushButton("🗑️ Удалить выбранную строку")
        btn_del_serv.clicked.connect(lambda: self.delete_row('services'))
        serv_btn.addWidget(btn_add_serv)
        serv_btn.addWidget(btn_del_serv)
        serv_btn.addStretch()
        services_layout.addLayout(serv_btn)

        layout.addWidget(self.tab_widget)

        # Итоги
        totals_widget = QWidget()
        totals_layout = QGridLayout(totals_widget)
        totals_layout.setSpacing(8)
        totals_layout.setContentsMargins(0, 0, 0, 0)

        self.label_total_net = QLabel(f"Сумма без НДС: 0.00 {CURRENCY}")
        self.label_vat = QLabel(f"НДС ({int(VAT_RATE * 100)}%): 0.00 {CURRENCY}")
        self.label_total_gross = QLabel(f"ИТОГО с НДС: 0.00 {CURRENCY}")
        self.label_paid_total = QLabel(f"Оплачено: 0.00 {CURRENCY}")
        self.label_remaining = QLabel(f"Остаток: 0.00 {CURRENCY}")
        self.label_client_balance = QLabel(f"Баланс клиента: 0.00 {CURRENCY}")
        self.payment_input = PaymentLineEdit("0.00")
        self.payment_input.setMaximumWidth(120)
        self.payment_input.returnPressed.connect(self.on_payment_input_return)

        preferred_policy = QSizePolicy.Preferred if hasattr(QSizePolicy, 'Preferred') else QSizePolicy.Policy.Preferred
        for lbl in [self.label_total_net, self.label_vat, self.label_total_gross,
                    self.label_paid_total, self.label_remaining, self.label_client_balance]:
            lbl.setStyleSheet("font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #fdfefe;")
            lbl.setWordWrap(True)
            lbl.setSizePolicy(preferred_policy, preferred_policy)

        self.label_total_gross.setStyleSheet("font-weight: bold; font-size: 15px; padding: 6px; background-color: #eaeded; border: 1px solid #b2babb; color: #1f5e9e;")

        totals_layout.addWidget(self.label_total_net, 0, 0)
        totals_layout.addWidget(self.label_vat, 0, 1)
        totals_layout.addWidget(self.label_total_gross, 0, 2)
        totals_layout.addWidget(self.label_paid_total, 0, 3)
        totals_layout.addWidget(self.label_remaining, 1, 0)
        totals_layout.addWidget(self.label_client_balance, 1, 1)
        totals_layout.addWidget(QLabel("Платёж:"), 1, 2)
        totals_layout.addWidget(self.payment_input, 1, 3)
        totals_layout.setColumnStretch(2, 1)
        totals_layout.setColumnStretch(3, 1)

        layout.addWidget(totals_widget)

        # Кнопки
        actions = QHBoxLayout()
        actions.addStretch()
        btn_save = QPushButton("💾 Сохранить все и закрыть")
        btn_save.setStyleSheet("background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f3d5bb, stop:1 #d8b092); color: #4d3625; font-weight: bold; padding: 6px 15px; border: 1px solid #c9a58e; border-radius: 12px;")
        btn_save.clicked.connect(self.save_all)
        btn_export_excel = QPushButton("Экспорт Excel")
        btn_export_excel.clicked.connect(self.export_excel)
        btn_export_pdf = QPushButton("Экспорт PDF")
        btn_export_pdf.clicked.connect(self.export_pdf)
        btn_print = QPushButton("Печатная форма")
        btn_print.clicked.connect(self.export_print_form)
        btn_payments = QPushButton("История платежей")
        btn_payments.clicked.connect(self.show_payment_history)
        btn_history = QPushButton("История статусов")
        btn_history.clicked.connect(self.show_status_history)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        actions.addWidget(btn_export_excel)
        actions.addWidget(btn_export_pdf)
        actions.addWidget(btn_print)
        actions.addWidget(btn_payments)
        actions.addWidget(btn_history)
        actions.addWidget(btn_save)
        actions.addWidget(btn_cancel)
        layout.addLayout(actions)

    # --------------------------------------------------------------
    def create_parts_table(self):
        table = EnterNavigableTable()
        table.setColumnCount(11)
        table.setHorizontalHeaderLabels([
            "№", "Номер детали", "Описание детали", "Количество",
            "Цена без НДС\nза единицу", "Закупка\nза единицу", "Поставщик",
            "Сумма без НДС", "НДС (20%)", "Всего с НДС", "Комментарий"
        ])
        self._setup_table_common(table)
        table.setItemDelegateForColumn(6, SupplierDelegate(self.suppliers, self))
        table.cellChanged.connect(lambda row, col: self.on_parts_cell_changed(row, col, table))
        table.itemChanged.connect(lambda item: self.auto_resize_columns(table))
        return table

    def create_services_table(self):
        table = EnterNavigableTable()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "№", "Описание услуги", "Кол-во", "Цена с НДС\n(за ед.)",
            "Сумма без НДС", "НДС (20%)", "Всего с НДС", "Комментарий"
        ])
        self._setup_table_common(table)
        table.cellChanged.connect(lambda row, col: self.on_services_cell_changed(row, col, table))
        table.itemChanged.connect(lambda item: self.auto_resize_columns(table))
        return table

    def _setup_table_common(self, table):
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(table.columnCount() - 1, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed |
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked
        )

    def auto_resize_columns(self, table):
        header = table.horizontalHeader()
        for col in range(table.columnCount() - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    # --------------------------------------------------------------
    def load_data(self):
        # Запчасти
        self.parts_table.blockSignals(True)
        self.parts_table.setRowCount(0)
        for part in self.db.get_order_parts(self.order_id):
            self._add_part_row_ui(part)
        self.parts_table.blockSignals(False)

        # Услуги
        self.services_table.blockSignals(True)
        self.services_table.setRowCount(0)
        for serv in self.db.get_order_services(self.order_id):
            self._add_service_row_ui(serv)
        self.services_table.blockSignals(False)

        order = self.db.get_order_details(self.order_id)
        if order:
            self.order_client_id = order.get('client_id')
            self.current_paid_amount = float(order.get('paid_amount', 0) or 0)
            self.current_client_balance = float(order.get('client_balance', 0) or 0)
            self.current_payment_status = order.get('payment_status', '—')
            self.payment_input.setText("0.00")
            self.label_paid_total.setText(f"Оплачено: {self.current_paid_amount:.2f} {CURRENCY}")
            remaining_value = max(order.get('total_amount', 0) - self.current_paid_amount, 0)
            self.label_remaining.setText(f"Остаток: {remaining_value:.2f} {CURRENCY}")
            self.label_client_balance.setText(f"Баланс клиента: {self.current_client_balance:.2f} {CURRENCY}")
            self.label_payment_status.setText(f"Статус оплаты: {self.current_payment_status}")
            self._update_total_label_styles(remaining_value, self.current_client_balance)

        self.full_recalculate()
        self.modified = False

    def event(self, event):
        try:
            if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.ActivationChange):
                if self.isActiveWindow():
                    try:
                        self._restore_table_editing()
                    except Exception:
                        logger.exception('Error while restoring table editing on window activation')
        except Exception:
            logger.exception('Error in OrderEditDialog.event')
        return super().event(event)

    def _restore_table_editing(self):
        try:
            if not hasattr(self, 'tab_widget') or not hasattr(self, 'parts_table') or not hasattr(self, 'services_table'):
                return
            table = self.parts_table if self.tab_widget.currentIndex() == 0 else self.services_table
            if table is None:
                return
            index = table.currentIndex()
            if not index.isValid():
                index = table.selectionModel().currentIndex()
            if index.isValid():
                item = table.item(index.row(), index.column())
                if item and item.flags() & Qt.ItemFlag.ItemIsEditable:
                    try:
                        table.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                        table.setCurrentCell(index.row(), index.column())
                        # defer edit slightly and only perform if table has focus to avoid race conditions
                        QTimer.singleShot(50, lambda it=item, t=table: t.editItem(it) if t.hasFocus() else None)
                    except Exception:
                        logger.exception('Failed to edit item in _restore_table_editing')
        except Exception:
            logger.exception('Error in _restore_table_editing')

    def on_payment_input_return(self):
        """Добавляет платеж в базу при нажатии Enter в поле ввода."""
        try:
            payment_amount = parse_number(self.payment_input.text())
            if payment_amount <= 0:
                QMessageBox.warning(self, "Платёж", "Введите положительную сумму платежа.")
                self.payment_input.setFocus()
                return
            
            # Заблокируем сигналы таблиц, чтобы не добавить пустую строку
            self.parts_table.blockSignals(True)
            self.services_table.blockSignals(True)
            
            # Добавляем платеж
            self.db.update_order_payment(self.order_id, payment_amount)
            
            # Обновляем UI
            self.load_data()
            
            # Разблокируем сигналы
            self.parts_table.blockSignals(False)
            self.services_table.blockSignals(False)
            
            # Показываем сообщение об успехе
            QMessageBox.information(self, "Платёж добавлен", f"Платёж на сумму {payment_amount:.2f} {CURRENCY} успешно добавлен.")
            
            # Очищаем поле и возвращаем фокус
            self.payment_input.setText("0.00")
            self.payment_input.selectAll()
            self.payment_input.setFocus()
        except Exception as e:
            logger.error(f"Error adding payment: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось добавить платёж:\n{e}")
            self.payment_input.setFocus()

    def _update_total_label_styles(self, remaining_value: float, client_balance: float | None = None):
        if remaining_value == 0:
            self.label_remaining.setStyleSheet(
                "font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #d4efdf; color: #1a7d42;"
            )
        else:
            self.label_remaining.setStyleSheet(
                "font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #f9ebea; color: #a93226;"
            )

        if client_balance is not None:
            if client_balance > 0:
                self.label_client_balance.setStyleSheet(
                    "font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #d4efdf; color: #1a7d42;"
                )
            elif client_balance < 0:
                self.label_client_balance.setStyleSheet(
                    "font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #f9ebea; color: #a93226;"
                )
            else:
                self.label_client_balance.setStyleSheet(
                    "font-weight: bold; font-size: 14px; padding: 6px; border: 1px solid #bdc3c7; background-color: #fdfefe; color: #4d4d4d;"
                )

    def _add_part_row_ui(self, data=None):
        table = self.parts_table
        row = table.rowCount()
        table.insertRow(row)

        qty_str = str(int(data.get('quantity', 1))) if data else '1'
        price_str = f"{data.get('selling_price', 0):.2f}" if data else '0.00'

        vals = [
            str(row + 1),
            data.get('part_number', '') if data else '',
            data.get('part_name', '') if data else '',
            qty_str,
            price_str,
            f"{data.get('purchase_price', 0):.2f}" if data else '0.00',
            data.get('supplier', '') if data else '',
            "0.00", "0.00", "0.00",
            data.get('notes', '') if data else ''
        ]
        for col, val in enumerate(vals):
            item = QTableWidgetItem(val)
            if col == 3 and data:
                item.setData(Qt.ItemDataRole.UserRole, data.get('id'))
            if col in (0, 7, 8, 9):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(QBrush(QColor("#f4f6f6")))
            table.setItem(row, col, item)
        self._update_part_row(row)
        self.auto_resize_columns(table)

    def _add_service_row_ui(self, data=None):
        table = self.services_table
        row = table.rowCount()
        table.insertRow(row)

        qty_str = str(int(data.get('quantity', 1))) if data else '1'
        price_str = f"{data.get('price_with_vat', 0):.2f}" if data else '0.00'

        vals = [
            str(row + 1),
            data.get('description', '') if data else '',
            qty_str,
            price_str,
            "0.00", "0.00", "0.00",
            data.get('notes', '') if data else ''
        ]
        for col, val in enumerate(vals):
            item = QTableWidgetItem(val)
            if col == 2 and data:
                item.setData(Qt.ItemDataRole.UserRole, data.get('id'))
            if col in (0, 4, 5, 6):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(QBrush(QColor("#f4f6f6")))
            table.setItem(row, col, item)
        self._update_service_row(row)
        self.auto_resize_columns(table)

    def add_row(self, section):
        if section == 'parts':
            self._add_part_row_ui()
            table = self.parts_table
            new_row = table.rowCount() - 1
            table.setCurrentCell(new_row, 1)
            table.editItem(table.item(new_row, 1))
        else:
            self._add_service_row_ui()
            table = self.services_table
            new_row = table.rowCount() - 1
            table.setCurrentCell(new_row, 1)
            table.editItem(table.item(new_row, 1))
        self.modified = True
        self.full_recalculate()

    def delete_row(self, section):
        table = self.parts_table if section == 'parts' else self.services_table
        indices = table.selectionModel().selectedRows()
        if not indices:
            QMessageBox.warning(self, "Удаление", "Выберите строку для удаления.")
            return
        if QMessageBox.question(self, "Удаление", "Удалить выбранные строки?") != QMessageBox.StandardButton.Yes:
            return

        for index in sorted(indices, reverse=True):
            row = index.row()
            id_item = table.item(row, 2 if section == 'services' else 3)
            p_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
            if p_id:
                self.deleted_ids.append((section, p_id))
            table.removeRow(row)
        self._renumber(table)
        self.full_recalculate()
        self.auto_resize_columns(table)
        self.modified = True

    def _renumber(self, table):
        for r in range(table.rowCount()):
            item = table.item(r, 0)
            if item:
                item.setText(str(r + 1))

    # --------------------------------------------------------------
    def on_parts_cell_changed(self, row, col, table):
        if col in (3, 4):
            self._update_part_row(row)
            self.full_recalculate()
            self.modified = True

    def on_services_cell_changed(self, row, col, table):
        if col in (2, 3):
            self._update_service_row(row)
            self.full_recalculate()
            self.modified = True

    def _update_part_row(self, row):
        table = self.parts_table
        qty_text = table.item(row, 3).text() if table.item(row, 3) else "0"
        price_text = table.item(row, 4).text() if table.item(row, 4) else "0"
        try:
            qty = int(parse_number(qty_text))
        except:
            qty = 1
        table.item(row, 3).setText(str(qty))
        price = parse_number(price_text)

        net = round(qty * price, 2)
        vat = round(net * self.VAT_RATE, 2)
        gross = net + vat

        table.blockSignals(True)
        for col, val in [(7, net), (8, vat), (9, gross)]:
            cell = table.item(row, col)
            if cell:
                cell.setText(f"{val:.2f}")
            else:
                item = QTableWidgetItem(f"{val:.2f}")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(QBrush(QColor("#f4f6f6")))
                table.setItem(row, col, item)
        table.blockSignals(False)

    def _update_service_row(self, row):
        table = self.services_table
        qty_text = table.item(row, 2).text() if table.item(row, 2) else "1"
        price_text = table.item(row, 3).text() if table.item(row, 3) else "0"

        try:
            qty = int(parse_number(qty_text))
        except:
            qty = 1
        table.item(row, 2).setText(str(qty))
        price_with_vat = parse_number(price_text)

        price_without_vat = round(price_with_vat / VAT_MULTIPLIER, 2)
        vat_amount = round(price_with_vat - price_without_vat, 2)

        subtotal_without = round(price_without_vat * qty, 2)
        subtotal_vat = round(vat_amount * qty, 2)
        subtotal_gross = round(price_with_vat * qty, 2)

        table.blockSignals(True)
        for col, val in [(4, subtotal_without), (5, subtotal_vat), (6, subtotal_gross)]:
            cell = table.item(row, col)
            if cell:
                cell.setText(f"{val:.2f}")
            else:
                item = QTableWidgetItem(f"{val:.2f}")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(QBrush(QColor("#f4f6f6")))
                table.setItem(row, col, item)
        table.blockSignals(False)

    def full_recalculate(self):
        total_net = 0.0
        total_vat = 0.0
        total_gross = 0.0

        for r in range(self.parts_table.rowCount()):
            self._update_part_row(r)
        for r in range(self.services_table.rowCount()):
            self._update_service_row(r)

        for r in range(self.parts_table.rowCount()):
            for col, target in [(7, 'net'), (8, 'vat'), (9, 'gross')]:
                item = self.parts_table.item(r, col)
                if item:
                    try:
                        val = float(item.text())
                        if target == 'net': total_net += val
                        elif target == 'vat': total_vat += val
                        else: total_gross += val
                    except:
                        pass

        for r in range(self.services_table.rowCount()):
            for col, target in [(4, 'net'), (5, 'vat'), (6, 'gross')]:
                item = self.services_table.item(r, col)
                if item:
                    try:
                        val = float(item.text())
                        if target == 'net': total_net += val
                        elif target == 'vat': total_vat += val
                        else: total_gross += val
                    except:
                        pass

        total_net = round(total_net, 2)
        total_vat = round(total_vat, 2)
        total_gross = round(total_gross, 2)

        self.label_total_net.setText(f"Сумма без НДС: {total_net:,.2f} {CURRENCY}")
        self.label_vat.setText(f"НДС ({int(VAT_RATE * 100)}%): {total_vat:,.2f} {CURRENCY}")
        self.label_total_gross.setText(f"ИТОГО с НДС: {total_gross:,.2f} {CURRENCY}")
        remaining_value = 0.0
        if hasattr(self, 'current_paid_amount'):
            self.label_paid_total.setText(f"Оплачено: {self.current_paid_amount:.2f} {CURRENCY}")
            remaining_value = max(total_gross - self.current_paid_amount, 0)
            self.label_remaining.setText(f"Остаток: {remaining_value:.2f} {CURRENCY}")
        if hasattr(self, 'current_client_balance'):
            predicted_balance = self.current_client_balance
            if self.current_paid_amount > total_gross:
                predicted_balance = self.current_client_balance + (self.current_paid_amount - total_gross)
            self.label_client_balance.setText(f"Баланс клиента: {predicted_balance:.2f} {CURRENCY}")
            self._update_total_label_styles(remaining_value, predicted_balance)

    # --------------------------------------------------------------
    def export_excel(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в Excel", f"order_{self.order_id}.xlsx", "Excel (*.xlsx)"
        )
        if not filename:
            return
        try:
            self.db.export_order_to_excel(self.order_id, filename)
            QMessageBox.information(self, "Экспорт", "Excel-файл создан.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))

    def export_pdf(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в PDF", f"order_{self.order_id}.pdf", "PDF (*.pdf)"
        )
        if not filename:
            return
        try:
            self.db.export_order_to_pdf(self.order_id, filename)
            QMessageBox.information(self, "Экспорт", "PDF-файл создан.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))

    def export_print_form(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Печатная форма", f"order_{self.order_id}.html", "HTML (*.html)"
        )
        if not filename:
            return
        try:
            self.db.export_order_to_html(self.order_id, filename)
            QMessageBox.information(self, "Печатная форма", "HTML-файл для печати создан.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))

    def show_payment_history(self):
        if not hasattr(self, 'order_client_id') or self.order_client_id is None:
            QMessageBox.warning(self, "История платежей", "Невозможно определить клиента заказа.")
            return
        dialog = PaymentHistoryDialog(self.db, self.order_id, self.order_client_id, refresh_callback=self.load_data, parent=self)
        dialog.exec()

    def show_status_history(self):
        history = self.db.get_order_status_history(self.order_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("История статусов")
        dialog.resize(600, 360)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        if history:
            lines = [
                f"{row['changed_at']}: {row.get('old_status') or '—'} → {row.get('new_status') or ''}"
                + (f" ({row.get('note')})" if row.get('note') else "")
                for row in history
            ]
            text.setPlainText("\n".join(lines))
        else:
            text.setPlainText("История статусов пока пуста.")
        layout.addWidget(text)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    # --------------------------------------------------------------
    def save_all(self):
        """Сохранение с корректной обработкой новых и обновлённых записей."""
        try:
            parts = []
            for r in range(self.parts_table.rowCount()):
                qty_item = self.parts_table.item(r, 3)
                if not qty_item:
                    continue
                p_id = qty_item.data(Qt.ItemDataRole.UserRole)
                part_number = self.parts_table.item(r, 1).text().strip() if self.parts_table.item(r, 1) else ''
                part_name = self.parts_table.item(r, 2).text().strip() if self.parts_table.item(r, 2) else ''
                if not part_name and not part_number:
                    continue
                quantity = int(parse_number(qty_item.text())) if qty_item else 1
                selling_price = parse_number(self.parts_table.item(r, 4).text()) if self.parts_table.item(r, 4) else 0
                purchase_price = parse_number(self.parts_table.item(r, 5).text()) if self.parts_table.item(r, 5) else 0
                supplier = self.parts_table.item(r, 6).text().strip() if self.parts_table.item(r, 6) else ''
                notes = self.parts_table.item(r, 10).text().strip() if self.parts_table.item(r, 10) else ''

                parts.append({
                    'id': p_id,
                    'part_number': part_number,
                    'part_name': part_name,
                    'quantity': quantity,
                    'selling_price': selling_price,
                    'purchase_price': purchase_price,
                    'supplier': supplier,
                    'notes': notes,
                })

            services = []
            for r in range(self.services_table.rowCount()):
                qty_item = self.services_table.item(r, 2)
                if not qty_item:
                    continue
                s_id = qty_item.data(Qt.ItemDataRole.UserRole)
                desc = self.services_table.item(r, 1).text().strip() if self.services_table.item(r, 1) else ''
                if not desc:
                    continue
                qty = int(parse_number(qty_item.text())) if qty_item else 1
                price_with_vat = parse_number(self.services_table.item(r, 3).text()) if self.services_table.item(r, 3) else 0
                notes = self.services_table.item(r, 7).text().strip() if self.services_table.item(r, 7) else ''

                services.append({
                    'id': s_id,
                    'description': desc,
                    'quantity': qty,
                    'price_with_vat': price_with_vat,
                    'notes': notes,
                })

            self.db.save_order_items(self.order_id, parts, services, self.deleted_ids)
            payment_amount = parse_number(self.payment_input.text())
            if payment_amount > 0:
                self.db.update_order_payment(self.order_id, payment_amount)
            self.deleted_ids.clear()

            self.modified = False
            QMessageBox.information(self, "Сохранено", "Заказ-наряд успешно обновлён.")
            self.accept()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить данные:\n{e}")

    def closeEvent(self, event):
        if self.modified:
            reply = QMessageBox.question(
                self, "Несохранённые изменения",
                "Сохранить изменения перед закрытием?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                self.save_all()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
