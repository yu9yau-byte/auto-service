#!/usr/bin/env python3
"""
Проверка синтаксиса database.py
"""

import py_compile
import sys

try:
    py_compile.compile('database.py', doraise=True)
    print("✅ database.py - синтаксис OK")
    sys.exit(0)
except py_compile.PyCompileError as e:
    print(f"❌ Ошибка синтаксиса в database.py:")
    print(e)
    sys.exit(1)
