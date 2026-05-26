import logging
from billing import line_totals_with_vat, split_unit_price_with_vat
from constants import PartStatus

logger = logging.getLogger(__name__)


class OrderRepository:
    def __init__(self, db):
        self.db = db

    def save_order_items(self, order_id, parts, services, deleted_ids=None):
        """
        ✅ ИСПРАВЛЕНО: Используем контекстный менеджер для безопасной работы с БД.
        Гарантирует COMMIT при успехе и ROLLBACK при ошибке.
        ✅ Защищено от утечки соединений (always closes).
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            deleted_ids = deleted_ids or []

            try:
                cursor.execute("BEGIN IMMEDIATE")  # IMMEDIATE для безопасности

                # --- Удаление помеченных элементов ---
                for section, item_id in deleted_ids:
                    if section == "parts":
                        cursor.execute("DELETE FROM order_parts WHERE id=? AND order_id=?", (item_id, order_id))
                    else:
                        cursor.execute("DELETE FROM order_services WHERE id=? AND order_id=?", (item_id, order_id))

                # --- Сохранение запчастей ---
                kept_part_ids = set()
                for part in parts:
                    part_id = part.get("id")
                    if part_id:
                        cursor.execute(
                            """
                            UPDATE order_parts
                            SET part_name=?, part_number=?, quantity=?, selling_price=?,
                                purchase_price=COALESCE(?, purchase_price),
                                supplier=?, status=COALESCE(?, status), notes=?
                            WHERE id=? AND order_id=?
                            """,
                            (
                                part["part_name"],
                                part.get("part_number"),
                                part["quantity"],
                                part["selling_price"],
                                part.get("purchase_price"),
                                part.get("supplier"),
                                part.get("status"),
                                part.get("notes"),
                                part_id,
                                order_id,
                            ),
                        )
                        kept_part_ids.add(part_id)
                    else:
                        cursor.execute(
                            """
                            INSERT INTO order_parts
                            (order_id, part_name, part_number, quantity, purchase_price,
                             selling_price, status, supplier, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                order_id,
                                part["part_name"],
                                part.get("part_number"),
                                part["quantity"],
                                part.get("purchase_price", 0.0),
                                part["selling_price"],
                                part.get("status", PartStatus.NEEDS_ORDER.value),
                                part.get("supplier"),
                                part.get("notes"),
                            ),
                        )
                        kept_part_ids.add(cursor.lastrowid)

                # Удалить старые запчасти
                if kept_part_ids:
                    placeholders = ",".join("?" for _ in kept_part_ids)
                    cursor.execute(
                        f"DELETE FROM order_parts WHERE order_id=? AND id NOT IN ({placeholders})",
                        (order_id, *kept_part_ids),
                    )
                else:
                    cursor.execute("DELETE FROM order_parts WHERE order_id=?", (order_id,))

                # --- Сохранение услуг ---
                kept_service_ids = set()
                for service in services:
                    service_id = service.get("id")
                    price_with_vat = service["price_with_vat"]
                    quantity = service["quantity"]
                    price_without_vat, vat_amount, _ = split_unit_price_with_vat(price_with_vat)
                    subtotal_without_vat, vat_total, subtotal_with_vat = line_totals_with_vat(
                        price_with_vat, quantity
                    )

                    if service_id:
                        cursor.execute(
                            """
                            UPDATE order_services
                            SET description=?, price_with_vat=?, vat_amount=?, price_without_vat=?,
                                quantity=?, subtotal_with_vat=?, subtotal_without_vat=?, notes=?
                            WHERE id=? AND order_id=?
                            """,
                            (
                                service["description"],
                                price_with_vat,
                                vat_amount,
                                price_without_vat,
                                quantity,
                                subtotal_with_vat,
                                subtotal_without_vat,
                                service.get("notes"),
                                service_id,
                                order_id,
                            ),
                        )
                        kept_service_ids.add(service_id)
                    else:
                        cursor.execute(
                            """
                            INSERT INTO order_services
                            (order_id, description, price_with_vat, vat_amount, price_without_vat,
                             quantity, subtotal_with_vat, subtotal_without_vat, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                order_id,
                                service["description"],
                                price_with_vat,
                                vat_amount,
                                price_without_vat,
                                quantity,
                                subtotal_with_vat,
                                subtotal_without_vat,
                                service.get("notes", ""),
                            ),
                        )
                        kept_service_ids.add(cursor.lastrowid)

                # Удалить старые услуги
                if kept_service_ids:
                    placeholders = ",".join("?" for _ in kept_service_ids)
                    cursor.execute(
                        f"DELETE FROM order_services WHERE order_id=? AND id NOT IN ({placeholders})",
                        (order_id, *kept_service_ids),
                    )
                else:
                    cursor.execute("DELETE FROM order_services WHERE order_id=?", (order_id,))

                # ✅ ОБНОВИТЬ ИТОГОВУЮ СУММУ (БЕЗ COMMIT - контекстный менеджер сделает)
                self.db._update_order_total(conn, order_id, commit=False)
                
                logger.info("Order items saved: order_id=%d, parts=%d, services=%d",
                           order_id, len(parts), len(services))
                
                # ✅ ВАЖНО: Контекстный менеджер автоматически сделает COMMIT при выходе
                
            except Exception as e:
                logger.exception("Failed to save order items for order_id=%d: %s", order_id, e)
                raise
