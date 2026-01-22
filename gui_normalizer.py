import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

class CSVNormalizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Нормализация")
        self.root.geometry("1400x700")
        
        # Переменные
        self.folder_path = tk.StringVar()
        self.folder_path.set("E:/Users/dmitriy.murov/Downloads/Tribler/Downloads/Test1")
        
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
        
    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_path.get())
        if folder:
            self.folder_path.set(folder)
            
    def create_csv(self):
        messagebox.showinfo("Информация", "Функция создания CSV")
        
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