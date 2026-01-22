"""
Standalone Log Viewer Service

This module provides a reusable log viewer window service.
Can be used independently in other projects with Tkinter.

Usage:
    from log_viewer_service import LogViewerService
    from logger import Logger
    
    logger = Logger()
    viewer = LogViewerService(logger)
    viewer.show_log_window(root_window)
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Dict


class LogViewerService:
    """
    Standalone service for displaying logs in a Tkinter window.
    
    Provides a configurable log viewer window with search, clear,
    and export capabilities.
    """
    
    def __init__(self, logger):
        """
        Initialize log viewer service.
        
        Args:
            logger: Logger instance with get_entries() and clear() methods
        """
        self.logger = logger
        self.window_geometry: Dict[str, str] = {}
        self.on_close_callback: Optional[Callable] = None

    def show_log_window(
        self,
        parent_window: tk.Widget,
        window_title: str = 'Log',
        width: int = 700,
        height: int = 400,
        show_timestamp: bool = True,
        show_search: bool = True,
        show_export: bool = True
    ) -> tk.Toplevel:
        """
        Show log viewer window.
        
        Args:
            parent_window: Parent Tkinter window
            window_title: Title for log window
            width: Window width in pixels
            height: Window height in pixels
            show_timestamp: Show timestamps in log entries
            show_search: Show search field
            show_export: Show export button
            
        Returns:
            The created Toplevel window
        """
        win = tk.Toplevel(parent_window)
        win.title(window_title)
        win.geometry(f'{width}x{height}')
        
        # Main container
        main_frame = ttk.Frame(win)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Search frame (optional)
        if show_search:
            search_frame = ttk.Frame(main_frame)
            search_frame.pack(fill='x', pady=(0, 5))
            
            ttk.Label(search_frame, text='Search:').pack(side='left', padx=5)
            search_var = tk.StringVar()
            search_entry = ttk.Entry(search_frame, textvariable=search_var)
            search_entry.pack(side='left', fill='x', expand=True, padx=5)
        else:
            search_var = None
            search_entry = None
        
        # Log display frame
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill='both', expand=True)
        
        log_list = tk.Listbox(list_frame, font=('Courier', 9))
        log_list.pack(fill='both', expand=True, side='left')
        
        scrollbar = ttk.Scrollbar(list_frame, command=log_list.yview)
        log_list.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        
        # Populate log entries
        self._populate_log_list(log_list, show_timestamp)
        
        # Search functionality
        if search_entry:
            def filter_logs(*args):
                search_text = search_var.get().lower()
                log_list.delete(0, tk.END)
                
                for entry in self.logger.get_entries():
                    if search_text in entry.lower():
                        log_list.insert(tk.END, entry)
                
                if not search_text:
                    self._populate_log_list(log_list, show_timestamp)
            
            search_var.trace('w', filter_logs)
        
        # Button frame
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill='x', pady=10, padx=10)
        
        # Clear button
        ttk.Button(
            btn_frame,
            text='Clear Log',
            command=lambda: self._clear_log(log_list)
        ).pack(side='left', padx=5)
        
        # Export button
        if show_export:
            ttk.Button(
                btn_frame,
                text='Export to File',
                command=lambda: self._export_log()
            ).pack(side='left', padx=5)
        
        # Copy button
        ttk.Button(
            btn_frame,
            text='Copy Selected',
            command=lambda: self._copy_to_clipboard(log_list, parent_window)
        ).pack(side='left', padx=5)
        
        # Close button
        ttk.Button(
            btn_frame,
            text='Close',
            command=win.destroy
        ).pack(side='left', padx=5)
        
        # Auto-scroll to bottom
        if log_list.size() > 0:
            log_list.see(log_list.size() - 1)
        
        # Close handler
        def on_closing():
            if self.on_close_callback:
                self.on_close_callback()
            win.destroy()
        
        win.protocol("WM_DELETE_WINDOW", on_closing)
        
        return win

    def show_simple_log_window(
        self,
        parent_window: tk.Widget,
        window_title: str = 'Log',
        width: int = 700,
        height: int = 400
    ) -> tk.Toplevel:
        """
        Show simplified log viewer (without search and export).
        
        Args:
            parent_window: Parent Tkinter window
            window_title: Title for log window
            width: Window width in pixels
            height: Window height in pixels
            
        Returns:
            The created Toplevel window
        """
        return self.show_log_window(
            parent_window,
            window_title=window_title,
            width=width,
            height=height,
            show_search=False,
            show_export=False
        )

    def _populate_log_list(self, log_list: tk.Listbox, show_timestamp: bool = True) -> None:
        """Populate listbox with log entries."""
        log_list.delete(0, tk.END)
        for entry in self.logger.get_entries():
            log_list.insert(tk.END, entry)

    def _clear_log(self, log_list: tk.Listbox) -> None:
        """Clear log and update display."""
        self.logger.clear()
        log_list.delete(0, tk.END)

    def _export_log(self) -> None:
        """Export log to file."""
        import os
        from datetime import datetime
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'log_{timestamp}.txt'
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                for entry in self.logger.get_entries():
                    f.write(entry + '\n')
            print(f"Log exported to {filename}")
        except Exception as e:
            print(f"Failed to export log: {e}")

    def _copy_to_clipboard(self, log_list: tk.Listbox, parent_window: tk.Widget) -> None:
        """Copy selected log entry to clipboard."""
        try:
            selection = log_list.curselection()
            if selection:
                item = log_list.get(selection[0])
                parent_window.clipboard_clear()
                parent_window.clipboard_append(item)
                parent_window.update()
        except Exception as e:
            print(f"Failed to copy to clipboard: {e}")

    def set_window_geometry(self, geometry: str) -> None:
        """Store window geometry for next time."""
        self.window_geometry['last'] = geometry

    def get_stored_geometry(self) -> Optional[str]:
        """Get stored window geometry."""
        return self.window_geometry.get('last')
