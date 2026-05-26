import logging
import time
from datetime import datetime

import openpyxl
from smartcard.Exceptions import NoCardException
from smartcard.System import readers
from smartcard.util import toHexString

import config

logger = logging.getLogger(__name__)


def parse_ber_tlv(data):
    """Парсер формата BER-TLV, используемого в смарт-картах."""
    parsed = {}
    i = 0
    while i < len(data):
        if data[i] == 0x00 or data[i] == 0xFF:
            i += 1
            continue

        tag = data[i]
        tag_len = 1
        if (tag & 0x1F) == 0x1F:
            tag = (tag << 8) | data[i + 1]
            tag_len = 2
            i += 1
        i += 1

        if i >= len(data):
            break

        length = data[i]
        i += 1
        if length & 0x80:
            num_bytes = length & 0x7F
            length = 0
            for _ in range(num_bytes):
                if i < len(data):
                    length = (length << 8) | data[i]
                    i += 1

        value = data[i : i + length]
        i += length

        if tag_len == 1:
            is_constructed = (tag & 0x20) == 0x20
        else:
            is_constructed = ((tag >> 8) & 0x20) == 0x20

        parsed_val = parse_ber_tlv(value) if is_constructed else value

        if tag in parsed:
            if not isinstance(parsed[tag], list):
                parsed[tag] = [parsed[tag]]
            parsed[tag].append(parsed_val)
        else:
            parsed[tag] = [parsed_val]

    return parsed


def get_tlv_value(parsed, *path):
    """Безопасное получение значения по пути тегов."""
    curr = parsed
    for tag in path:
        if isinstance(curr, list):
            found = False
            for item in curr:
                if isinstance(item, dict) and tag in item:
                    curr = item[tag]
                    found = True
                    break
            if not found:
                return None
        elif isinstance(curr, dict) and tag in curr:
            curr = curr[tag]
        else:
            return None

    if isinstance(curr, list) and len(curr) > 0:
        curr = curr[0]

    if isinstance(curr, (list, bytes)):
        try:
            return bytes(curr).decode("utf-8", errors="ignore").strip()
        except Exception:
            return bytes(curr).hex()
    return curr


def extract_document_data(tlv_tree):
    """Извлекает поля из распарсенного TLV дерева."""
    fields = {}

    val = get_tlv_value(tlv_tree, 0x72, 0x98)
    if val:
        fields["Категория авто"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0x99)
    if val:
        fields["Количество осей"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0xA5, 0x9E)
    if val:
        fields["Номер двигателя"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0x9F24)
    if val:
        fields["Цвет"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0xC2)
    if val:
        fields["Личный номер владельца (JMBG)"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0xC4)
    if val:
        fields["Нагрузка ТС"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0xC5)
    if val:
        fields["Год выпуска"] = val

    val = get_tlv_value(tlv_tree, 0x72, 0xC9)
    if val:
        fields["Серийный номер документа"] = val

    val = get_tlv_value(tlv_tree, 0x71, 0x81)
    if val:
        fields["Номер авто"] = val

    val = get_tlv_value(tlv_tree, 0x71, 0x8A)
    if val:
        fields["VIN номер"] = val

    val = get_tlv_value(tlv_tree, 0x71, 0xA3, 0x87)
    if val:
        fields["Марка (Make)"] = val

    val = get_tlv_value(tlv_tree, 0x71, 0xA3, 0x89)
    if val:
        fields["Модель"] = val

    owner_surname = get_tlv_value(tlv_tree, 0x71, 0xA1, 0xA2, 0x83) or get_tlv_value(
        tlv_tree, 0x72, 0xA1, 0xA2, 0x83
    )
    owner_name = get_tlv_value(tlv_tree, 0x71, 0xA1, 0xA2, 0x84) or get_tlv_value(
        tlv_tree, 0x72, 0xA1, 0xA2, 0x84
    )
    owner_address = get_tlv_value(tlv_tree, 0x71, 0xA1, 0xA2, 0x85) or get_tlv_value(
        tlv_tree, 0x72, 0xA1, 0xA2, 0x85
    )

    if owner_name or owner_surname:
        fields["Владелец"] = f"{owner_name or ''} {owner_surname or ''}".strip()
    if owner_address:
        fields["Адрес владельца"] = owner_address

    user_surname = get_tlv_value(tlv_tree, 0x71, 0xA1, 0xA9, 0x83) or get_tlv_value(
        tlv_tree, 0x72, 0xA1, 0xA9, 0x83
    )
    user_name = get_tlv_value(tlv_tree, 0x71, 0xA1, 0xA9, 0x84) or get_tlv_value(
        tlv_tree, 0x72, 0xA1, 0xA9, 0x84
    )
    user_address = get_tlv_value(tlv_tree, 0x71, 0xA1, 0xA9, 0x85) or get_tlv_value(
        tlv_tree, 0x72, 0xA1, 0xA9, 0x85
    )

    if user_name or user_surname:
        fields["Пользователь (Корисник)"] = f"{user_name or ''} {user_surname or ''}".strip()
    if user_address:
        fields["Адрес пользователя"] = user_address

    return fields


