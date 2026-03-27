"""
EBook Library Organizer Entry Point / Точка входа для EBook Library Organizer

Точка входа для запуска приложения EBook Library Organizer.

This module is safe to run either as a package (`python -m fb2parser`) or
directly as a file in an IDE (Run Python File). When run as a standalone file
the code will try several import strategies so `MainWindow` is imported
correctly regardless of current working directory or sys.path.
"""
import sys
import os

def _import_mainwindow():
    """
    Import and return MainWindow class using fallbacks.

    1. Try direct import from current directory first (PRIORITY!)
       This works when run as: python __main__.py or python -m fb2parser
    2. Try relative import as fallback for when imported as a module
    
    / Импортировать и вернуть класс MainWindow с использованием резервных вариантов.
    """
    # PRIORITY: Direct import from current directory
    repo_root = os.path.abspath(os.path.dirname(__file__))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    
    try:
        import gui_main
        # Force reload to avoid cached imports
        import importlib
        importlib.reload(gui_main)
        return gui_main.MainWindow
    except Exception:
        pass
    
    # Fallback: Try relative import (when imported as a module)
    try:
        from .gui_main import MainWindow
        return MainWindow
    except Exception:
        raise ImportError("Could not import MainWindow from gui_main")


def main():
    """
    Start the GUI application.
    
    / Запустить приложение GUI.
    """
    MainWindow = _import_mainwindow()
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
