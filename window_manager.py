"""
Window Manager - управление иерархией и фокусом окон.

Обеспечивает:
- Правильную иерархию окон (модальность)
- Передачу фокуса при открытии/закрытии окна
- Стек открытых окон для корректного восстановления фокуса
"""

import tkinter as tk
from typing import Optional, List, Callable


class WindowManager:
    """Менеджер для управления иерархией и фокусом окон."""
    
    def __init__(self):
        """Инициализация менеджера окон."""
        self._window_stack: List[tk.Widget] = []
        self._window_callbacks: dict = {}  # window_id -> cleanup_callback
    
    def register_main_window(self, main_window: tk.Tk) -> None:
        """Зарегистрировать главное окно.
        
        Args:
            main_window: Главное окно приложения (tk.Tk)
        """
        self._window_stack = [main_window]
    
    def open_child_window(self, parent: tk.Widget, child: tk.Toplevel, 
                         on_close: Optional[Callable] = None) -> None:
        """Открыть дочернее окно с передачей фокуса.
        
        Args:
            parent: Родительское окно
            child: Открываемое дочернее окно (tk.Toplevel)
            on_close: Опциональный callback при закрытии окна
        """
        # Добавить окно в стек
        self._window_stack.append(child)
        
        # Сохранить callback если есть
        if on_close:
            window_id = id(child)
            self._window_callbacks[window_id] = on_close
        
        # Установить модальность
        child.grab_set()
        child.transient(parent)
        
        # Перенести фокус на новое окно
        child.focus_set()
        child.lift()
        
        # Завязать обработчик закрытия окна
        child.protocol('WM_DELETE_WINDOW', lambda: self._close_window(child))
    
    def _close_window(self, window: tk.Toplevel) -> None:
        """Закрыть окно и вернуть фокус предыдущему.
        
        Args:
            window: Закрываемое окно
        """
        window_id = id(window)
        
        # Вызвать callback если он был зарегистрирован
        if window_id in self._window_callbacks:
            try:
                self._window_callbacks[window_id]()
            except Exception as e:
                print(f"Error in window close callback: {e}")
            finally:
                del self._window_callbacks[window_id]
        
        # Удалить окно из стека
        if window in self._window_stack:
            self._window_stack.remove(window)
        
        # Закрыть окно
        try:
            window.destroy()
        except tk.TclError:
            pass  # Окно уже закрыто
        
        # Вернуть фокус на предыдущее окно
        if self._window_stack:
            previous_window = self._window_stack[-1]
            try:
                # Release grab from closed window first
                previous_window.grab_release()
                # Set grab on previous window
                previous_window.grab_set()
                # Set focus
                previous_window.focus_set()
                previous_window.lift()
            except tk.TclError:
                pass  # Window already destroyed
    
    def close_window(self, window: tk.Toplevel) -> None:
        """Публичный метод для закрытия окна через менеджер.
        
        Args:
            window: Закрываемое окно
        """
        self._close_window(window)
    
    def get_current_window(self) -> Optional[tk.Widget]:
        """Получить текущее активное окно.
        
        Returns:
            Текущее окно или None
        """
        return self._window_stack[-1] if self._window_stack else None
    
    def get_window_stack(self) -> List[tk.Widget]:
        """Получить стек окон (для отладки).
        
        Returns:
            Копия стека окон
        """
        return self._window_stack.copy()


# Глобальный экземпляр менеджера
_window_manager: Optional[WindowManager] = None


def get_window_manager() -> WindowManager:
    """Получить глобальный экземпляр менеджера окон.
    
    Returns:
        Глобальный WindowManager
    """
    global _window_manager
    if _window_manager is None:
        _window_manager = WindowManager()
    return _window_manager