def wait_for_card(connection, timeout_sec=None, poll_interval_sec=None, status_callback=None):
    """Ожидание вставки карты с периодическим опросом."""
    timeout_sec = timeout_sec if timeout_sec is not None else config.CARD_WAIT_TIMEOUT_SEC
    poll_interval_sec = (
        poll_interval_sec if poll_interval_sec is not None else config.CARD_POLL_INTERVAL_SEC
    )

    for attempt in range(timeout_sec):
        try:
            connection.connect()
            logger.info("Card connected after %s sec", attempt + 1)
            return True
        except NoCardException:
            if status_callback and (attempt == 0 or (attempt + 1) % 5 == 0):
                status_callback(
                    f"Ожидание карты... ({attempt + 1}/{timeout_sec} сек)"
                )
            time.sleep(poll_interval_sec)
        except Exception as exc:
            logger.exception("Card connection error")
            raise exc

    return False


def get_card_data(timeout_sec=None, poll_interval_sec=None, status_callback=None):
    """
    Читает карту и возвращает словарь полей или {'error': '...'}.
    Ожидает вставку карты до timeout_sec секунд.
    """
    try:
        reader_list = readers()
        if len(reader_list) == 0:
            return {"error": "Считыватель смарт-карт не найден. Проверьте подключение USB."}

        reader = reader_list[0]
        connection = reader.createConnection()
        logger.info("Using card reader: %s", reader)

        if not wait_for_card(
            connection,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            status_callback=status_callback,
        ):
            return {
                "error": (
                    f"Карта не вставлена. Превышено время ожидания ({config.CARD_WAIT_TIMEOUT_SEC} сек)."
                )
            }

        try:
            card_data = read_all_data(connection, verbose=False)
            if not card_data:
                return {"error": "Не удалось прочитать данные с карты (возможно, неверный формат)."}

            full_data = bytearray()
            for key in ("File_D001", "File_D011", "File_D021", "File_D031"):
                if key in card_data:
                    full_data.extend(card_data[key])

            tlv_tree = parse_ber_tlv(list(full_data))
            return extract_document_data(tlv_tree)
        except Exception as exc:
            logger.exception("Card data processing failed")
            return {"error": f"Ошибка обработки данных: {exc}"}
        finally:
            try:
                connection.disconnect()
            except Exception:
                pass
    except Exception as exc:
        logger.exception("Smart card system error")
        return {"error": f"Системная ошибка смарт-карты: {exc}"}


