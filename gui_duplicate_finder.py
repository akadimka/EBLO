import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class DuplicateFinderWindow:
    def __init__(self, parent=None):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Поиск дубликатов")
        self.window.geometry("1400x900")
        
        # Переменные
        self.library_path = tk.StringVar()
        self.library_path.set("C:/Users/dmitriy.murov/Downloads/TriblerDownloads/EBook Library")
        
        self.work_path = tk.StringVar()
        self.work_path.set("C:/Users/dmitriy.murov/Downloads/TriblerDownloads/Test1")
        
        self.status_text = tk.StringVar()
        self.status_text.set("Готово")
        
        # Создание GUI
        self.create_widgets()
        
    def create_widgets(self):
        # Главный контейнер
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Верхняя часть - пути к папкам
        paths_frame = ttk.Frame(main_frame)
        paths_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Библиотека
        lib_frame = ttk.Frame(paths_frame)
        lib_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(lib_frame, text="Библиотека:", font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=2)
        lib_entry = ttk.Entry(lib_frame, textvariable=self.library_path)
        lib_entry.pack(fill=tk.X, pady=2)
        
        # Рабочая папка
        work_frame = ttk.Frame(paths_frame)
        work_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(work_frame, text="Рабочая папка:", font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=2)
        work_entry = ttk.Entry(work_frame, textvariable=self.work_path)
        work_entry.pack(fill=tk.X, pady=2)
        
        # Разделитель
        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        
        # Заголовок для списков дубликатов
        ttk.Label(main_frame, text="Дубликаты (файлы, найденные в обеих папках):", 
                 font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        # Контейнер для двух списков
        lists_frame = ttk.Frame(main_frame)
        lists_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Левый список - "Путь в библиотеке"
        left_frame = ttk.Frame(lists_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        ttk.Label(left_frame, text="Путь в библиотеке").pack(anchor=tk.W, pady=2)
        
        left_scroll_y = ttk.Scrollbar(left_frame, orient=tk.VERTICAL)
        left_scroll_x = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL)
        
        self.left_listbox = tk.Listbox(
            left_frame,
            yscrollcommand=left_scroll_y.set,
            xscrollcommand=left_scroll_x.set,
            bg='white',
            font=('Arial', 9)
        )
        
        left_scroll_y.config(command=self.left_listbox.yview)
        left_scroll_x.config(command=self.left_listbox.xview)
        
        self.left_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        left_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Правый список - "Путь в рабочей папке"
        right_frame = ttk.Frame(lists_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        ttk.Label(right_frame, text="Путь в рабочей папке").pack(anchor=tk.W, pady=2)
        
        right_scroll_y = ttk.Scrollbar(right_frame, orient=tk.VERTICAL)
        right_scroll_x = ttk.Scrollbar(right_frame, orient=tk.HORIZONTAL)
        
        self.right_listbox = tk.Listbox(
            right_frame,
            yscrollcommand=right_scroll_y.set,
            xscrollcommand=right_scroll_x.set,
            bg='white',
            font=('Arial', 9)
        )
        
        right_scroll_y.config(command=self.right_listbox.yview)
        right_scroll_x.config(command=self.right_listbox.xview)
        
        self.right_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        right_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Нижний разделитель
        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        
        # Прогресс-бар
        self.progress = ttk.Progressbar(main_frame, mode='determinate', length=300)
        self.progress.pack(fill=tk.X, pady=(0, 10))
        
        # Статус
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        status_label = ttk.Label(status_frame, textvariable=self.status_text, 
                                font=('Arial', 9))
        status_label.pack(anchor=tk.W)
        
        # Кнопки внизу
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X)
        
        ttk.Button(buttons_frame, text="Сравнить", 
                  command=self.compare_folders).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Отмена", 
                  command=self.close_window).pack(side=tk.LEFT, padx=5)
        
    def compare_folders(self):
        # Заглушка для функции сравнения
        self.status_text.set("Выполняется поиск дубликатов...")
        self.progress['value'] = 0
        
        # Имитация процесса
        for i in range(101):
            self.progress['value'] = i
            self.window.update_idletasks()
            self.window.after(10)
        
        self.status_text.set("Готово. Дубликаты не найдены.")
        messagebox.showinfo("Информация", "Поиск завершен")
        
    def close_window(self):
        self.window.destroy()
        
    def run(self):
        self.window.mainloop()

# Для запуска как отдельного окна
if __name__ == "__main__":
    app = DuplicateFinderWindow()
    app.run()

# Для запуска из другого приложения
def open_duplicate_finder(parent=None):
    DuplicateFinderWindow(parent)