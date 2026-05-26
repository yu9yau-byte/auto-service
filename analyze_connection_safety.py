#!/usr/bin/env python3
"""
ДИАГНОСТИЧЕСКИЙ СКРИПТ для проверки утечки соединений

Анализирует все методы database.py и показывает:
1. Какие методы используют старый паттерн
2. Какие методы используют новый паттерн (безопасный)
3. Рекомендации по рефакторингу
"""

import re
from pathlib import Path
from collections import defaultdict


def analyze_database_py():
    """Анализировать database.py на утечку соединений"""
    
    db_path = Path("database.py")
    if not db_path.exists():
        print(f"❌ Файл не найден: {db_path}")
        return
    
    with open(db_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Найти все методы
    method_pattern = r'def (\w+)\(self[^)]*\):[^\n]*\n((?:[^\n]*\n(?!    def ))*)'
    methods = re.findall(method_pattern, content)
    
    print("="*70)
    print("🔍 АНАЛИЗ МЕТОДОВ DATABASE.PY НА УТЕЧКУ СОЕДИНЕНИЙ")
    print("="*70)
    
    safe_methods = []      # Используют get_connection()
    unsafe_methods = []    # Используют self.connect()
    readonly_methods = []  # Только читают (SELECT)
    
    for method_name, method_body in methods:
        if method_name.startswith('_'):
            continue  # Пропустить приватные методы
        
        # Проверка: uses get_connection()?
        if 'with self.get_connection()' in method_body:
            safe_methods.append(method_name)
        # Проверка: uses self.connect()?
        elif 'self.connect()' in method_body:
            # Проверка: это read-only или write?
            if 'SELECT' in method_body and 'INSERT' not in method_body and 'UPDATE' not in method_body:
                readonly_methods.append((method_name, 'SELECT'))
            else:
                unsafe_methods.append(method_name)
        elif 'SELECT' in method_body and 'self.connection' not in method_body:
            readonly_methods.append((method_name, 'другое'))
    
    print(f"\n✅ БЕЗОПАСНЫЕ МЕТОДЫ ({len(safe_methods)} методов)")
    print("   Используют get_connection() (контекстный менеджер):")
    for m in sorted(safe_methods):
        print(f"   ✓ {m}()")
    
    print(f"\n⚠️  НЕБЕЗОПАСНЫЕ МЕТОДЫ ({len(unsafe_methods)} методов)")
    print("   Используют self.connect() (старый паттерн):")
    print("   ДЕЙСТВИЕ: Рефакторить на get_connection()")
    for m in sorted(unsafe_methods):
        print(f"   ✗ {m}()")
    
    print(f"\n📖 МЕТОДЫ ТОЛЬКО ДЛЯ ЧТЕНИЯ ({len(readonly_methods)} методов)")
    print("   Безопасны, не требуют рефакторинга:")
    for m, typ in sorted(readonly_methods):
        print(f"   ○ {m}() [{typ}]")
    
    print("\n" + "="*70)
    print("📊 СТАТИСТИКА")
    print("="*70)
    print(f"Всего методов:     {len(safe_methods) + len(unsafe_methods) + len(readonly_methods)}")
    print(f"Безопасных:        {len(safe_methods):3d} ✅")
    print(f"Небезопасных:      {len(unsafe_methods):3d} ⚠️ ")
    print(f"Только чтение:     {len(readonly_methods):3d} ○")
    
    total_problematic = len(unsafe_methods)
    if total_problematic > 0:
        print(f"\n⚠️  ТРЕБУЮТ РЕФАКТОРИНГА: {total_problematic} методов")
        print("   Рекомендуемый порядок:")
        print("   1. Проверить какие методы вызывают чаще всего")
        print("   2. Переделать на with self.get_connection() as conn:")
        print("   3. Убрать conn = self.connect() и self.close()")
        print("   4. Запустить тесты после каждого изменения")
    else:
        print("\n✅ ВСЕ МЕТОДЫ БЕЗОПАСНЫ! Утечка соединений исправлена.")
    
    # Проверка: есть ли все импорты?
    print("\n" + "="*70)
    print("🔧 ПРОВЕРКА НЕОБХОДИМЫХ ЭЛЕМЕНТОВ")
    print("="*70)
    
    checks = [
        ('import contextlib', 'Контекстный менеджер'),
        ('_db_lock = threading.RLock()', 'Мьютекс для потокобезопасности'),
        ('_active_connections', 'Отслеживание активных соединений'),
        ('_connection_counter', 'Счетчик соединений'),
        ('def get_connection(self):', 'Метод get_connection()'),
        ('def get_connection_stats(self):', 'Метод get_connection_stats()'),
        ('def log_connection_stats(self):', 'Метод log_connection_stats()'),
    ]
    
    for check_str, desc in checks:
        if check_str in content:
            print(f"✅ {desc}")
        else:
            print(f"❌ {desc} - ОТСУТСТВУЕТ")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    analyze_database_py()