def read_all_data(connection, verbose=True):
    """Чтение всех доступных данных с карты."""
    all_data = {}

    def log_info(msg, *args):
        if verbose:
            logger.info(msg, *args)
        else:
            logger.debug(msg, *args)

    select_commands = [
        [0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00],
        [0x00, 0xA4, 0x04, 0x00, 0x07, 0xA0, 0x00, 0x00, 0x01, 0x51, 0x00, 0x00],
        [
            0x00,
            0xA4,
            0x04,
            0x00,
            0x10,
            0xA0,
            0x00,
            0x00,
            0x00,
            0x77,
            0x01,
            0x08,
            0x00,
            0x07,
            0x00,
            0x00,
            0xFE,
            0x00,
            0x00,
            0x01,
            0x00,
        ],
        [
            0x00,
            0xA4,
            0x04,
            0x0C,
            0x10,
            0xA0,
            0x00,
            0x00,
            0x00,
            0x77,
            0x01,
            0x08,
            0x00,
            0x07,
            0x00,
            0x00,
            0xFE,
            0x00,
            0x00,
            0xAD,
            0xF2,
        ],
        [0x00, 0xA4, 0x04, 0x00, 0x08, 0xA0, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00],
        [
            0x00,
            0xA4,
            0x04,
            0x00,
            0x0D,
            0xF3,
            0x81,
            0x00,
            0x00,
            0x02,
            0x53,
            0x45,
            0x52,
            0x56,
            0x4C,
            0x04,
            0x02,
            0x01,
        ],
        [0x00, 0xA4, 0x04, 0x00, 0x08, 0xA0, 0x00, 0x00, 0x00, 0x18, 0x43, 0x4D, 0x00],
        [
            0x00,
            0xA4,
            0x04,
            0x00,
            0x10,
            0xA0,
            0x00,
            0x00,
            0x00,
            0x18,
            0x34,
            0x14,
            0x01,
            0x00,
            0x65,
            0x56,
            0x4C,
            0x2D,
            0x30,
            0x30,
            0x31,
        ],
        [
            0x00,
            0xA4,
            0x04,
            0x0C,
            0x0C,
            0xA0,
            0x00,
            0x00,
            0x00,
            0x18,
            0x65,
            0x56,
            0x4C,
            0x2D,
            0x30,
            0x30,
            0x31,
        ],
    ]

    log_info("SELECT AID...")
    for cmd in select_commands:
        try:
            _, sw1, sw2 = connection.transmit(cmd)
            log_info("SELECT %s: SW=%02X%02X", toHexString(cmd), sw1, sw2)
            if sw1 == 0x90 and sw2 == 0x00:
                log_info("Application selected")
                break
        except Exception:
            logger.debug("SELECT failed for %s", toHexString(cmd), exc_info=True)

    ef_files = [
        [0x00, 0xA4, 0x02, 0x04, 0x02, 0xD0, 0x01],
        [0x00, 0xA4, 0x02, 0x04, 0x02, 0xD0, 0x11],
        [0x00, 0xA4, 0x02, 0x04, 0x02, 0xD0, 0x21],
        [0x00, 0xA4, 0x02, 0x04, 0x02, 0xD0, 0x31],
    ]

    log_info("READ BINARY...")
    for idx, ef_cmd in enumerate(ef_files):
        try:
            _, sw1, sw2 = connection.transmit(ef_cmd)
            if sw1 == 0x90 and sw2 == 0x00:
                file_data = bytearray()
                offset = 0
                while True:
                    read_cmd = [0x00, 0xB0, (offset >> 8) & 0xFF, offset & 0xFF, 0xFF]
                    response, r_sw1, r_sw2 = connection.transmit(read_cmd)

                    if r_sw1 == 0x90 and r_sw2 == 0x00 and len(response) > 0:
                        file_data.extend(response)
                        offset += len(response)
                        if len(response) < 0xFF:
                            break
                    elif r_sw1 == 0x6B and r_sw2 == 0x00:
                        break
                    elif r_sw1 == 0x62 and r_sw2 == 0x82:
                        if len(response) > 0:
                            file_data.extend(response)
                        break
                    else:
                        if offset == 0:
                            logger.warning(
                                "Read file D0%01d failed: SW=%02X%02X", idx, r_sw1, r_sw2
                            )
                        break

                if len(file_data) > 0:
                    all_data[f"File_D0{idx}1"] = list(file_data)
                    log_info("File D0%01d read (%d bytes)", idx, len(file_data))
        except Exception:
            logger.debug("EF read error D0%01d", idx, exc_info=True)

    if not all_data:
        log_info("Fallback: READ RECORD")
        for rec_num in range(1, 20):
            try:
                read_cmd = [0x00, 0xB2, rec_num, 0x04, 0x00]
                response, sw1, sw2 = connection.transmit(read_cmd)
                if sw1 == 0x90 and sw2 == 0x00 and len(response) > 0:
                    all_data[f"Запись_{rec_num}"] = response
            except Exception:
                pass

    if not all_data:
        try:
            read_cmd = [0x00, 0xB0, 0x00, 0x00, 0xFF]
            response, sw1, sw2 = connection.transmit(read_cmd)
            if sw1 == 0x90 and sw2 == 0x00 and response:
                all_data["Blind_Binary"] = response
        except Exception:
            pass

    return all_data


