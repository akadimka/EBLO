"""
Window state management utilities.

Provides functions to save and restore window geometry (size, position, state).
"""

import tkinter as tk
from typing import Optional, Tuple


def save_window_geometry(window: tk.Tk, window_name: str, settings_manager):
    """
    Save window geometry (position, size, and state).
    
    Args:
        window: Tkinter window to save
        window_name: Unique identifier for the window (e.g., 'main', 'settings', 'debug')
        settings_manager: SettingsManager instance
    """
    try:
        # Get geometry: "WxH+X+Y"
        geometry = window.geometry()
        
        # Clean up geometry string - fix malformed coordinates like "+-1953" -> "-1953"
        import re
        # Replace "+-" with "-" to fix malformed negative coordinates
        geometry = re.sub(r'\+-', '-', geometry)
        
        # Get state (normal, maximized, iconified, etc.)
        state = window.state()
        
        # Normalize state for cross-platform compatibility
        # Tkinter on Windows returns "zoomed", convert to "maximized" for portability
        if state == 'zoomed':
            state = 'maximized'
        
        # Store as dict
        window_data = {
            'geometry': geometry,
            'state': state,
        }
        
        # Save to settings
        if not hasattr(settings_manager, '_window_states'):
            settings_manager._window_states = {}
        
        settings_manager.set_window_geometry(window_name, window_data)
        
    except Exception as e:
        pass


def restore_window_geometry(window: tk.Tk, window_name: str, settings_manager,
                           default_geometry: Optional[str] = None,
                           default_state: str = 'normal') -> bool:
    """
    Restore window geometry (position, size, and state).
    
    Args:
        window: Tkinter window to restore
        window_name: Unique identifier for the window
        settings_manager: SettingsManager instance
        default_geometry: Default geometry if not saved (e.g., "1280x709+100+100")
        default_state: Default state ('normal', 'maximized', etc.)
    
    Returns:
        True if geometry was restored, False if using defaults
    """
    try:
        window_data = settings_manager.get_window_geometry(window_name)
        
        # Helper function to validate and fix geometry
        def validate_geometry(geom_str):
            """Validate geometry string format and basic sanity checks."""
            try:
                import re
                # Clean up malformed coordinates (+-1953 -> -1953)
                geom_str = re.sub(r'\+-', '-', geom_str)
                
                match = re.match(r'(\d+)x(\d+)([\+\-])(\d+)([\+\-])(\d+)', geom_str)
                if not match:
                    return None
                
                width = int(match.group(1))
                height = int(match.group(2))
                
                # Only validate minimum size, don't touch coordinates
                # (negative coords are valid for multi-monitor systems)
                if width < 200 or height < 100:
                    return None
                
                # Return geometry as-is (after cleanup)
                return geom_str
            except Exception as e:
                return None
        
        if window_data is None:
            # No saved geometry, use defaults
            if default_geometry:
                valid_geom = validate_geometry(default_geometry)
                if valid_geom:
                    window.geometry(valid_geom)
            window.state(default_state)
            return False
        
        # Handle both old format (just string) and new format (dict)
        if isinstance(window_data, str):
            # Old format: just geometry string
            valid_geom = validate_geometry(window_data)
            if valid_geom:
                window.geometry(valid_geom)
            else:
                if default_geometry:
                    valid_default = validate_geometry(default_geometry)
                    if valid_default:
                        window.geometry(valid_default)
            window.state(default_state)
            return True
        
        elif isinstance(window_data, dict):
            # New format: dict with geometry and state
            geometry = window_data.get('geometry', default_geometry)
            state = window_data.get('state', default_state)
            
            # Normalize state for Tkinter
            # Tkinter on Windows uses "zoomed" instead of "maximized"
            # So we need to convert both directions:
            # - When SAVING: zoomed -> maximized (for portability)
            # - When APPLYING: maximized -> zoomed (for Windows Tkinter)
            if state == 'maximized':
                state = 'zoomed'
            
            if state in ['zoomed', 'iconic']:
                # For special states, set geometry first, then apply state
                if geometry:
                    valid_geom = validate_geometry(geometry)
                    if valid_geom:
                        try:
                            window.geometry(valid_geom)
                        except tk.TclError:
                            pass
                
                # Then apply state - this will maximize/zoom the window
                try:
                    window.state(state)
                    # Force update to ensure state is properly applied
                    window.update_idletasks()
                except tk.TclError:
                    try:
                        window.state(default_state)
                    except:
                        pass
            else:
                # For normal state, set geometry
                if geometry:
                    valid_geom = validate_geometry(geometry)
                    if valid_geom:
                        try:
                            window.geometry(valid_geom)
                        except tk.TclError as e:
                            if default_geometry:
                                valid_default = validate_geometry(default_geometry)
                                if valid_default:
                                    try:
                                        window.geometry(valid_default)
                                    except:
                                        pass
                    elif default_geometry:
                        valid_default = validate_geometry(default_geometry)
                        if valid_default:
                            try:
                                window.geometry(valid_default)
                            except:
                                pass
                
                try:
                    window.state(state)
                except tk.TclError:
                    try:
                        window.state(default_state)
                    except:
                        pass
            
            return True
        
        return False
        
    except Exception as e:
        if default_geometry:
            try:
                window.geometry(default_geometry)
            except:
                pass
        return False


