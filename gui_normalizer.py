import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
import sys
from pathlib import Path

try:
    from regen_csv import RegenCSVService
except ImportError:
    from .regen_csv import RegenCSVService


class CSVNormalizerApp:
    def __init__(self, root, folder_path=None, logger=None, settings_manager=None):
        self.root = root
        self.root.title("Нормализация")
        self.root.geometry("1400x700")
        
        # Logger из главного окна (если передан)
        self.logger = logger
        
        # Settings manager из главного окна (если передан)
        self.settings_manager = settings_manager
        
        # Переменные
        self.folder_path = tk.StringVar()
        # Если папка передана, используем её, иначе используем по умолчанию
        if folder_path and os.path.isdir(folder_path):
            self.folder_path.set(folder_path)
        else:
            self.folder_path.set("E:/Users/dmitriy.murov/Downloads/Tribler/Downloads/Test1")
        
        # Сервис для генерации CSV
        self.csv_service = RegenCSVService()
        self.processing = False
        
        self._log("Инициализация окна нормализации")
        
        # Создание GUI
        self.create_widgets()
        
    def create_widgets(self):
        # Верхняя панель с путем к папке
        top_frame = ttk.Frame(self.root, padding="5")
        top_frame.pack(fill=tk.X, side=tk.TOP)
        
        ttk.Label(top_frame, text="Папка для Input:").pack(side=tk.LEFT, padx=5)
        
        path_entry = ttk.Entry(top_frame, textvariable=self.folder_path, width=80)
        path_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        ttk.Button(top_frame, text="Обзор", command=self.browse_folder).pack(side=tk.LEFT, padx=5)
        
        # Основная таблица
        table_frame = ttk.Frame(self.root, padding="5")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        
        # Treeview (таблица)
        columns = (
            "file_path", "metadata_authors", "proposed_author", "author_source",
            "metadata_series", "proposed_series", "series_source",
            "book_title", "metadata_genre"
        )
        
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show='headings',
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set
        )
        
        # Настройка scrollbars
        v_scrollbar.config(command=self.tree.yview)
        h_scrollbar.config(command=self.tree.xview)
        
        # Заголовки столбцов
        column_names = {
            "file_path": "file_path",
            "metadata_authors": "metadata_authors",
            "proposed_author": "proposed_author",
            "author_source": "author_source",
            "metadata_series": "metadata_series",
            "proposed_series": "proposed_series",
            "series_source": "series_source",
            "book_title": "book_title",
            "metadata_genre": "metadata_genre"
        }
        
        for col in columns:
            self.tree.heading(col, text=column_names[col])
            self.tree.column(col, width=120, minwidth=80)
        
        # Размещение элементов
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        # Нижняя панель с кнопками
        bottom_frame = ttk.Frame(self.root, padding="5")
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        ttk.Label(bottom_frame, text="Готово").pack(side=tk.LEFT, padx=10)
        
        # Кнопки
        buttons_frame = ttk.Frame(bottom_frame)
        buttons_frame.pack(side=tk.LEFT, padx=20)
        
        ttk.Button(buttons_frame, text="Создать CSV", command=self.create_csv).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Отмена", command=self.cancel).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Применить изменения", command=self.apply_changes).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Битые файлы", command=self.show_broken_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Шаблоны", command=self.show_templates).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Дубликаты", command=self.show_duplicates).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Удалить пустые папки", command=self.delete_empty_folders).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Логи", command=self.show_logs).pack(side=tk.LEFT, padx=2)
        
    def _log(self, message: str):
        """Логирование в окно логов и консоль."""
        if self.logger:
            self.logger.log(message)
        # Временное логирование в консоль
        print(f"[NORMALIZER] {message}", file=sys.stdout)
        sys.stdout.flush()
        
    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_path.get())
        if folder:
            self.folder_path.set(folder)
            self._log(f"Папка выбрана: {folder}")
            
    def create_csv(self):
        """Создать CSV из FB2 файлов в папке."""
        folder = self.folder_path.get()
        self._log(f"Начало создания CSV для папки: {folder}")
        
        if not folder or not os.path.isdir(folder):
            self._log(f"ОШИБКА: Папка не существует или не указана: {folder}")
            messagebox.showerror("Ошибка", "Укажите корректную папку")
            return
        
        if self.processing:
            self._log("ОШИБКА: Обработка уже в процессе")
            messagebox.showwarning("Внимание", "Обработка уже в процессе")
            return
        
        # Запустить обработку в отдельном потоке
        self.processing = True
        self._log("Запуск потока генерации CSV")
        thread = threading.Thread(
            target=self._process_csv_thread,
            args=(folder,),
            daemon=True
        )
        thread.start()
    
    def _process_csv_thread(self, folder_path: str):
        """Обработка CSV в отдельном потоке."""
        try:
            self._log(f"Начало генерации CSV для папки: {folder_path}")
            
            def progress_callback(current, total, status):
                """Обновить прогресс в UI."""
                self._log(f"Прогресс: {current}/{total} - {status}")
                self.root.after(0, lambda: self._update_progress(current, total, status))
            
            # Определяем путь сохранения CSV если нужно
            output_csv_path = None
            if self.settings_manager and self.settings_manager.get_generate_csv():
                # Сохраняем в папку проекта с именем regen.csv
                output_csv_path = str(Path(__file__).parent / 'regen.csv')
                self._log(f"CSV будет сохранён в: {output_csv_path}")
            else:
                self._log("Параметр 'Генерировать CSV-файл' отключен - CSV не будет сохранён")
            
            # Генерировать CSV
            self._log("Запуск сервиса генерации CSV")
            records = self.csv_service.generate_csv(
                folder_path,
                output_csv_path=output_csv_path,
                progress_callback=progress_callback
            )
            
            self._log(f"CSV сгенерирован: {len(records)} записей")
            if output_csv_path:
                self._log(f"CSV-файл сохранён: {output_csv_path}")
            
            # Обновить таблицу в UI
            self.root.after(0, lambda: self._fill_table(records))
            
            # Показать результат
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Готово",
                    f"Обработано {len(records)} файлов\nТаблица обновлена"
                )
            )
            self._log(f"Обработка завершена успешно: {len(records)} файлов")
        except Exception as e:
            self._log(f"ОШИБКА при обработке CSV: {str(e)}")
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "Ошибка",
                    f"Ошибка при обработке: {str(e)}"
                )
            )
        finally:
            self.processing = False
    
    def _update_progress(self, current: int, total: int, status: str):
        """Обновить статус прогресса."""
        # Обновить лейбл внизу
        status_label = None
        for child in self.root.winfo_children():
            if isinstance(child, ttk.Frame):
                for widget in child.winfo_children():
                    if isinstance(widget, ttk.Label) and 'Готово' in widget.cget('text'):
                        status_label = widget
                        break
        
        if status_label:
            status_label.config(text=f"{status} ({current}/{total})")
    
    def _fill_table(self, records):
        """Заполнить таблицу записями."""
        # Очистить таблицу
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Добавить записи
        for record in records:
            self.tree.insert(
                '',
                tk.END,
                values=record.to_tuple()
            )
        
    def cancel(self):
        if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите отменить?"):
            self.root.quit()
            
    def apply_changes(self):
        messagebox.showinfo("Информация", "Применение изменений")
        
    def show_broken_files(self):
        messagebox.showinfo("Информация", "Показать битые файлы")
        
    def show_templates(self):
        messagebox.showinfo("Информация", "Показать шаблоны")
        
    def show_duplicates(self):
        messagebox.showinfo("Информация", "Показать дубликаты")
        
    def delete_empty_folders(self):
        if messagebox.askyesno("Подтверждение", "Удалить пустые папки?"):
            messagebox.showinfo("Информация", "Пустые папки удалены")
            
    def show_logs(self):
        messagebox.showinfo("Информация", "Показать логи")

def main():
    root = tk.Tk()
    app = CSVNormalizerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()