def save_to_excel(parsed_fields, raw_data):
    if not parsed_fields and not raw_data:
        logger.warning("No card data to save to Excel")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Саобраћајна дозвола"
    ws.append(["Поле", "Значение"])
    ws.append(["Дата чтения", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ws.append([])

    if parsed_fields:
        ws.append(["--- ИЗВЛЕЧЕННЫЕ ДАННЫЕ ---", ""])
        for key, value in parsed_fields.items():
            ws.append([key, value])
        ws.append([])

    if raw_data:
        ws.append(["--- СЫРЫЕ БИНАРНЫЕ ДАННЫЕ (HEX) ---", ""])
        for key, value in raw_data.items():
            if isinstance(value, list):
                ws.append([key, toHexString(value)])

    filename = f"card_data_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(filename)
    logger.info("Card data saved to %s", filename)


def read_serbian_card():
    """CLI: чтение карты с выводом в консоль."""
    print("=" * 60)
    print("ЧТЕНИЕ СЕРБСКОЙ САОБРАЋАЙНЕ ДОЗВОЛЕ")
    print("=" * 60)

    reader_list = readers()
    if len(reader_list) == 0:
        print("Ридеры не найдены!")
        return

    print(f"Найдено ридеров: {len(reader_list)}")
    print(f"Ридер: {reader_list[0]}")
    print("\nВСТАВЬТЕ смарт-карту в ридер...")

    connection = reader_list[0].createConnection()
    if not wait_for_card(
        connection,
        status_callback=lambda msg: print(f"   {msg}"),
    ):
        print("Карта не вставлена. Превышено время ожидания.")
        return

    print("Карта обнаружена!")
    try:
        print(f"   ATR: {toHexString(connection.getATR())}")
    except Exception:
        pass

    try:
        card_data = read_all_data(connection, verbose=True)
        if card_data:
            full_data = bytearray()
            for key in ("File_D001", "File_D011", "File_D021", "File_D031"):
                if key in card_data:
                    full_data.extend(card_data[key])
            try:
                tlv_tree = parse_ber_tlv(list(full_data))
                extracted_fields = extract_document_data(tlv_tree)
                for field_name, field_value in extracted_fields.items():
                    print(f"   {field_name}: {field_value}")
                save_to_excel(extracted_fields, card_data)
            except Exception as exc:
                logger.exception("TLV parse error")
                print(f"Ошибка парсинга: {exc}")
                save_to_excel({}, card_data)
        else:
            print("Не удалось прочитать данные")
    finally:
        try:
            connection.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    read_serbian_card()
    input("\nНажмите Enter для выхода...")