def _apply_window_state(window: tk.Tk, state: str, default_state: str) -> None:
    """
    Apply window state with error handling.
    
    Helper function to safely apply window state after delay.
    """
    try:
        window.state(state)
    except tk.TclError:
        try:
            window.state(default_state)
        except:
            pass


def setup_window_persistence(window: tk.Tk, window_name: str, settings_manager,
                            default_geometry: Optional[str] = None) -> None:
    """
    Setup automatic persistence for a window.
    
    Call this after creating a window to automatically:
    - Restore geometry when window is first displayed
    - Save geometry when window is closed
    
    Args:
        window: Tkinter window
        window_name: Unique identifier
        settings_manager: SettingsManager instance
        default_geometry: Optional default geometry
    """
    
    
    # Restore geometry using deferred callback to ensure window is ready
    # This is more reliable than relying on <Map> event timing
    def restore_deferred():
        restore_window_geometry(window, window_name, settings_manager, default_geometry)
    
    # Schedule restoration for next event loop iteration (after window initialization)
    window.after(1, restore_deferred)
    
    # Also bind to <Map> event as backup (in case window is shown before after() callback)
    def on_first_map(event=None):
        window.unbind('<Map>')
        # Restore again on map in case it was shown before our after() callback
        restore_window_geometry(window, window_name, settings_manager, default_geometry)
    
    window.bind('<Map>', on_first_map)
    
    # Save geometry on close
    def on_close():
        save_window_geometry(window, window_name, settings_manager)
        window.destroy()
    
    window.protocol('WM_DELETE_WINDOW', on_close)


def create_toplevel_with_persistence(parent: tk.Tk, window_name: str, 
                                     settings_manager,
                                     default_geometry: Optional[str] = None,
                                     on_close_callback = None,
                                     **toplevel_kwargs) -> tk.Toplevel:
    """
    Create a Toplevel window with automatic persistence.
    
    Args:
        parent: Parent window
        window_name: Unique identifier for this window
        settings_manager: SettingsManager instance
        default_geometry: Default size+position (e.g., "800x600+100+100")
        on_close_callback: Optional callback to call before window closes
        **toplevel_kwargs: Additional kwargs for tk.Toplevel()
    
    Returns:
        Configured Toplevel window
    """
    dlg = tk.Toplevel(parent)
    
    # Apply any kwargs
    for key, value in toplevel_kwargs.items():
        if key == 'title':
            dlg.title(value)
        elif key == 'geometry':
            dlg.geometry(value)
    
    # Setup persistence
    restore_window_geometry(dlg, window_name, settings_manager, default_geometry)
    
    # Save on close
    def on_close():
        save_window_geometry(dlg, window_name, settings_manager)
        if on_close_callback:
            on_close_callback()
        dlg.destroy()
    
    # Also bind to Destroy event to catch any close path
    def on_destroy(event):
        if dlg.winfo_exists():
            save_window_geometry(dlg, window_name, settings_manager)
            if on_close_callback:
                on_close_callback()
    
    dlg.bind('<Destroy>', on_destroy, add=True)
    dlg.protocol('WM_DELETE_WINDOW', on_close)
    
    return dlg
