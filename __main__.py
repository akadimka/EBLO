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
    Import and return MainWindow class using a few fallbacks.

    1. Try direct import from current directory first (PRIORITY!)
    2. Try normal package import `from fb2parser.gui_main import MainWindow`.
    3. If that fails, ensure parent of repository root is on sys.path and retry.
    4. As a last resort, load `gui_main.py` directly from the repository path.
    
    / Импортировать и вернуть класс MainWindow с использованием нескольких резервных вариантов.
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
    
    # Fallback to package import
    try:
        from fb2parser.gui_main import MainWindow
        return MainWindow
    except Exception:
        pass

    # Try adding parent dir of the repo to sys.path so package import can work
    parent = os.path.dirname(repo_root)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    try:
        from fb2parser.gui_main import MainWindow
        return MainWindow
    except Exception:
        pass

    # Last resort: import the gui_main module directly from file path
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("fb2parser.gui_main.local", os.path.join(repo_root, 'gui_main.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, 'MainWindow')
    except Exception:
        raise


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
