"""
Logging Module / Модуль логирования

Handles logging of actions and errors.

/ Логирование действий и ошибок.
"""
from datetime import datetime

class Logger:
    """
    Simple in-memory logger.
    
    / Простой логгер в памяти.
    """
    
    def __init__(self):
        """Initialize logger / Инициализация логгера."""
        self.entries = []

    def log(self, message):
        """
        Log a message.
        
        / Залогировать сообщение.
        """
        entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        self.entries.append(entry)

    def get_entries(self):
        """
        Get last 1000 log entries.
        
        / Получить последние 1000 записей логов.
        """
        return self.entries[-1000:]  # Ограничение на размер лога

    def clear(self):
        """
        Clear all log entries.
        
        / Очистить все записи логов.
        """
        self.entries.clear()
