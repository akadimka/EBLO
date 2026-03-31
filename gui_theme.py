#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тема и визуальные настройки приложения.

Применяет единый стиль ко всем ttk-виджетам.
Совместим со стандартным tkinter — внешние зависимости не требуются.

Дополнительно поддерживает sv_ttk (Sun Valley, Windows-11-стиль):
    pip install sv-ttk
Если sv_ttk не установлен, применяется встроенная тема на базе clam.
"""

import tkinter as tk
from tkinter import ttk
import sys

# ── Цветовая палитра (Windows-11 light) ──────────────────────────────────────
ACCENT      = "#0067C0"   # Microsoft blue
ACCENT_DARK = "#004E9A"   # Нажатая кнопка / заголовок
ACCENT_LIGHT= "#CCE4F7"   # Фон выделенной строки
BG          = "#F3F3F3"   # Фон окна
BG_ELEM     = "#FFFFFF"   # Фон виджетов (Entry, Treeview)
BG_HOVER    = "#E8E8E8"   # Hover фон кнопки
FG          = "#1A1A1A"   # Основной текст
FG_MUTED    = "#767676"   # Второстепенный текст
BORDER      = "#C8C8C8"   # Граница
ROW_ODD     = "#FFFFFF"   # Нечётная строка Treeview
ROW_EVEN    = "#F0F5FB"   # Чётная строка Treeview (едва заметный синеватый)
SEL_BG      = "#CCE4F7"   # Фон выделения
SEL_FG      = "#003D7A"   # Текст выделения
HDR_BG      = "#E4EBF4"   # Фон заголовков Treeview
HDR_FG      = "#333333"   # Текст заголовков
STATUS_OK   = "#2E7D32"   # Зелёный — готово
STATUS_BUSY = "#E65100"   # Оранжевый — в процессе
STATUS_ERR  = "#C62828"   # Красный — ошибка

FONT_NORMAL = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_SMALL  = ("Segoe UI", 9)
FONT_HDR    = ("Segoe UI", 9, "bold")


def apply_theme(root: tk.Tk) -> bool:
    """Применить тему к корневому окну и всем дочерним виджетам.

    Возвращает True если удалось загрузить sv_ttk (Windows-11 тема),
    False — использована встроенная тема.
    """
    # Попытка использовать Sun Valley (Windows 11 Fluent Design)
    try:
        import sv_ttk  # type: ignore
        sv_ttk.set_theme("light")
        _apply_extra_styles()  # поверх sv_ttk: шрифты + row-colors
        return True
    except ImportError:
        pass

    # Встроенная тема на базе clam
    style = ttk.Style(root)
    style.theme_use("clam")
    _build_clam_theme(style)
    return False


def _build_clam_theme(style: ttk.Style) -> None:
    """Настроить clam-тему под современный вид."""

    # ── Глобально: шрифт ────────────────────────────────────────────────────
    style.configure(".", font=FONT_NORMAL, background=BG, foreground=FG)

    # ── Frame / LabelFrame ───────────────────────────────────────────────────
    style.configure("TFrame",      background=BG)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER, borderwidth=1)
    style.configure(
        "TLabelframe.Label",
        background=BG, foreground=FG,
        font=FONT_BOLD,
    )

    # ── Label ────────────────────────────────────────────────────────────────
    style.configure("TLabel", background=BG, foreground=FG, font=FONT_NORMAL)
    style.configure("Muted.TLabel", foreground=FG_MUTED, font=FONT_SMALL)

    # ── Button ───────────────────────────────────────────────────────────────
    style.configure(
        "TButton",
        font=FONT_NORMAL,
        background=BG_ELEM,
        foreground=FG,
        bordercolor=BORDER,
        focuscolor=ACCENT,
        padding=(10, 5),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("active",   BG_HOVER),
            ("pressed",  "#D4D4D4"),
            ("disabled", "#E0E0E0"),
        ],
        foreground=[("disabled", FG_MUTED)],
        relief=[("pressed", "flat"), ("active", "flat")],
    )

    # Акцентная кнопка (Primary)
    style.configure(
        "Accent.TButton",
        font=FONT_BOLD,
        background=ACCENT,
        foreground="#FFFFFF",
        bordercolor=ACCENT_DARK,
        padding=(10, 5),
        relief="flat",
    )
    style.map(
        "Accent.TButton",
        background=[
            ("active",   ACCENT_DARK),
            ("pressed",  "#003876"),
            ("disabled", "#A0C4E8"),
        ],
        foreground=[("disabled", "#FFFFFF")],
    )

    # ── Entry ────────────────────────────────────────────────────────────────
    style.configure(
        "TEntry",
        font=FONT_NORMAL,
        fieldbackground=BG_ELEM,
        foreground=FG,
        bordercolor=BORDER,
        focuscolor=ACCENT,
        insertcolor=FG,
        padding=(4, 3),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT), ("active", ACCENT)],
        fieldbackground=[("disabled", BG)],
    )

    # ── Combobox ─────────────────────────────────────────────────────────────
    style.configure(
        "TCombobox",
        font=FONT_NORMAL,
        fieldbackground=BG_ELEM,
        foreground=FG,
        bordercolor=BORDER,
        arrowcolor=FG,
        padding=(4, 3),
    )
    style.map(
        "TCombobox",
        bordercolor=[("focus", ACCENT)],
        fieldbackground=[("readonly", BG)],
    )

    # ── Scrollbar ────────────────────────────────────────────────────────────
    style.configure(
        "TScrollbar",
        background="#DCDCDC",
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=FG_MUTED,
        arrowsize=12,
        relief="flat",
    )
    style.map(
        "TScrollbar",
        background=[("active", "#BEBEBE"), ("pressed", "#A8A8A8")],
    )

    # ── Progressbar ──────────────────────────────────────────────────────────
    style.configure(
        "TProgressbar",
        troughcolor=BG_HOVER,
        background=ACCENT,
        bordercolor=BG,
        lightcolor=ACCENT,
        darkcolor=ACCENT_DARK,
        thickness=6,
    )

    # ── Treeview ─────────────────────────────────────────────────────────────
    style.configure(
        "Treeview",
        font=FONT_NORMAL,
        background=BG_ELEM,
        fieldbackground=BG_ELEM,
        foreground=FG,
        rowheight=24,
        bordercolor=BORDER,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        font=FONT_HDR,
        background=HDR_BG,
        foreground=HDR_FG,
        bordercolor=BORDER,
        relief="flat",
        padding=(4, 6),
    )
    style.map(
        "Treeview",
        background=[("selected", SEL_BG)],
        foreground=[("selected", SEL_FG)],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", "#D4DFF0")],
    )

    # ── Notebook (вкладки) ───────────────────────────────────────────────────
    style.configure(
        "TNotebook",
        background=BG,
        bordercolor=BORDER,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        font=FONT_NORMAL,
        background=BG_HOVER,
        foreground=FG_MUTED,
        padding=(14, 6),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BG_ELEM), ("active", BG)],
        foreground=[("selected", FG)],
        expand=[("selected", (0, 0, 0, 0))],
    )

    # ── Separator ────────────────────────────────────────────────────────────
    style.configure("TSeparator", background=BORDER)

    # ── PanedWindow ──────────────────────────────────────────────────────────
    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=5, sashrelief="flat", background=BORDER)


def _apply_extra_styles() -> None:
    """Дополнительные стили поверх sv_ttk (шрифты, row-colors)."""
    style = ttk.Style()
    style.configure(".", font=FONT_NORMAL)
    style.configure("TLabelframe.Label", font=FONT_BOLD)
    style.configure("Treeview", rowheight=24, font=FONT_NORMAL)
    style.configure("Treeview.Heading", font=FONT_HDR)


# ── Treeview: чередующиеся строки ────────────────────────────────────────────

def stripe_treeview(tree: ttk.Treeview) -> None:
    """Настроить теги для чередующихся строк Treeview.

    Вызвать один раз при создании виджета, затем при заполнении данными
    использовать apply_stripes(tree).
    """
    tree.tag_configure("odd",  background=ROW_ODD)
    tree.tag_configure("even", background=ROW_EVEN)


def apply_stripes(tree: ttk.Treeview) -> None:
    """Применить нечётный/чётный тег к уже заполненному Treeview."""
    for i, item in enumerate(tree.get_children()):
        tag = "even" if i % 2 == 0 else "odd"
        tree.item(item, tags=(tag,))


# ── Умный статус-бар ─────────────────────────────────────────────────────────

class SmartStatusBar:
    """Статусная строка с цветовым индикатором состояния.

    Использование:
        bar = SmartStatusBar(parent)
        bar.pack(fill='x', side='bottom')
        bar.set("Сканирование...", state="busy")
        bar.set("Готово", state="ok")
        bar.set("Ошибка: ...", state="error")
    """

    _STATE_COLORS = {
        "ok":    STATUS_OK,
        "busy":  STATUS_BUSY,
        "error": STATUS_ERR,
        "idle":  FG_MUTED,
    }

    def __init__(self, parent: tk.Widget):
        self._frame = tk.Frame(parent, background=BG, pady=2)

        # Цветной квадратик-индикатор
        self._dot = tk.Label(
            self._frame,
            text="●",
            font=("Segoe UI", 8),
            background=BG,
            foreground=FG_MUTED,
            padx=4,
        )
        self._dot.pack(side="left")

        # Текст статуса
        self._var = tk.StringVar(value="Готово")
        self._label = tk.Label(
            self._frame,
            textvariable=self._var,
            font=FONT_SMALL,
            background=BG,
            foreground=FG_MUTED,
            anchor="w",
        )
        self._label.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # Тонкая линия сверху
        tk.Frame(parent, background=BORDER, height=1).pack(
            fill="x", side="bottom", before=self._frame
        )

    def pack(self, **kwargs):
        self._frame.pack(**kwargs)

    def set(self, text: str, state: str = "idle") -> None:
        """Обновить текст и цвет индикатора.

        Args:
            text:  Отображаемый текст
            state: "ok" | "busy" | "error" | "idle"
        """
        self._var.set(text)
        color = self._STATE_COLORS.get(state, FG_MUTED)
        self._dot.configure(foreground=color)
        self._label.configure(foreground=color if state != "idle" else FG_MUTED)

    @property
    def variable(self) -> tk.StringVar:
        """StringVar текста (для обратной совместимости с textvariable=)."""
        return self._var
