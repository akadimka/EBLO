import tkinter as tk
from tkinter import ttk, messagebox

class BrokenFilesWindow:
    def __init__(self, parent=None):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Битые файлы")
        self.window.geometry("1000x600")
        
        # Переменная для счетчика
        self.scan_status = tk.StringVar()
        self.scan_status.set("Сканирование битых файлов: 70/70")
        
        # Создание GUI
        self.create_widgets()
        
    def create_widgets(self):
        # Главный контейнер
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Верхняя часть - статус сканирования
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(status_frame, textvariable=self.scan_status, 
                 font=('Arial', 9)).pack(anchor=tk.W)
        
        # Таблица с битыми файлами
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        
        # Treeview (таблица)
        columns = ("file_path", "reason")
        
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
        self.tree.heading("file_path", text="file_path")
        self.tree.heading("reason", text="reason")
        
        # Ширина столбцов
        self.tree.column("file_path", width=600, minwidth=200)
        self.tree.column("reason", width=300, minwidth=150)
        
        # Размещение элементов
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        # Нижние кнопки
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(buttons_frame, text="Отмена", 
                  command=self.close_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Удалить", 
                  command=self.delete_files).pack(side=tk.RIGHT, padx=5)
        
    def delete_files(self):
        # Проверка выбранных элементов
        selected_items = self.tree.selection()
        
        if not selected_items:
            messagebox.showwarning("Предупреждение", "Не выбраны файлы для удаления")
            return
        
        # Подтверждение удаления
        result = messagebox.askyesno(
            "Подтверждение", 
            f"Вы уверены, что хотите удалить {len(selected_items)} файл(ов)?"
        )
        
        if result:
            # Удаление выбранных элементов из таблицы
            for item in selected_items:
                self.tree.delete(item)
            messagebox.showinfo("Информация", "Файлы успешно удалены")
        
    def close_window(self):
        self.window.destroy()
        
    def add_broken_file(self, file_path, reason):
        """Метод для добавления битого файла в таблицу"""
        self.tree.insert('', 'end', values=(file_path, reason))
        
    def run(self):
        self.window.mainloop()

# Для запуска как отдельного окна
if __name__ == "__main__":
    app = BrokenFilesWindow()
    
    # Пример добавления данных (для демонстрации)
    # app.add_broken_file("C:/path/to/file1.fb2", "Невозможно прочитать")
    # app.add_broken_file("C:/path/to/file2.fb2", "Повреждён XML")
    
    app.run()

# Для запуска из другого приложения
def open_broken_files_window(parent=None):
    return BrokenFilesWindow(parent)