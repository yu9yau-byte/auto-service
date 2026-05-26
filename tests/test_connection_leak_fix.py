#!/usr/bin/env python3
"""
TEST SUITE для проверки исправления утечки соединений БД

🎯 Цель: убедиться что после 1000+ операций не будет "Database is locked"
Признаки утечки ДО ИСПРАВЛЕНИЯ:
  - Каждый вызов connect()+close() оставляет соединение открытым
  - После ~1000 операций: ошибка "database is locked"
  - SQLite имеет лимит одновременных соединений

✅ После исправления:
  - get_connection() с контекстным менеджером гарантирует close()
  - Число открытых соединений остается < 10
  - 10000+ операций выполняются без ошибок
"""

import logging
import sqlite3
import tempfile
from pathlib import Path
import time

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импортируем класс БД (используя временный файл для теста)
import sys
sys.path.insert(0, str(Path(__file__).parent))

from database import ServiceDatabase


def test_connection_leak_old_pattern():
    """
    ❌ ДЕМОНСТРАЦИЯ: старый паттерн вызывает утечку
    
    Этот тест показывает проблему:
        conn = self.connect()
        ...
        self.close()  # ← Только закрывает self.connection, но могут быть другие
    """
    print("\n" + "="*60)
    print("❌ TEST 1: Демонстрация утечки (старый паттерн)")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_leak.db"
        db = ServiceDatabase(str(db_path))
        
        # Simulate старый паттерн
        print("\nЭмулируем старый паттерн (conn = self.connect() ... self.close()):")
        for i in range(50):
            conn = db.connect()  # ← каждый раз новое соединение
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            db.close()  # ← только закрывает self.connection
            
            if (i + 1) % 10 == 0:
                stats = db.get_connection_stats()
                print(f"  Итерация {i+1}: активных соединений = {stats['currently_active']}")
        
        final_stats = db.get_connection_stats()
        print(f"\n✅ Финальная статистика (старый паттерн):")
        print(f"   Всего создано: {final_stats['total_created']}")
        print(f"   Активных сейчас: {final_stats['currently_active']}")
        print(f"   ⚠️  УТЕЧКА ОБНАРУЖЕНА: {final_stats['is_leaking']}")
        
        db.log_connection_stats()


def test_connection_leak_new_pattern():
    """
    ✅ ИСПРАВЛЕНИЕ: новый паттерн с контекстным менеджером
    
    Этот тест показывает исправление:
        with db.get_connection() as conn:
            ...
            # ← автоматически conn.close() в finally
    """
    print("\n" + "="*60)
    print("✅ TEST 2: Исправленный паттерн (контекстный менеджер)")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_no_leak.db"
        db = ServiceDatabase(str(db_path))
        
        print("\nИспользуем новый паттерн (with db.get_connection() as conn:):")
        for i in range(100):
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
            except Exception as e:
                logger.error("Error in iteration %d: %s", i+1, e)
                raise
            
            if (i + 1) % 20 == 0:
                stats = db.get_connection_stats()
                print(f"  Итерация {i+1}: активных соединений = {stats['currently_active']}")
        
        final_stats = db.get_connection_stats()
        print(f"\n✅ Финальная статистика (новый паттерн):")
        print(f"   Всего создано: {final_stats['total_created']}")
        print(f"   Активных сейчас: {final_stats['currently_active']}")
        print(f"   ⚠️  УТЕЧКА ОБНАРУЖЕНА: {final_stats['is_leaking']}")
        
        db.log_connection_stats()
        
        assert final_stats['currently_active'] == 0, "❌ Соединения не были закрыты!"
        assert not final_stats['is_leaking'], "❌ Обнаружена утечка!"
        print("\n✅ ТЕСТ ПРОЙДЕН: нет утечки соединений!")


