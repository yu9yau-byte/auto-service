#!/usr/bin/env python3
"""
✅ ТЕСТ: Проверка исправления Race Condition в многопоточности
Этот тест создаёт несколько потоков и одновременно добавляет данные в БД.
Если операции будут безопасными, то все данные сохранятся корректно.
"""

import threading
import tempfile
import os
import time
from database import ServiceDatabase

def test_thread_safety():
    """Тест потокобезопасности БД"""
    print("\n" + "="*70)
    print("🧪 ТЕСТ: Потокобезопасность операций с БД")
    print("="*70)
    
    # Создаём временную БД для теста
    handle, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(handle)
    
    try:
        db = ServiceDatabase(db_path)
        print(f"\n✅ БД создана: {db_path}")
        print(f"✅ Мьютекс инициализирован: {db._db_lock}")
        
        # Параметры теста
        num_threads = 5
        clients_per_thread = 10
        total_expected = num_threads * clients_per_thread
        
        print(f"\n📊 Параметры теста:")
        print(f"   • Потоков: {num_threads}")
        print(f"   • Клиентов на поток: {clients_per_thread}")
        print(f"   • Всего ожидается: {total_expected} клиентов")
        
        errors = []
        
        def add_clients(thread_id):
            """Добавляет клиентов в БД из отдельного потока"""
            try:
                for i in range(clients_per_thread):
                    client_name = f"Клиент-{thread_id}-{i}"
                    client_id = db.add_client(
                        full_name=client_name,
                        phone=f"+381-{thread_id}-{i}",
                        email=f"client{thread_id}_{i}@test.com"
                    )
                    print(f"   ✅ Поток {thread_id}: добавлен клиент #{client_id} '{client_name}'")
                    time.sleep(0.01)  # Небольшая задержка для усиления конфликтов
            except Exception as e:
                errors.append((thread_id, str(e)))
                print(f"   ❌ Поток {thread_id}: ОШИБКА - {e}")
        
        # Запускаем потоки
        print(f"\n🚀 Запуск {num_threads} потоков...")
        threads = []
        start_time = time.time()
        
        for i in range(num_threads):
            thread = threading.Thread(target=add_clients, args=(i,), name=f"Worker-{i}")
            threads.append(thread)
            thread.start()
        
        # Ждём завершения всех потоков
        for thread in threads:
            thread.join()
        
        elapsed = time.time() - start_time
        print(f"\n✅ Все потоки завершены за {elapsed:.2f} сек")
        
        # Проверяем результаты
        print(f"\n📋 Проверка результатов:")
        all_clients = db.get_all_clients()
        actual_count = len(all_clients)
        
        print(f"   • Добавлено клиентов: {actual_count}")
        print(f"   • Ожидалось: {total_expected}")
        
        if errors:
            print(f"\n❌ ОШИБКИ ({len(errors)}):")
            for thread_id, error in errors:
                print(f"   • Поток {thread_id}: {error}")
        
        if actual_count == total_expected and not errors:
            print(f"\n✅ ТЕСТ ПРОЙДЕН! Все {total_expected} клиентов добавлены безопасно.")
            return True
        else:
            print(f"\n❌ ТЕСТ НЕ ПРОЙДЕН!")
            print(f"   Ожидалось: {total_expected}, получено: {actual_count}")
            return False
            
    finally:
        db.close()
        try:
            os.remove(db_path)
            print(f"\n🗑️  Временная БД удалена: {db_path}")
        except Exception as e:
            print(f"\n⚠️  Не удалось удалить БД: {e}")

def test_context_manager():
    """Тест контекстного менеджера для соединений"""
    print("\n" + "="*70)
    print("🧪 ТЕСТ: Контекстный менеджер get_connection()")
    print("="*70)
    
    handle, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(handle)
    
    try:
        db = ServiceDatabase(db_path)
        
        print("\n✅ Тест 1: Успешная операция (COMMIT)")
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO clients (full_name, phone)
                    VALUES (?, ?)
                ''', ("Тестовый клиент", "+381-123-456"))
                # Контекстный менеджер должен сделать COMMIT
        except Exception as e:
            print(f"❌ ОШИБКА: {e}")
            return False
        
        # Проверим, что данные сохранились
        clients = db.get_all_clients()
        if len(clients) == 1:
            print(f"✅ Данные успешно сохранены в БД")
        else:
            print(f"❌ Данные не сохранились!")
            return False
        
        print("\n✅ Тест 2: Обработка исключения (ROLLBACK)")
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO clients (full_name, phone)
                    VALUES (?, ?)
                ''', ("Второй клиент", "+381-999-999"))
                # Вызываем ошибку - должен быть ROLLBACK
                raise ValueError("Тестовая ошибка")
        except ValueError:
            print(f"✅ Исключение обработано, должен быть ROLLBACK")
        
        # Проверим, что второй клиент не добавлен
        clients = db.get_all_clients()
        if len(clients) == 1:
            print(f"✅ Откат сработал, второй клиент не добавлен")
        else:
            print(f"❌ ROLLBACK не сработал, клиентов: {len(clients)}")
            return False
        
        print(f"\n✅ ТЕСТ ПРОЙДЕН! Контекстный менеджер работает правильно.")
        return True
        
    finally:
        db.close()
        try:
            os.remove(db_path)
        except:
            pass

if __name__ == "__main__":
    print("\n" + "█"*70)
    print("█ 🔒 ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЙ RACE CONDITION")
    print("█"*70)
    
    # Тест 1: Многопоточность
    test1_passed = test_thread_safety()
    
    # Тест 2: Контекстный менеджер
    test2_passed = test_context_manager()
    
    # Итоги
    print("\n" + "█"*70)
    print("█ ИТОГИ ТЕСТИРОВАНИЯ")
    print("█"*70)
    
    print(f"\n1️⃣  Тест потокобезопасности:    {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"2️⃣  Тест контекстного менеджера: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print(f"\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Race Condition исправлена!")
        exit(0)
    else:
        print(f"\n⚠️  НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ")
        exit(1)
