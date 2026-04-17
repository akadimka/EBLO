"""
Window state management utilities.

Provides functions to save and restore window geometry (size, position, state).
Supports multi-monitor setups correctly (virtual screen bounds via ctypes on Windows).
"""

import re
import tkinter as tk
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Virtual screen helpers (multi-monitor)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Application window group registry
# ---------------------------------------------------------------------------
# Все окна приложения регистрируются здесь в порядке открытия.
# При активации любого окна все остальные поднимаются, активированное — наверх.

_app_windows: list = []


def _register_app_window(window: tk.Tk) -> None:
    """Зарегистрировать окно в группе приложения."""
    if window not in _app_windows:
        _app_windows.append(window)

    def on_focus_in(event) -> None:
        # Реагируем только на фокус самого окна, не дочерних виджетов
        if event.widget is not window:
            return
        # Переставить окно в конец (самое свежее)
        try:
            _app_windows.remove(window)
        except ValueError:
            pass
        _app_windows.append(window)
        # Поднять все окна снизу вверх: старые первые, новое последним (поверх)
        for win in list(_app_windows):
            try:
                if win is not window and win.winfo_exists():
                    win.lift()
            except Exception:
                pass
        try:
            window.lift()
        except Exception:
            pass

    def on_destroy(event) -> None:
        if event.widget is window:
            try:
                _app_windows.remove(window)
            except ValueError:
                pass

    window.bind('<FocusIn>',  on_focus_in,  add=True)
    window.bind('<Destroy>',  on_destroy,   add=True)


def _setup_taskbar(window: tk.Tk) -> None:
    """Гарантировать, что кнопка окна в Панели задач появится на мониторе окна.

    Добавляет стиль WS_EX_APPWINDOW, не трогая owner-связь (она нужна для
    группировки окон приложения при переключении через Панель задач).
    Безопасно на не-Windows: исключения перехватываются.
    """
    try:
        import sys
        if sys.platform != 'win32':
            return
        import ctypes
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        GWL_EXSTYLE    = -20
        WS_EX_APPWINDOW = 0x00040000
        current = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current | WS_EX_APPWINDOW)
    except Exception:
        pass


def _get_virtual_screen_bounds() -> Tuple[int, int, int, int]:
    """Return (x, y, width, height) of the virtual screen spanning all monitors.

    On Windows uses ctypes GetSystemMetrics; falls back to (0, 0, 0, 0) on
    other platforms (caller must use screen_width/height from winfo then).
    """
    try:
        import ctypes
        u32 = ctypes.windll.user32
        vx = u32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = u32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        vw = u32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        vh = u32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        if vw > 0 and vh > 0:
            return vx, vy, vw, vh
    except Exception:
        pass
    return 0, 0, 0, 0


