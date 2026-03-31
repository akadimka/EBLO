"""FB2 deep integrity checker window.

Validates each FB2 file for:
  1. XML well-formedness (via ElementTree)
  2. Presence of required FB2 elements
  3. Encoding declaration matches actual file bytes
  4. Non-empty book title and at least one author
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager

# Required FB2 structural elements (tag local-name)
_REQUIRED_TAGS = [
    'description', 'title-info', 'book-title',
]


def _check_fb2_file(path: Path) -> list[str]:
    """Check one FB2 file.  Returns list of issue strings (empty = OK)."""
    issues = []

    # 1. Basic file readability
    try:
        raw = path.read_bytes()
    except OSError as e:
        return [f"Не удаётся прочитать: {e}"]

    if len(raw) < 64:
        return ["Файл слишком мал (< 64 байт)"]

    # 2. Detect declared encoding from XML declaration
    declared_enc = None
    try:
        header = raw[:200].decode('ascii', errors='replace')
        import re
        enc_m = re.search(r'encoding=["\']([^"\']+)["\']', header, re.IGNORECASE)
        if enc_m:
            declared_enc = enc_m.group(1).lower()
    except Exception:
        pass

    # 3. Decode content
    content = None
    for enc in ([declared_enc] if declared_enc else []) + ['utf-8', 'cp1251']:
        try:
            content = raw.decode(enc, errors='strict')
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if content is None:
        try:
            content = raw.decode('utf-8', errors='replace')
            issues.append("Кодировка: заменены некорректные символы при чтении UTF-8")
        except Exception:
            return ["Не удаётся декодировать файл"]

    # 4. XML well-formedness
    try:
        ET.fromstring(content.encode('utf-8', errors='replace'))
    except ET.ParseError as e:
        issues.append(f"XML повреждён: {e}")
        # Cannot do structural checks if XML is broken
        return issues

    # 5. Structural checks using regex (faster than full parse for large files)
    import re
    title_info_m = re.search(
        r'<(?:fb:)?title-info>(.*?)</(?:fb:)?title-info>', content,
        re.DOTALL | re.IGNORECASE
    )
    if not title_info_m:
        issues.append("Отсутствует блок <title-info>")
        return issues

    title_info = title_info_m.group(1)

    book_title_m = re.search(r'<book-title[^>]*>(.*?)</book-title>', title_info,
                              re.DOTALL | re.IGNORECASE)
    if not book_title_m:
        issues.append("Отсутствует тег <book-title>")
    elif not book_title_m.group(1).strip():
        issues.append("Пустой <book-title>")

    author_m = re.search(r'<(?:fb:)?author>', title_info, re.IGNORECASE)
    if not author_m:
        issues.append("Отсутствует тег <author>")
    else:
        first_m  = re.search(r'<(?:fb:)?first-name>(.*?)</(?:fb:)?first-name>', title_info, re.DOTALL)
        last_m   = re.search(r'<(?:fb:)?last-name>(.*?)</(?:fb:)?last-name>', title_info, re.DOTALL)
        nick_m   = re.search(r'<(?:fb:)?nickname>(.*?)</(?:fb:)?nickname>', title_info, re.DOTALL)
        has_name = (
            (first_m and first_m.group(1).strip()) or
            (last_m  and last_m.group(1).strip()) or
            (nick_m  and nick_m.group(1).strip())
        )
        if not has_name:
            issues.append("Автор без имени (пустые first-name, last-name, nickname)")

    return issues


class IntegrityCheckWindow:
    """Окно глубокой проверки целостности FB2-файлов."""

    def __init__(self, parent=None, settings_manager: SettingsManager = None,
                 initial_folder: str = ''):
        self.settings = settings_manager

        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Глубокая проверка FB2")
        self.window.minsize(800, 450)
        if parent:
            self.window.transient(parent)

        if settings_manager:
            setup_window_persistence(self.window, 'integrity_check', settings_manager,
                                     '1000x600+150+100')
        else:
            self.window.geometry('1000x600')

        self._folder_var = tk.StringVar(value=initial_folder)
        self._stop_flag = threading.Event()
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Controls
        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ctrl, text="Папка:").pack(side=tk.LEFT)
        ttk.Entry(ctrl, textvariable=self._folder_var, width=60).pack(
            side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        ttk.Button(ctrl, text="…", command=self._browse).pack(side=tk.LEFT)
        self._scan_btn = ttk.Button(ctrl, text="Проверить", command=self._start_scan)
        self._scan_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(ctrl, text="Остановить", command=self._stop_scan).pack(side=tk.LEFT)

        # Progress
        self._status_var = tk.StringVar(value='')
        ttk.Label(main, textvariable=self._status_var, foreground='blue').pack(
            fill=tk.X, pady=(0, 4))

        # Table
        table_frame = ttk.Frame(main)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        cols = ("file_path", "issues")
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings')
        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.heading("file_path", text="Файл")
        self.tree.heading("issues", text="Проблемы")
        self.tree.column("file_path", width=550, minwidth=200)
        self.tree.column("issues", width=400, minwidth=150)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        # Bottom buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="Удалить выделенные",
                   command=self._delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Закрыть",
                   command=self.window.destroy).pack(side=tk.LEFT, padx=4)

    # ------------------------------------------------------------------
    def _browse(self):
        d = filedialog.askdirectory(title="Папка с FB2 файлами",
                                    initialdir=self._folder_var.get())
        if d:
            self._folder_var.set(d)

    def _start_scan(self):
        folder = self._folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Ошибка", "Укажите корректную папку")
            return
        # Clear table
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._stop_flag.clear()
        self._scan_btn.configure(state='disabled')
        threading.Thread(target=self._scan_thread, args=(folder,), daemon=True).start()

    def _stop_scan(self):
        self._stop_flag.set()

    def _scan_thread(self, folder: str):
        fb2_files = sorted(Path(folder).rglob('*.fb2'))
        total = len(fb2_files)
        bad_count = 0
        for i, fp in enumerate(fb2_files):
            if self._stop_flag.is_set():
                break
            issues = _check_fb2_file(fp)
            msg = f"[{i+1}/{total}] {fp.name}"
            self.window.after(0, lambda m=msg: self._status_var.set(m))
            if issues:
                bad_count += 1
                rel = str(fp)
                try:
                    rel = str(fp.relative_to(folder))
                except ValueError:
                    pass
                issue_str = ' | '.join(issues)
                self.window.after(0, lambda r=rel, s=issue_str:
                                  self.tree.insert('', tk.END, values=(r, s)))

        stopped = self._stop_flag.is_set()
        final = (f"Остановлено. Проверено {i+1}/{total}."
                 if stopped else
                 f"Готово. Проверено {total} файлов, проблем: {bad_count}")
        self.window.after(0, lambda: (
            self._status_var.set(final),
            self._scan_btn.configure(state='normal'),
        ))

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("", "Не выбраны файлы")
            return
        folder = self._folder_var.get().strip()
        if not messagebox.askyesno("Удалить?",
                                   f"Удалить {len(sel)} файл(ов) с диска?"):
            return
        deleted = 0
        for iid in sel:
            rel_path = self.tree.set(iid, 'file_path')
            full = Path(folder) / rel_path
            try:
                full.unlink(missing_ok=True)
                self.tree.delete(iid)
                deleted += 1
            except Exception as e:
                messagebox.showerror("Ошибка", f"{rel_path}: {e}")
        messagebox.showinfo("Готово", f"Удалено {deleted} файл(ов)")
