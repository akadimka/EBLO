#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protected Working Directory Manager

Хранит текущий рабочий каталог и защищает его от удаления.
Это глобальный модуль, доступный из любого места приложения.
"""

import os

# Глобальная переменная для защиты рабочего каталога
_protected_workdir = None


def set_protected_workdir(folder_path: str):
    """Установить рабочий каталог для защиты от удаления.
    
    Вызывается:
    - При старте приложения
    - При смене рабочего каталога через UI
    
    Args:
        folder_path: Путь к рабочему каталогу
    """
    global _protected_workdir
    
    if folder_path:
        # Нормализовать путь
        _protected_workdir = os.path.normpath(os.path.abspath(folder_path))
        print(f"[PROTECTED_WORKDIR] Set to: {_protected_workdir}")
    else:
        _protected_workdir = None
        print(f"[PROTECTED_WORKDIR] Cleared")


def get_protected_workdir() -> str:
    """Получить защищенный рабочий каталог.
    
    Returns:
        Path to protected working directory or None
    """
    return _protected_workdir


def is_protected(path: str) -> bool:
    """Проверить, является ли путь защищенным рабочим каталогом.
    
    Args:
        path: Путь для проверки
    
    Returns:
        True если путь совпадает с защищенным рабочим каталогом
    """
    if not path or not _protected_workdir:
        return False
    
    # Нормализовать для сравнения
    path_normalized = os.path.normpath(os.path.abspath(path))
    workdir_normalized = os.path.normpath(os.path.abspath(_protected_workdir))
    
    return path_normalized == workdir_normalized