def _parse_geometry(geometry_str: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse "WxH+X+Y" (with possible negative coords) → (w, h, x, y) or None."""
    try:
        geometry_str = re.sub(r'\+-', '-', geometry_str)
        m = re.match(r'(\d+)x(\d+)([\+\-])(\d+)([\+\-])(\d+)', geometry_str)
        if not m:
            return None
        w = int(m.group(1))
        h = int(m.group(2))
        x = int(m.group(4)) * (1 if m.group(3) == '+' else -1)
        y = int(m.group(6)) * (1 if m.group(5) == '+' else -1)
        return w, h, x, y
    except Exception:
        return None


def _is_geometry_visible(geometry_str: str, window) -> bool:
    """Return True if the window (or at least its title bar) is visible on any monitor.

    Uses the Windows virtual screen so windows on secondary monitors (left/right/above)
    are correctly recognised as visible.
    """
    try:
        parsed = _parse_geometry(geometry_str)
        if not parsed:
            return False
        w, h, x, y = parsed

        if w < 200 or h < 100:
            return False

        # Try Windows virtual screen first
        vx, vy, vw, vh = _get_virtual_screen_bounds()
        if vw > 0:
            # Allow a 50-px margin so partially off-screen windows are still OK
            margin = 50
            vs_left   = vx - margin
            vs_top    = vy - margin
            vs_right  = vx + vw + margin
            vs_bottom = vy + vh + margin
        else:
            # Fallback: primary screen only
            try:
                sw = window.winfo_screenwidth()
                sh = window.winfo_screenheight()
            except Exception:
                sw, sh = 1920, 1080
            margin = 200
            vs_left, vs_top = -margin, -margin
            vs_right, vs_bottom = sw + margin, sh + margin

        # Window is visible if it intersects the virtual desktop
        win_right  = x + w
        win_bottom = y + h
        return not (win_right  < vs_left  or
                    x          > vs_right or
                    win_bottom < vs_top   or
                    y          > vs_bottom)

    except Exception:
        return True   # optimistic fallback


# ---------------------------------------------------------------------------
# Parent-relative default geometry
# ---------------------------------------------------------------------------

def _default_geometry_near_parent(parent: tk.Tk,
                                  width: int,
                                  height: int,
                                  offset_x: int = 60,
                                  offset_y: int = 40) -> str:
    """Return a geometry string placing the window on the same monitor as *parent*.

    If *parent* is not available or its position cannot be determined,
    falls back to "+100+100".
    """
    try:
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        # Clamp so the new window stays fully inside the virtual screen (best-effort)
        vx, vy, vw, vh = _get_virtual_screen_bounds()
        if vw > 0:
            nx = max(vx, min(px + offset_x, vx + vw - width))
            ny = max(vy, min(py + offset_y, vy + vh - height))
        else:
            nx = px + offset_x
            ny = py + offset_y
        return f"{width}x{height}+{nx}+{ny}"
    except Exception:
        return f"{width}x{height}+100+100"


# ---------------------------------------------------------------------------
# Core save / restore
# ---------------------------------------------------------------------------

def save_window_geometry(window: tk.Tk, window_name: str, settings_manager) -> None:
    """Save window geometry (position, size, state) to settings."""
    try:
        geometry = re.sub(r'\+-', '-', window.geometry())
        state = window.state()

        if state == 'withdrawn':
            state = 'normal'
        if state == 'zoomed':
            state = 'maximized'

        window_data = {'geometry': geometry, 'state': state}
        settings_manager.set_window_geometry(window_name, window_data)
    except Exception:
        pass


def _validated_geometry(geom_str: Optional[str], window) -> Optional[str]:
    """Return cleaned geometry string if valid and visible, else None."""
    if not geom_str:
        return None
    geom_str = re.sub(r'\+-', '-', geom_str)
    parsed = _parse_geometry(geom_str)
    if not parsed:
        return None
    w, h, x, y = parsed
    if w < 200 or h < 100:
        return None
    if not _is_geometry_visible(geom_str, window):
        return None
    return geom_str


def restore_window_geometry(window: tk.Tk,
                            window_name: str,
                            settings_manager,
                            default_geometry: Optional[str] = None,
                            default_state: str = 'normal',
                            parent_window: Optional[tk.Tk] = None) -> bool:
    """Restore saved window geometry.

    If no geometry is saved and *parent_window* is given, the window is placed
    on the same monitor as *parent_window* (size taken from *default_geometry*).

    Returns True if saved geometry was applied, False if defaults were used.
    """
    try:
        window_data = settings_manager.get_window_geometry(window_name)

        def apply_state(state: str) -> None:
            if state == 'maximized':
                state = 'zoomed'
            try:
                window.state(state)
                window.update_idletasks()
            except tk.TclError:
                try:
                    window.state(default_state)
                except Exception:
                    pass

        def apply_geometry(geom: Optional[str], fallback: Optional[str] = None) -> None:
            valid = _validated_geometry(geom, window) if geom else None
            if not valid:
                valid = _validated_geometry(fallback, window) if fallback else None
            if valid:
                try:
                    window.geometry(valid)
                except tk.TclError:
                    pass

        # ── No saved data ──────────────────────────────────────────────────
        if window_data is None:
            if parent_window is not None and default_geometry:
                # Derive size from default, position from parent's monitor
                parsed = _parse_geometry(default_geometry)
                if parsed:
                    w, h, _, _ = parsed
                    near_geom = _default_geometry_near_parent(parent_window, w, h)
                    apply_geometry(near_geom, default_geometry)
                else:
                    apply_geometry(default_geometry)
            elif default_geometry:
                apply_geometry(default_geometry)
            apply_state(default_state)
            return False

        # ── Old format: plain string ───────────────────────────────────────
        if isinstance(window_data, str):
            apply_geometry(window_data, default_geometry)
            apply_state(default_state)
            return True

        # ── New format: dict ───────────────────────────────────────────────
        if isinstance(window_data, dict):
            geometry = window_data.get('geometry', default_geometry)
            state    = window_data.get('state',    default_state)

            if state in ('zoomed', 'maximized', 'iconic'):
                apply_geometry(geometry, default_geometry)
                apply_state(state)
            else:
                apply_geometry(geometry, default_geometry)
                apply_state(state)
            return True

        return False

    except Exception:
        if default_geometry:
            try:
                window.geometry(default_geometry)
            except Exception:
                pass
        return False


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _apply_window_state(window: tk.Tk, state: str, default_state: str) -> None:
    """Safely apply window state."""
    try:
        window.state(state)
    except tk.TclError:
        try:
            window.state(default_state)
        except Exception:
            pass


def center_window_on_parent(window: tk.Toplevel,
                            parent: tk.Tk,
                            width: int = 400,
                            height: int = 300) -> str:
    """Return geometry string centering *window* on *parent*."""
    try:
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        cx = px + (pw - width)  // 2
        cy = py + (ph - height) // 2
        # Keep at least 50 px on-screen (use virtual screen bounds)
        vx, vy, vw, vh = _get_virtual_screen_bounds()
        if vw > 0:
            cx = max(vx, min(cx, vx + vw - width  + 50))
            cy = max(vy, min(cy, vy + vh - height + 50))
        return f"{width}x{height}+{cx}+{cy}"
    except Exception:
        return f"{width}x{height}+200+200"


def _show_at_position(window: tk.Tk) -> None:
    """Показать окно в правильной позиции без мигания.

    Если окно было скрыто (withdrawn) — делаем его прозрачным, снимаем
    withdrawn-состояние (deiconify), применяем геометрию, потом убираем
    прозрачность.  Win32 уважает geometry() только для видимого окна,
    поэтому withdraw/deiconify не работает надёжно на multi-monitor.
    """
    try:
        import sys
        if sys.platform == 'win32':
            was_withdrawn = (window.state() == 'withdrawn')
            window.wm_attributes('-alpha', 0)
            if was_withdrawn:
                window.deiconify()
            window.update_idletasks()
            # geometry уже применена — просто показываем
            window.wm_attributes('-alpha', 1)
            return
    except Exception:
        pass
    # Fallback для не-Windows
    if window.state() == 'withdrawn':
        window.deiconify()


def setup_window_persistence(window: tk.Tk,
                             window_name: str,
                             settings_manager,
                             default_geometry: Optional[str] = None,
                             parent_window: Optional[tk.Tk] = None) -> None:
    """Attach geometry persistence to *window*.

    • Restores saved geometry (or places near *parent_window* if first open).
    • Saves geometry when the window is closed via WM_DELETE_WINDOW.

    Использует alpha=0/1 вместо withdraw/deiconify — Win32 надёжно соблюдает
    geometry() только для видимого (пусть и прозрачного) окна.
    """
    # Скрываем прозрачностью (не withdraw) чтобы Win32 уважал geometry()
    try:
        import sys
        if sys.platform == 'win32':
            window.wm_attributes('-alpha', 0)
            # Если окно было withdrawn (из __init__) — показываем прозрачным
            if window.state() == 'withdrawn':
                window.deiconify()
    except Exception:
        window.withdraw()

    restore_window_geometry(window, window_name, settings_manager,
                            default_geometry, parent_window=parent_window)
    window.update_idletasks()
    _setup_taskbar(window)
    _register_app_window(window)

    # Показываем уже в правильной позиции
    try:
        import sys
        if sys.platform == 'win32':
            window.wm_attributes('-alpha', 1)
            return
    except Exception:
        pass
    window.deiconify()

    def on_close() -> None:
        save_window_geometry(window, window_name, settings_manager)
        window.destroy()

    window.protocol('WM_DELETE_WINDOW', on_close)


def create_toplevel_with_persistence(parent: tk.Tk,
                                     window_name: str,
                                     settings_manager,
                                     default_geometry: Optional[str] = None,
                                     on_close_callback=None,
                                     **toplevel_kwargs) -> tk.Toplevel:
    """Create a Toplevel with automatic geometry persistence.

    New windows (no saved position) open near *parent*.
    """
    dlg = tk.Toplevel(parent)

    # Скрываем прозрачностью — Win32 уважает geometry() только для visible окна
    try:
        import sys
        if sys.platform == 'win32':
            dlg.wm_attributes('-alpha', 0)
        else:
            dlg.withdraw()
    except Exception:
        dlg.withdraw()

    for key, value in toplevel_kwargs.items():
        if key == 'title':
            dlg.title(value)
        elif key == 'geometry':
            dlg.geometry(value)

    restore_window_geometry(dlg, window_name, settings_manager,
                            default_geometry, parent_window=parent)
    dlg.update_idletasks()
    _setup_taskbar(dlg)
    _register_app_window(dlg)

    try:
        import sys
        if sys.platform == 'win32':
            dlg.wm_attributes('-alpha', 1)
        else:
            dlg.deiconify()
    except Exception:
        dlg.deiconify()

    def on_close() -> None:
        save_window_geometry(dlg, window_name, settings_manager)
        if on_close_callback:
            on_close_callback()
        dlg.destroy()

    def on_destroy(event=None) -> None:
        if dlg.winfo_exists():
            save_window_geometry(dlg, window_name, settings_manager)
            if on_close_callback:
                on_close_callback()

    dlg.bind('<Destroy>', on_destroy, add=True)
    dlg.protocol('WM_DELETE_WINDOW', on_close)

    return dlg
