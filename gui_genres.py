"""Окно управления жанрами: дерево, ассоциации, drag&drop, контекстные меню."""
import tkinter as tk
from tkinter import ttk, messagebox

# Обработка импортов
try:
    from .genres_manager import GenresManager
    from .window_manager import get_window_manager
except ImportError:
    from genres_manager import GenresManager
    from window_manager import get_window_manager

class GenresManagerWindow(tk.Toplevel):
    def __init__(self, master, genres_manager, update_callback=None):
        super().__init__(master)
        self.title('Управление жанрами')
        self.genres_manager = genres_manager
        self.master_window = master
        
        # Восстановление размеров окна из настроек
        if hasattr(master, 'settings'):
            geometry = master.settings.get_window_geometry('genres_manager')
            if geometry:
                self.geometry(geometry)
            else:
                self.geometry('700x500')
        else:
            self.geometry('700x500')
        self.update_callback = update_callback
        self.logger = getattr(master, 'logger', None)
        
        # Управление окном через менеджер
        window_manager = get_window_manager()
        window_manager.open_child_window(
            master,
            self,
            on_close=self._on_window_closing
        )

        main_pane = ttk.PanedWindow(self, orient='horizontal')
        main_pane.pack(fill='both', expand=True)

        # Слева: дерево жанров
        left_frame = ttk.Frame(main_pane)
        ttk.Label(left_frame, text='Основные жанры').pack(anchor='w')
        self.tree = ttk.Treeview(left_frame, show='tree')
        self.tree.pack(fill='both', expand=True, side='left')
        self.tree.bind('<Button-3>', self._on_tree_context)
        self.tree.bind('<B1-Motion>', self._on_drag)
        self.tree.bind('<ButtonRelease-1>', self._on_drop)
        self.tree.bind('<Button-1>', self._on_tree_click)
        left_scroll = ttk.Scrollbar(left_frame, command=self.tree.yview)
        self.tree.config(yscrollcommand=left_scroll.set)
        left_scroll.pack(side='right', fill='y')
        main_pane.add(left_frame, weight=2)

        # Справа: ассоциированные жанры
        right_frame = ttk.Frame(main_pane)
        ttk.Label(right_frame, text='Ассоциированные жанры').pack(anchor='w')
        self.assoc_list = tk.Listbox(right_frame)
        self.assoc_list.pack(fill='both', expand=True, side='left')
        self.assoc_list.bind('<Button-3>', self._on_assoc_context)
        assoc_scroll = ttk.Scrollbar(right_frame, command=self.assoc_list.yview)
        self.assoc_list.config(yscrollcommand=assoc_scroll.set)
        assoc_scroll.pack(side='right', fill='y')
        main_pane.add(right_frame, weight=3)

        self._dragging = None
        
        # Восстановление состояния дерева жанров из настроек
        self._expanded_nodes = set()
        if hasattr(master, 'settings'):
            self._expanded_nodes = master.settings.get_genre_tree_state()
            
        self._populate_tree()

    def _populate_tree(self):
        # Сохраняем состояние развернутости узлов перед пересозданием дерева
        # Если дерево уже существует, сохраняем его текущее состояние
        # Иначе используем сохраненное состояние из настроек
        if self.tree.get_children():
            expanded_nodes = self._get_expanded_nodes()
        else:
            expanded_nodes = self._expanded_nodes
            
        selected_path = []
        selection = self.tree.selection()
        if selection:
            # Сохраняем путь к выделенному элементу
            temp_item = selection[0]
            while temp_item:
                selected_path.insert(0, self.tree.item(temp_item, 'text'))
                temp_item = self.tree.parent(temp_item)
        
        self.tree.delete(*self.tree.get_children())
        def add_node(node, parent=''):
            # Проверяем, должен ли узел быть развернут
            is_expanded = node.name in expanded_nodes
            item = self.tree.insert(parent, 'end', text=node.name, open=is_expanded)
            for child in node.children:
                add_node(child, item)
        for node in self.genres_manager.root_nodes:
            add_node(node)
            
        # Восстанавливаем выделение после пересоздания дерева
        if selected_path:
            self._restore_selection(selected_path)

    def _on_tree_context(self, event):
        item = self.tree.identify_row(event.y)
        menu = tk.Menu(self, tearoff=0)
        if item:
            menu.add_command(label='Добавить поджанр', command=lambda: self._add_genre(item))
            menu.add_command(label='Удалить', command=lambda: self._delete_genre(item))
            menu.add_command(label='Переименовать', command=lambda: self._rename_genre(item))
        else:
            menu.add_command(label='Добавить жанр', command=lambda: self._add_genre(''))
        menu.post(event.x_root, event.y_root)

    def _add_genre(self, parent_item):
        name = self._prompt('Название жанра:')
        if not name:
            return
        parent_node = self._get_node_by_item(parent_item) if parent_item else None
        try:
            from .genres_manager import GenreNode
        except ImportError:
            from genres_manager import GenreNode
        new_node = GenreNode(name)
        
        added = True
        if parent_node:
            added = parent_node.add_child(new_node)
        else:
            # Check if root node with this name already exists
            if any(n.name == name for n in self.genres_manager.root_nodes):
                added = False
            else:
                self.genres_manager.root_nodes.append(new_node)
        
        if not added:
            from tkinter import messagebox
            messagebox.showinfo('Дубликат', f'Жанр "{name}" уже существует')
            return
        
        self.genres_manager.save()
        # Сохраняем путь к новому узлу для последующего развертывания
        new_node_path = []
        temp_node = new_node
        while temp_node:
            new_node_path.insert(0, temp_node.name)
            temp_node = temp_node.parent
        self._populate_tree()
        # Развертываем узлы, ведущие к новому жанру
        self._expand_to_node(new_node_path)
        # Вызываем callback для обновления основного окна
        if self.update_callback:
            self.update_callback()
        if self.logger:
            self.logger.log(f'Добавлен жанр: {name}')

    def _delete_genre(self, item):
        node = self._get_node_by_item(item)
        if not node:
            return
        if node.parent:
            node.parent.remove_child(node)
        else:
            self.genres_manager.root_nodes.remove(node)
        self.genres_manager.save()
        self._populate_tree()
        # Вызываем callback для обновления основного окна
        if self.update_callback:
            self.update_callback()
        if self.logger:
            self.logger.log(f'Удалён жанр: {node.name}')

    def _rename_genre(self, item):
        node = self._get_node_by_item(item)
        if not node:
            return
        new_name = self._prompt('Новое название жанра:', node.name)
        if new_name and new_name != node.name:
            node.name = new_name
            self.genres_manager.save()
            self._populate_tree()
            # Вызываем callback для обновления основного окна
            if self.update_callback:
                self.update_callback()
            if self.logger:
                self.logger.log(f'Переименован жанр: {new_name}')

    def _on_tree_click(self, event):
        # Обработка клика по элементу дерева
        item = self.tree.identify_row(event.y)
        if item:
            # Если мы не в процессе перетаскивания, выбираем элемент
            if not self._dragging:
                # Выбираем элемент
                self.tree.selection_set(item)
                # Обновляем список ассоциированных жанров
                self._on_tree_select()
        else:
            # Снимаем выделение
            self.tree.selection_set()
            # Очищаем список ассоциированных жанров
            self.assoc_list.delete(0, tk.END)

    def _on_tree_select(self, event=None):
        item = self.tree.selection()
        if not item:
            return
        node = self._get_node_by_item(item[0])
        self.assoc_list.delete(0, tk.END)
        if node:
            for genre_str in sorted(node.assigned):
                self.assoc_list.insert(tk.END, genre_str)

    def _on_assoc_context(self, event):
        sel = self.assoc_list.curselection()
        if not sel:
            return
        genre_str = self.assoc_list.get(sel[0])
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='Удалить ассоциацию', command=lambda: self._remove_association(genre_str))
        menu.post(event.x_root, event.y_root)

    def _remove_association(self, genre_str):
        item = self.tree.selection()
        if not item:
            return
        # Сохраняем путь к выделенному элементу перед обновлением дерева
        selected_path = []
        temp_item = item[0]
        while temp_item:
            selected_path.insert(0, self.tree.item(temp_item, 'text'))
            temp_item = self.tree.parent(temp_item)
        
        node = self._get_node_by_item(item[0])
        if node and genre_str in node.assigned:
            # Используем метод remove_association из GenresManager для корректного удаления
            self.genres_manager.remove_association(genre_str, node.name)
            self._populate_tree()  # Обновить дерево, так как структура узлов могла измениться
            
            # Восстанавливаем выделение после пересоздания дерева
            self._restore_selection(selected_path)
            
            self._on_tree_select()  # Обновить список ассоциированных жанров
            # Вызываем callback для обновления основного окна
            if self.update_callback:
                self.update_callback()
            if self.logger:
                self.logger.log(f'Удалена ассоциация: {genre_str}')
    
    def _restore_selection(self, path):
        """Восстановить выделение в дереве по пути."""
        if not path:
            return
            
        def find_item_by_path(parent, path_index):
            if path_index >= len(path):
                return parent
                
            children = self.tree.get_children(parent)
            for child in children:
                if self.tree.item(child, 'text') == path[path_index]:
                    return find_item_by_path(child, path_index + 1)
                    
            return parent
            
        item = find_item_by_path('', 0)
        if item:
            self.tree.selection_set(item)
            self.tree.see(item)  # Прокрутить к выделенному элементу

    def _expand_to_node(self, path):
        """Разворачивает узлы дерева, ведущие к указанному узлу."""
        if not path:
            return
            
        def find_and_expand(parent, path_index):
            if path_index >= len(path):
                return
                
            children = self.tree.get_children(parent)
            for child in children:
                if self.tree.item(child, 'text') == path[path_index]:
                    # Разворачиваем узел
                    self.tree.item(child, open=True)
                    # Рекурсивно обрабатываем следующий уровень
                    find_and_expand(child, path_index + 1)
                    break
                    
        find_and_expand('', 0)

    def _get_node_by_item(self, item):
        # Восстановление GenreNode по item Treeview
        path = []
        while item:
            path.insert(0, self.tree.item(item, 'text'))
            item = self.tree.parent(item)
        nodes = self.genres_manager.root_nodes
        node = None
        for name in path:
            node = next((n for n in nodes if n.name == name), None)
            if node:
                nodes = node.children
            else:
                return None
        return node

    def _prompt(self, text, initial=''):
        # Простое окно ввода (используется для добавления и переименования жанра)
        win = tk.Toplevel(self)
        win.title(text)
        win.grab_set()
        win.transient(self)  # Сделать окно_transient
        win.focus_set()  # Установить фокус на окно
        win.resizable(False, False)  # Запретить изменение размера
        tk.Label(win, text=text).pack(padx=10, pady=5)
        entry = tk.Entry(win)
        entry.insert(0, initial)
        entry.pack(padx=10, pady=5)
        entry.focus_set()  # Установить фокус на поле ввода
        result = {'val': None}
        def ok(event=None):
            result['val'] = entry.get()
            win.destroy()
        entry.bind('<Return>', ok)
        tk.Button(win, text='OK', command=ok).pack(pady=5)
        win.bind('<Return>', lambda event: ok())
        win.wait_window()
        return result['val']

    def _on_drag(self, event):
        # Начало перетаскивания или продолжение перетаскивания
        item = self.tree.identify_row(event.y)
        if item:
            # Если это начало перетаскивания, запоминаем элемент
            if not self._dragging:
                self._dragging = item
                # Визуальная обратная связь - выделяем элемент, который перетаскивается
                self.tree.selection_set(item)
                # Изменяем стиль элемента для визуальной индикации
                self.tree.tag_configure("dragging", background="lightblue")
                self.tree.item(item, tags=("dragging",))
            else:
                # Если это продолжение перетаскивания, выделяем элемент под курсором
                if item != self._dragging:
                    # Сбрасываем стиль предыдущего элемента
                    self.tree.item(self.tree.selection()[0] if self.tree.selection() else item, tags=())
                    # Выделяем новый элемент
                    self.tree.selection_set(item)
                    # Изменяем стиль элемента, на который наведен курсор
                    self.tree.tag_configure("drop_target", background="lightgreen")
                    self.tree.item(item, tags=("drop_target",))
                else:
                    # Если курсор над элементом, который перетаскивается, сбрасываем стиль
                    if self.tree.selection():
                        self.tree.item(self.tree.selection()[0], tags=())
                    self.tree.selection_set(item)
        else:
            # Если курсор не над элементом, снимаем выделение и сбрасываем стиль
            if self.tree.selection():
                self.tree.item(self.tree.selection()[0], tags=())
            self.tree.selection_set()

    def _get_expanded_nodes(self):
        """Получает список имен развернутых узлов дерева."""
        expanded = set()
        
        def check_node(item):
            # Проверяем, развернут ли узел
            if self.tree.item(item, 'open'):
                # Добавляем имя узла в список развернутых
                expanded.add(self.tree.item(item, 'text'))
                
            # Рекурсивно проверяем дочерние узлы
            children = self.tree.get_children(item)
            for child in children:
                check_node(child)
                
        # Проверяем все корневые узлы
        root_children = self.tree.get_children('')
        for child in root_children:
            check_node(child)
            
        return expanded

    def _on_drop(self, event):
        if not self._dragging:
            return
        target = self.tree.identify_row(event.y)
        if not target or target == self._dragging:
            self._dragging = None
            return
        node = self._get_node_by_item(self._dragging)
        target_node = self._get_node_by_item(target)
        
        # Проверяем, что оба узла существуют и это действительно перемещение
        if not node or not target_node or node == target_node:
            self._dragging = None
            return
            
        # Проверяем, что target_node не является потомком node
        # (предотвращаем перемещение родителя в своего потомка)
        temp_parent = target_node.parent
        while temp_parent:
            if temp_parent == node:
                self._dragging = None
                return
            temp_parent = temp_parent.parent
            
        # Проверяем, что node не является прямым потомком target_node
        # (в этом случае перемещение не требуется)
        if node.parent == target_node:
            self._dragging = None
            return
            
        # Визуальная обратная связь - снимаем выделение
        self.tree.selection_set()
        # Сбрасываем все теги
        for item in self.tree.get_children():
            # Сбрасываем теги текущего элемента
            self.tree.item(item, tags=())
            # Рекурсивно сбрасываем теги дочерних элементов
            self._reset_tags_recursive(item)
            
        # Удалить из старого родителя
        if node.parent:
            node.parent.remove_child(node)
        else:
            self.genres_manager.root_nodes.remove(node)
            
        # Добавить к новому родителю
        target_node.add_child(node)
        
        self.genres_manager.save()
        self._populate_tree()
        
        # Вызываем callback для обновления основного окна
        if self.update_callback:
            self.update_callback()
            
        if self.logger:
            self.logger.log(f'Перемещён жанр: {node.name} → {target_node.name}')
            
        self._dragging = None

    
    def _reset_tags_recursive(self, parent_item):
        """Рекурсивно сбрасывает теги всех дочерних элементов."""
        children = self.tree.get_children(parent_item)
        for child in children:
            # Сбрасываем теги текущего элемента
            self.tree.item(child, tags=())
            # Рекурсивно обрабатываем дочерние элементы
            self._reset_tags_recursive(child)

    def _on_window_closing(self):
        """Callback when window is being closed by manager."""
        self._save_state()

    def _save_state(self):
        """Save window state."""
        try:
            # Сохраняем состояние дерева жанров перед закрытием
            if hasattr(self.master, 'settings'):
                expanded_nodes = self._get_expanded_nodes()
                self.master.settings.set_genre_tree_state(expanded_nodes)
                
            # Сохраняем размеры окна перед закрытием
            if hasattr(self.master, 'settings'):
                geometry = self.geometry()
                self.master.settings.set_window_geometry('genres_manager', geometry)
        except tk.TclError:
            pass

    def destroy(self):
        # Сохраняем состояние дерева жанров перед закрытием
        if hasattr(self.master, 'settings'):
            expanded_nodes = self._get_expanded_nodes()
            self.master.settings.set_genre_tree_state(expanded_nodes)
            
        # Сохраняем размеры окна перед закрытием
        if hasattr(self.master, 'settings'):
            try:
                geometry = self.geometry()
                self.master.settings.set_window_geometry('genres_manager', geometry)
            except tk.TclError:
                pass
        try:
            super().destroy()
        except tk.TclError:
            pass
