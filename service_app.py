# service_app.py - Главное приложение

import logging
import sys
import threading
from PyQt6.QtWidgets import (QApplication, QMainWindow, QTabWidget,
                              QWidget, QVBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QHBoxLayout,
                              QMessageBox, QHeaderView, QGroupBox, QListWidget,
                              QListWidgetItem, QMenu, QAbstractItemView,
                              QLineEdit, QSplitter, QComboBox, QFileDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QBrush
from database import ServiceDatabase
from constants import CURRENCY, CardField, ORDER_STATUSES, STATUS_COLORS
from entity_dialogs import ClientDialog, VehicleDialog, ManualOrderDialog, ManualOrderEntryDialog
from order_dialog import OrderDialog
from order_edit_dialog import OrderEditDialog
from new_order_choice_dialog import NewOrderChoiceDialog
import config
from app_logging import setup_logging
from backup import backup_database
from read_card_v2 import get_card_data

logger = logging.getLogger(__name__)


class CardReaderSignals(QObject):
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal()


class ServiceApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = ServiceDatabase(str(config.DB_PATH))
        self.setWindowTitle("🔧 Система управления автосервисом")
        self.setGeometry(100, 100, 1400, 800)

        self.card_signals = CardReaderSignals()
        self.card_signals.data_ready.connect(self.handle_card_data)
        self.card_signals.error.connect(lambda msg: QMessageBox.warning(self, "Ошибка карты", msg))
        self.card_signals.status.connect(self.on_card_reader_status)
        self.card_signals.finished.connect(self.on_card_reader_finished)

        backup_path = backup_database(
            config.DB_PATH, config.BACKUP_DIR, config.BACKUP_KEEP_DAYS
        )
        if backup_path:
            logging.getLogger(__name__).info("Startup backup: %s", backup_path)

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        header = QLabel("🚗 Автосервис - Управление заказами")
        header.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("padding: 15px; background-color: #d6b29b; color: #4a3321; border-radius: 10px;")
        main_layout.addWidget(header)

        quick_actions = QHBoxLayout()

        # ✅ Единая кнопка вместо трёх
        self.btn_new_order = QPushButton("➕ Новый заказ-наряд")
        self.btn_new_order.setStyleSheet(
            "padding: 10px; font-size: 14px; border: 1px solid #c9a58e; border-radius: 12px;"
            " background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f3d5bb, stop:1 #d8b092);"
            " color: #4d3625; font-weight: bold;")
        self.btn_new_order.clicked.connect(self.unified_new_order)

        quick_actions.addWidget(self.btn_new_order)
        quick_actions.addStretch()
        main_layout.addLayout(quick_actions)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #bdc3c7; border-radius: 5px; }
            QTabBar::tab { padding: 10px 20px; font-size: 13px; }
            QTabBar::tab:selected { background-color: #3498db; color: white; }
        """)

        self.tab_kanban = self.create_kanban_tab()
        self.tabs.addTab(self.tab_kanban, "📋 Текущие заказы")
        self.tab_clients = self.create_clients_tab()
        self.tabs.addTab(self.tab_clients, "👥 База клиентов")
        self.tab_vehicles = self.create_vehicles_tab()
        self.tabs.addTab(self.tab_vehicles, "🚗 Автомобили")
        self.tab_history = self.create_history_tab()
        self.tabs.addTab(self.tab_history, "🔍 Поиск истории")
        self.tab_finance = self.create_finance_tab()
        self.tabs.addTab(self.tab_finance, "💰 Финансы")
        main_layout.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.statusBar().showMessage("✅ Готов к работе")

    # ==================== ЕДИНАЯ ТОЧКА СОЗДАНИЯ ЗАКАЗА ====================
    def unified_new_order(self):
        """Открывает диалог выбора способа создания заказ-наряда."""
        dialog = NewOrderChoiceDialog(parent=self)
        if not dialog.exec():
            return
        choice = dialog.get_choice()
        if choice == NewOrderChoiceDialog.CHOICE_CARD:
            self.scan_card()
        elif choice == NewOrderChoiceDialog.CHOICE_MANUAL:
            self.create_new_order_manual()

    # ==================== КАНБАН ====================
    def create_kanban_tab(self):
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        main_layout.setSpacing(10)

        self.kanban_lists = {}
        self.status_colors = {status: QColor(color) for status, color in STATUS_COLORS.items()}
        self.statuses = ORDER_STATUSES

        for status in self.statuses:
            group = QGroupBox(status)
            group.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {self.status_colors[status].lighter(180).name()};
                    border: 2px solid {self.status_colors[status].name()};
                    border-radius: 8px; margin-top: 10px; font-weight: bold;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin; left: 10px; padding: 2px 10px;
                    background-color: {self.status_colors[status].name()};
                    color: white; border-radius: 4px;
                }}
            """)
            group_layout = QVBoxLayout(group)

            list_widget = QListWidget()
            list_widget.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(self.kanban_context_menu)
            list_widget.itemDoubleClicked.connect(self.on_order_double_clicked)
            list_widget.setStyleSheet("""
                QListWidget {
                    background-color: #ffffff; border: 1px solid #bdc3c7; border-radius: 5px; padding: 4px;
                }
                QListWidget::item {
                    padding: 8px; margin: 4px 0; border-radius: 5px; border-left: 5px solid;
                    color: black;
                }
                QListWidget::item:selected {
                    background-color: #3498db; color: white;
                }
            """)
            group_layout.addWidget(list_widget)
            self.kanban_lists[status] = list_widget
            main_layout.addWidget(group)

        self.load_kanban()
        return widget

    def load_kanban(self):
        for lst in self.kanban_lists.values():
            lst.clear()
        orders = self.db.get_orders_by_status()
        for order in orders:
            status = order.get('status', ORDER_STATUSES[0])
            if status not in self.kanban_lists:
                status = ORDER_STATUSES[0]
            car_info = f"{order.get('brand','')} {order.get('model','')} [{order.get('license_plate','')}]"
            text = f"№{order['order_number']}\n{order.get('full_name','')}\n{car_info}\n{order.get('created_at','')}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, order['id'])
            item.setForeground(QBrush(self.status_colors.get(status, QColor('#95a5a6'))))
            if order.get('complaint'):
                item.setToolTip(f"Жалоба: {order['complaint']}")
            self.kanban_lists[status].addItem(item)

    def refresh_kanban(self):
        self.load_kanban()

    def kanban_context_menu(self, pos):
        sender_list = self.sender()
        if not isinstance(sender_list, QListWidget):
            return
        item = sender_list.itemAt(pos)
        if not item:
            return
        order_id = item.data(Qt.ItemDataRole.UserRole)
        if not order_id:
            return
        order = self.db.get_order_details(order_id)
        if not order:
            return
        cur_status = order.get('status', ORDER_STATUSES[0])
        menu = QMenu()
        for st in self.statuses:
            if st != cur_status:
                act = menu.addAction(f"➡ {st}")
                act.setData((order_id, st))
        if menu.isEmpty():
            return
        chosen = menu.exec(sender_list.viewport().mapToGlobal(pos))
        if chosen:
            oid, new_st = chosen.data()
            try:
                self.db.update_order_status(oid, new_st)
                self.refresh_kanban()
                self.statusBar().showMessage(f"✅ Заказ перемещён в «{new_st}»")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось обновить статус:\n{e}")

    def on_order_double_clicked(self, item):
        order_id = self._get_order_id_from_item(item)
        if order_id:
            try:
                self.open_order_editor(order_id)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть заказ:\n{e}")

    def open_order_editor(self, order_id):
        dialog = OrderEditDialog(self.db, order_id, parent=self)
        if dialog.exec():
            self.refresh_kanban()
            self.statusBar().showMessage("✅ Заказ-наряд обновлён")

    def _get_order_id_from_item(self, item):
        order_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(order_id, str) and order_id.isdigit():
            return int(order_id)
        if isinstance(order_id, int):
            return order_id
        try:
            if order_id is not None:
                return int(order_id)
        except (TypeError, ValueError):
            pass
        return None

    # ==================== КЛИЕНТЫ ====================
    def create_clients_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        actions = QHBoxLayout()
        btn_add = QPushButton("Добавить клиента")
        btn_add.clicked.connect(self.add_client_manual)
        btn_edit = QPushButton("Редактировать")
        btn_edit.clicked.connect(self.edit_selected_client)
        actions.addWidget(btn_add)
        actions.addWidget(btn_edit)
        actions.addStretch()
        layout.addLayout(actions)
        self.clients_table = QTableWidget()
        self.clients_table.setColumnCount(5)
        self.clients_table.setHorizontalHeaderLabels(["ID", "ФИО", "Телефон", "Email", "Дата регистрации"])
        self.clients_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #bdc3c7; gridline-color: #ecf0f1;
            }
            QHeaderView::section {
                background-color: #34495e; color: white; padding: 8px; font-weight: bold;
            }
            QTableWidget::item:selected {
                background-color: #3498db; color: white;
            }
        """)
        self.clients_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.clients_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.clients_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.clients_table.itemDoubleClicked.connect(lambda _: self.edit_selected_client())
        layout.addWidget(self.clients_table)
        self.load_clients()
        return widget

    def load_clients(self):
        clients = self.db.get_all_clients()
        self.clients_table.setRowCount(len(clients))
        for row, c in enumerate(clients):
            self.clients_table.setItem(row, 0, QTableWidgetItem(str(c['id'])))
            self.clients_table.setItem(row, 1, QTableWidgetItem(c['full_name']))
            self.clients_table.setItem(row, 2, QTableWidgetItem(c.get('phone', '')))
            self.clients_table.setItem(row, 3, QTableWidgetItem(c.get('email', '')))
            self.clients_table.setItem(row, 4, QTableWidgetItem(c['created_at']))

    def add_client_manual(self):
        dialog = ClientDialog(parent=self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['full_name']:
                QMessageBox.warning(self, "Клиент", "ФИО обязательно.")
                return
            self.db.add_client(**data)
            self.load_clients()

    def edit_selected_client(self):
        row = self.clients_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Клиент", "Выберите клиента.")
            return
        client_id = int(self.clients_table.item(row, 0).text())
        client = self.db.get_client(client_id)
        if not client:
            return
        dialog = ClientDialog(client, self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['full_name']:
                QMessageBox.warning(self, "Клиент", "ФИО обязательно.")
                return
            self.db.update_client(client_id, **data)
            self.load_clients()
            self.load_vehicles()

    # ==================== АВТОМОБИЛИ ====================
    def create_vehicles_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        actions = QHBoxLayout()
        btn_add = QPushButton("Добавить автомобиль")
        btn_add.clicked.connect(self.add_vehicle_manual)
        btn_edit = QPushButton("Редактировать")
        btn_edit.clicked.connect(self.edit_selected_vehicle)
        actions.addWidget(btn_add)
        actions.addWidget(btn_edit)
        actions.addStretch()
        layout.addLayout(actions)
        self.vehicles_table = QTableWidget()
        self.vehicles_table.setColumnCount(7)
        self.vehicles_table.setHorizontalHeaderLabels(["ID", "VIN", "Марка", "Модель", "Год", "Номер", "Владелец"])
        self.vehicles_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #bdc3c7; gridline-color: #ecf0f1;
            }
            QHeaderView::section {
                background-color: #34495e; color: white; padding: 8px; font-weight: bold;
            }
            QTableWidget::item:selected {
                background-color: #3498db; color: white;
            }
        """)
        self.vehicles_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.vehicles_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vehicles_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.vehicles_table.itemDoubleClicked.connect(lambda _: self.edit_selected_vehicle())
        layout.addWidget(self.vehicles_table)
        self.load_vehicles()
        return widget

    def load_vehicles(self):
        vehicles = self.db.get_all_vehicles()
        self.vehicles_table.setRowCount(len(vehicles))
        for row, v in enumerate(vehicles):
            self.vehicles_table.setItem(row, 0, QTableWidgetItem(str(v['id'])))
            self.vehicles_table.setItem(row, 1, QTableWidgetItem(v['vin']))
            self.vehicles_table.setItem(row, 2, QTableWidgetItem(v['brand']))
            self.vehicles_table.setItem(row, 3, QTableWidgetItem(v.get('model', '')))
            self.vehicles_table.setItem(row, 4, QTableWidgetItem(str(v.get('year') or '')))
            self.vehicles_table.setItem(row, 5, QTableWidgetItem(v.get('license_plate', '')))
            self.vehicles_table.setItem(row, 6, QTableWidgetItem(v.get('owner_name', '')))

    def add_vehicle_manual(self):
        clients = self.db.get_all_clients()
        if not clients:
            QMessageBox.information(self, "Автомобиль", "Сначала добавьте клиента.")
            return
        dialog = VehicleDialog(clients, parent=self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['vin'] or not data['brand']:
                QMessageBox.warning(self, "Автомобиль", "VIN и марка обязательны.")
                return
            if self.db.add_vehicle(**data) is None:
                QMessageBox.warning(self, "Автомобиль", "Автомобиль с таким VIN уже существует.")
                return
            self.load_vehicles()

    def edit_selected_vehicle(self):
        row = self.vehicles_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Автомобиль", "Выберите автомобиль.")
            return
        vehicle_id = int(self.vehicles_table.item(row, 0).text())
        vehicle = self.db.get_vehicle(vehicle_id)
        if not vehicle:
            return
        dialog = VehicleDialog(self.db.get_all_clients(), vehicle, self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['vin'] or not data['brand']:
                QMessageBox.warning(self, "Автомобиль", "VIN и марка обязательны.")
                return
            if not self.db.update_vehicle(vehicle_id, **data):
                QMessageBox.warning(self, "Автомобиль", "Автомобиль с таким VIN уже существует.")
                return
            self.load_vehicles()
            self.refresh_kanban()

    # ==================== ПОИСК ИСТОРИИ ====================
    def create_history_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        search_box = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите имя владельца, регистрационный номер или VIN...")
        self.search_input.setStyleSheet("padding: 8px; font-size: 13px;")
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все статусы", None)
        for status in self.statuses:
            self.status_filter.addItem(status, status)
        self.vin_filter = QLineEdit()
        self.vin_filter.setPlaceholderText("VIN")
        self.order_number_filter = QLineEdit()
        self.order_number_filter.setPlaceholderText("№ заказа")
        self.phone_filter = QLineEdit()
        self.phone_filter.setPlaceholderText("Телефон")
        btn_search = QPushButton("🔍 Искать")
        btn_search.setStyleSheet("background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f3d5bb, stop:1 #d8b092); color: #4d3625; padding: 8px 16px; border: 1px solid #c9a58e; border-radius: 10px;")
        btn_search.clicked.connect(self.perform_search)
        search_box.addWidget(self.search_input)
        search_box.addWidget(self.status_filter)
        search_box.addWidget(self.vin_filter)
        search_box.addWidget(self.order_number_filter)
        search_box.addWidget(self.phone_filter)
        search_box.addWidget(btn_search)
        layout.addLayout(search_box)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "№ заказа", "Дата", "Клиент", "Автомобиль", "Номер", "Статус", "Сумма"
        ])
        self.history_table.setStyleSheet("""
            QTableWidget { border: 1px solid #bdc3c7; gridline-color: #ecf0f1; }
            QHeaderView::section { background-color: #34495e; color: white; padding: 8px; font-weight: bold; }
            QTableWidget::item:selected { background-color: #3498db; color: white; }
        """)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.itemDoubleClicked.connect(self.on_history_double_clicked)
        layout.addWidget(self.history_table)

        return widget

    def perform_search(self):
        query = self.search_input.text().strip()
        status = self.status_filter.currentData()
        vin = self.vin_filter.text().strip()
        order_number = self.order_number_filter.text().strip()
        phone = self.phone_filter.text().strip()
        if not any([query, status, vin, order_number, phone]):
            QMessageBox.information(self, "Поиск", "Введите запрос или выберите фильтр.")
            return
        results = self.db.search_orders(query, status=status, vin=vin, order_number=order_number, phone=phone)
        self.history_table.setRowCount(len(results))
        if not results:
            self.statusBar().showMessage("🔍 Ничего не найдено")
            return
        for row, order in enumerate(results):
            self.history_table.setItem(row, 0, QTableWidgetItem(str(order['order_number'])))
            self.history_table.setItem(row, 1, QTableWidgetItem(order['created_at']))
            self.history_table.setItem(row, 2, QTableWidgetItem(order['full_name']))
            car_desc = f"{order.get('brand','')} {order.get('model','')}"
            self.history_table.setItem(row, 3, QTableWidgetItem(car_desc))
            self.history_table.setItem(row, 4, QTableWidgetItem(order.get('license_plate', '')))
            self.history_table.setItem(row, 5, QTableWidgetItem(order.get('status', '')))
            self.history_table.setItem(row, 6, QTableWidgetItem(f"{order.get('total_amount', 0):.2f}"))
            # Сохраняем ID в первом столбце
            self.history_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, order['id'])
        self.statusBar().showMessage(f"🔍 Найдено: {len(results)}")

    def on_history_double_clicked(self, item):
        # ✅ ИСПРАВЛЕНО: всегда читаем ID из первого столбца
        first_item = self.history_table.item(item.row(), 0)
        order_id = first_item.data(Qt.ItemDataRole.UserRole) if first_item else None
        if order_id:
            self.open_order_editor(order_id)

    # ==================== ФИНАНСЫ ====================
    def create_finance_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QHBoxLayout()
        self.finance_period = QComboBox()
        self.finance_period.addItem("Сегодня", "day")
        self.finance_period.addItem("Эта неделя", "week")
        self.finance_period.addItem("Этот месяц", "month")
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.load_finance)
        btn_export = QPushButton("Экспорт отчета Excel")
        btn_export.clicked.connect(self.export_finance_report)
        controls.addWidget(QLabel("Период:"))
        controls.addWidget(self.finance_period)
        controls.addWidget(btn_refresh)
        controls.addWidget(btn_export)
        controls.addStretch()
        layout.addLayout(controls)

        self.finance_summary = QLabel()
        self.finance_summary.setStyleSheet("font-weight: bold; padding: 8px; background-color: #ecf0f1;")
        layout.addWidget(self.finance_summary)

        self.finance_tabs = QTabWidget()
        self.finance_orders_table = self._make_table([
            "№", "Дата", "Клиент", "Авто", "Выручка", "Себестоимость", "Прибыль", "Оплачено", "Долг"
        ])
        self.finance_services_table = self._make_table(["Услуга", "Кол-во", "Заказов", "Выручка"])
        self.finance_parts_table = self._make_table(["Деталь", "Номер", "Кол-во", "Заказов", "Выручка", "Себестоимость", "Прибыль"])
        self.finance_debts_table = self._make_table(["№", "Дата", "Клиент", "Телефон", "Авто", "Сумма", "Оплачено", "Долг", "Статус"])
        self.finance_debts_table.itemDoubleClicked.connect(self.on_finance_order_double_clicked)
        self.finance_orders_table.itemDoubleClicked.connect(self.on_finance_order_double_clicked)

        self.finance_tabs.addTab(self.finance_orders_table, "Прибыль по заказам")
        self.finance_tabs.addTab(self.finance_services_table, "Популярные услуги")
        self.finance_tabs.addTab(self.finance_parts_table, "Популярные запчасти")
        self.finance_tabs.addTab(self.finance_debts_table, "Долги")
        layout.addWidget(self.finance_tabs)

        self.load_finance()
        return widget

    def _make_table(self, headers):
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def load_finance(self):
        period = self.finance_period.currentData()
        summary = self.db.get_finance_summary(period)
        self.finance_summary.setText(
            f"Заказов: {summary['order_count']} | "
            f"Выручка: {summary['revenue']:.2f} {CURRENCY} | "
            f"Оплачено: {summary['paid']:.2f} {CURRENCY} | "
            f"Долг: {summary['debt']:.2f} {CURRENCY} | "
            f"Себестоимость запчастей: {summary['parts_cost']:.2f} {CURRENCY} | "
            f"Прибыль: {summary['profit']:.2f} {CURRENCY}"
        )
        self._fill_orders_profit(self.db.get_order_profit_rows(period))
        self._fill_popular_services(self.db.get_popular_services(period))
        self._fill_popular_parts(self.db.get_popular_parts(period))
        self._fill_debts(self.db.get_debts())

    def _fill_orders_profit(self, rows):
        table = self.finance_orders_table
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            car = f"{row.get('brand', '')} {row.get('model', '')} [{row.get('license_plate', '')}]"
            values = [
                row['order_number'], row['created_at'], row['full_name'], car,
                row['total_amount'], row['parts_cost'], row['profit'], row['paid_amount'], row['debt']
            ]
            self._set_finance_row(table, row_idx, values, row['id'])

    def _fill_popular_services(self, rows):
        table = self.finance_services_table
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            values = [row['description'], row['quantity'], row['order_count'], row['revenue']]
            self._set_finance_row(table, row_idx, values)

    def _fill_popular_parts(self, rows):
        table = self.finance_parts_table
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            values = [row['part_name'], row.get('part_number', ''), row['quantity'], row['order_count'], row['revenue'], row['cost'], row['profit']]
            self._set_finance_row(table, row_idx, values)

    def _fill_debts(self, rows):
        table = self.finance_debts_table
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            car = f"{row.get('brand', '')} {row.get('model', '')} [{row.get('license_plate', '')}]"
            values = [
                row['order_number'], row['created_at'], row['full_name'], row.get('phone', ''),
                car, row['total_amount'], row['paid_amount'], row['debt'], row['payment_status']
            ]
            self._set_finance_row(table, row_idx, values, row['id'])

    def _set_finance_row(self, table, row_idx, values, order_id=None):
        for col, value in enumerate(values):
            if isinstance(value, float):
                text = f"{value:.2f}"
            else:
                text = str(value or '')
            item = QTableWidgetItem(text)
            if col == 0 and order_id:
                item.setData(Qt.ItemDataRole.UserRole, order_id)
            table.setItem(row_idx, col, item)

    def on_finance_order_double_clicked(self, item):
        order_id = self._get_order_id_from_item(item)
        if not order_id and hasattr(item, 'tableWidget'):
            first_item = item.tableWidget().item(item.row(), 0)
            order_id = self._get_order_id_from_item(first_item) if first_item else None
        if order_id:
            try:
                self.open_order_editor(order_id)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть заказ:\n{e}")
            self.load_finance()

    def export_finance_report(self):
        period = self.finance_period.currentData()
        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспорт финансового отчета", f"finance_report_{period}.xlsx", "Excel (*.xlsx)"
        )
        if not filename:
            return
        try:
            self.db.export_finance_report_to_excel(filename, period)
            QMessageBox.information(self, "Экспорт", "Финансовый отчет создан.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))

    # ==================== СЧИТЫВАТЕЛЬ КАРТ ====================
    def scan_card(self):
        self.statusBar().showMessage("⏳ Вставьте карту в считыватель (до 30 сек)...")
        # ✅ Блокируем единую кнопку во время считывания
        self.btn_new_order.setEnabled(False)
        self.btn_new_order.setText("⏳ Считывание карты...")
        thread = threading.Thread(target=self._read_card_worker, daemon=True)
        thread.start()

    def on_card_reader_status(self, message):
        self.statusBar().showMessage(message)

    def _read_card_worker(self):
        """Фоновый поток для чтения карты."""
        def on_status(message):
            self.card_signals.status.emit(message)

        try:
            result = get_card_data(status_callback=on_status)
            if "error" in result:
                self.card_signals.error.emit(result["error"])
            else:
                self.card_signals.data_ready.emit(result)
        except Exception as e:
            logger.exception("Card reader error")
            self.card_signals.error.emit(f"Ошибка считывателя: {e}")
        finally:
            self.card_signals.finished.emit()

    def on_card_reader_finished(self):
        # ✅ Восстанавливаем единую кнопку
        self.btn_new_order.setEnabled(True)
        self.btn_new_order.setText("➕ Новый заказ-наряд")
        self.statusBar().showMessage("✅ Готов к работе")

    def handle_card_data(self, fields):
        """Обработка данных с карты техпаспорта."""
        try:
            vin = fields.get(CardField.VIN.value, '').strip()
            owner_name = fields.get(CardField.OWNER.value, '').strip()
            brand = fields.get(CardField.BRAND.value, 'Неизвестно').strip()
            model = fields.get(CardField.MODEL.value, '').strip()
            plate = fields.get(CardField.PLATE.value, '').strip()
            color = fields.get(CardField.COLOR.value, '').strip()
            year = fields.get(CardField.YEAR.value, '').strip()
            try:
                year = int(year) if year else None
            except (ValueError, TypeError):
                year = None

            if not vin or not owner_name:
                answer = QMessageBox.question(
                    self,
                    "Неполные данные",
                    "Карта не содержит VIN или ФИО владельца. Ввести данные вручную?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self.create_new_order_manual()
                return

            with self.db._db_lock:
                client = self.db.find_client_by_name(owner_name)
                if not client:
                    client_id = self.db.add_client(owner_name)
                    client = {'id': client_id, 'full_name': owner_name}

                vehicle = self.db.find_vehicle_by_vin(vin)
                if not vehicle:
                    vid = self.db.add_vehicle(client['id'], vin, brand, model, year, plate, color)
                    if vid is None:
                        QMessageBox.warning(self, "Ошибка", "Не удалось добавить автомобиль (возможно, VIN уже есть).")
                        return
                    vehicle = {'id': vid, 'vin': vin, 'brand': brand, 'model': model,
                               'license_plate': plate, 'color': color, 'year': year}

            self.open_new_order_dialog(client, vehicle)

        except Exception as e:
            logger.exception("Error handling card data")
            QMessageBox.critical(self, "Ошибка", f"Ошибка обработки данных карты: {e}")

    def create_new_order(self):
        """Создание заказа через выбор из существующих клиентов/авто."""
        clients = self.db.get_all_clients()
        vehicles = self.db.get_all_vehicles()
        if not clients or not vehicles:
            QMessageBox.information(self, "Новый заказ", "Сначала добавьте клиента и автомобиль.")
            return
        dialog = ManualOrderDialog(clients, vehicles, self)
        if not dialog.exec():
            return
        data = dialog.get_data()
        if not data['complaint']:
            QMessageBox.warning(self, "Новый заказ", "Жалоба клиента обязательна.")
            return
        vehicle = data['vehicle']
        if not vehicle:
            QMessageBox.warning(self, "Новый заказ", "У выбранного клиента нет автомобиля.")
            return
        client = self.db.get_client(vehicle['client_id'])
        order_id, _ = self.db.create_order(vehicle['id'], client['id'], data['complaint'])
        self.open_order_editor(order_id)
        self.refresh_kanban()
        self.tabs.setCurrentWidget(self.tab_kanban)

    def create_new_order_manual(self):
        """Создание заказа с ручным вводом всех данных."""
        dialog = ManualOrderEntryDialog(self)
        if not dialog.exec():
            return
        data = dialog.get_data()
        required = [data['full_name'], data['vin'], data['brand'], data['complaint']]
        if not all(required):
            QMessageBox.warning(self, "Новый заказ", "ФИО, VIN, марка и жалоба обязательны.")
            return

        client = self.db.find_client_by_name(data['full_name'])
        if not client:
            client_id = self.db.add_client(
                data['full_name'], data['phone'], data['email'], data['address'], data['notes']
            )
            client = self.db.get_client(client_id)

        vehicle = self.db.find_vehicle_by_vin(data['vin'])
        if vehicle and vehicle['client_id'] != client['id']:
            QMessageBox.warning(self, "Автомобиль", "VIN уже зарегистрирован за другим клиентом.")
            return

        if not vehicle:
            vehicle_id = self.db.add_vehicle(
                client['id'], data['vin'], data['brand'], data['model'], data['year'], data['license_plate'], data['color']
            )
            if vehicle_id is None:
                QMessageBox.warning(self, "Автомобиль", "Автомобиль с таким VIN уже существует.")
                return
            vehicle = self.db.get_vehicle(vehicle_id)

        order_id, _ = self.db.create_order(vehicle['id'], client['id'], data['complaint'])
        self.open_order_editor(order_id)
        self.refresh_kanban()
        self.load_clients()
        self.load_vehicles()
        self.tabs.setCurrentWidget(self.tab_kanban)

    def open_new_order_dialog(self, client, vehicle):
        dialog = OrderDialog(self.db, client, vehicle, parent=self)
        if dialog.exec() and dialog.order_created:
            if dialog.order_id:
                self.open_order_editor(dialog.order_id)
            self.refresh_kanban()
            self.load_clients()
            self.load_vehicles()
        else:
            self.statusBar().showMessage("❌ Создание заказа отменено или произошла ошибка")

    def on_tab_changed(self, index):
        current = self.tabs.widget(index)
        if current is self.tab_kanban:
            self.refresh_kanban()
        elif current is self.tab_clients:
            self.load_clients()
        elif current is self.tab_vehicles:
            self.load_vehicles()
        elif current is self.tab_finance:
            self.load_finance()

    def closeEvent(self, event):
        self.db.close()
        event.accept()


def main():
    setup_logging(config.LOG_DIR, config.LOG_FILE)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet("""
        QWidget {
            background-color: #f5e8df;
            color: #4a3527;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        QMainWindow {
            background-color: #f5e8df;
        }
        QTabWidget::pane {
            border: 1px solid #d4b9a1;
            border-radius: 12px;
            background: #f9efe5;
        }
        QTabBar::tab {
            padding: 10px 20px;
            font-size: 13px;
            background: #edd3bb;
            color: #4a3527;
            border: 1px solid #d4b9a1;
            border-bottom: none;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            margin-right: 4px;
        }
        QTabBar::tab:selected {
            background: #f3dcc6;
            color: #3c2c21;
        }
        QTabBar::tab:hover {
            background: #f7e1cf;
        }
        QGroupBox {
            background-color: #f7e9dd;
            border: 1px solid #d4b9a1;
            border-radius: 12px;
            margin-top: 18px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 2px 8px;
            background-color: #d5b09a;
            color: #3f2d20;
            border-radius: 6px;
        }
        QPushButton {
            background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f3d5bb, stop:1 #d8b092);
            border: 1px solid #c9a58e;
            border-radius: 12px;
            color: #4d3625;
            padding: 10px 16px;
            min-height: 36px;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f7dbc1, stop:1 #dbbb9d);
        }
        QPushButton:pressed {
            background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #d8ad8b, stop:1 #c59777);
            padding-top: 2px;
        }
        QTableWidget, QListWidget, QTreeView {
            background-color: #fbf3ec;
            gridline-color: #e6d3c4;
            border: 1px solid #d4b9a1;
        }
        QHeaderView::section {
            background-color: #e7d0be;
            color: #4a3527;
            padding: 8px;
            border: 1px solid #d4b9a1;
        }
        QLineEdit, QTextEdit, QComboBox, QPlainTextEdit {
            background-color: #fff6ec;
            border: 1px solid #d4b9a1;
            border-radius: 8px;
            padding: 6px;
            color: #4d3625;
        }
        QMessageBox {
            background-color: #f8ede1;
        }
        QStatusBar {
            background-color: #ead5c0;
            color: #4a3527;
        }
    """)
    window = ServiceApp()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