def test_high_volume_operations():
    """
    🔥 СТРЕСС-ТЕСТ: 5000+ операций с новым паттерном
    
    Цель: убедиться что даже при высокой нагрузке не будет
    ошибки "database is locked"
    """
    print("\n" + "="*60)
    print("🔥 TEST 3: Стресс-тест (5000+ операций)")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_stress.db"
        db = ServiceDatabase(str(db_path))
        
        # Добавим тестовую таблицу
        with db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS test_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    value TEXT,
                    timestamp REAL
                )
            """)
        
        print("\nВыполняем 5000 операций INSERT/SELECT...")
        start_time = time.time()
        errors = []
        
        for i in range(5000):
            try:
                # Write
                with db.get_connection() as conn:
                    conn.execute(
                        "INSERT INTO test_data (value, timestamp) VALUES (?, ?)",
                        (f"test_{i}", time.time())
                    )
                
                # Read
                if i % 10 == 0:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM test_data")
                        count = cursor.fetchone()[0]
                
            except Exception as e:
                errors.append(f"Операция {i}: {e}")
                if "database is locked" in str(e):
                    logger.error("❌ УТЕЧКА ОБНАРУЖЕНА: database is locked после %d операций", i)
                    raise
            
            if (i + 1) % 500 == 0:
                stats = db.get_connection_stats()
                elapsed = time.time() - start_time
                ops_per_sec = (i + 1) / elapsed
                print(f"  {i+1}/5000: активных соединений = {stats['currently_active']}, "
                      f"скорость = {ops_per_sec:.0f} ops/sec")
        
        elapsed = time.time() - start_time
        final_stats = db.get_connection_stats()
        
        print(f"\n✅ Стресс-тест завершен за {elapsed:.2f} сек ({5000/elapsed:.0f} ops/sec)")
        print(f"   Всего создано соединений: {final_stats['total_created']}")
        print(f"   Активных сейчас: {final_stats['currently_active']}")
        
        if errors:
            print(f"\n❌ Ошибок: {len(errors)}")
            for err in errors[:5]:
                print(f"   - {err}")
        else:
            print(f"\n✅ Ошибок: 0")
        
        assert not errors, "❌ Есть ошибки при выполнении операций!"
        assert final_stats['currently_active'] == 0, "❌ Соединения остались открытыми!"
        print("\n✅ ТЕСТ ПРОЙДЕН: высокая нагрузка обработана успешно!")


def test_connection_stats_reporting():
    """
    📊 TEST 4: Проверка отчетности статистики
    """
    print("\n" + "="*60)
    print("📊 TEST 4: Отчетность статистики соединений")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_stats.db"
        db = ServiceDatabase(str(db_path))
        
        # Test 1: пусто
        stats = db.get_connection_stats()
        print(f"\nПосле инициализации:")
        print(f"   {stats}")
        
        # Test 2: открыть временное соединение
        print(f"\nОтрываем 5 временных соединений...")
        conns = []
        for i in range(5):
            with db.get_connection() as conn:
                conns.append(conn)
            stats = db.get_connection_stats()
            print(f"   Итерация {i+1}: активных = {stats['currently_active']}")
        
        # Test 3: финал
        final_stats = db.get_connection_stats()
        print(f"\nИтоговая статистика:")
        db.log_connection_stats()
        
        assert final_stats['currently_active'] == 0, "❌ Соединения остались открытыми!"
        print("\n✅ ТЕСТ ПРОЙДЕН: статистика корректна!")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("DATABASE CONNECTION LEAK FIX - TEST SUITE")
    print("="*60)
    
    try:
        test_connection_leak_old_pattern()
        test_connection_leak_new_pattern()
        test_high_volume_operations()
        test_connection_stats_reporting()
        
        print("\n" + "="*60)
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        print("="*60)
        print("\n📝 ВЫВОДЫ:")
        print("   ✅ Новый паттерн (get_connection) безопасен от утечек")
        print("   ✅ Даже при 5000+ операциях нет утечек")
        print("   ✅ Статистика корректно отслеживается")
        print("   ✅ Нет ошибок 'database is locked'")
        
    except AssertionError as e:
        print(f"\n❌ ТЕСТ ПРОВАЛЕН: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
