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


def _is_geometry_visible(geometry_str: str, window) -> bool:
    """
    Check if a window geometry (position and size) is visible on screen.
    
    Args:
        geometry_str: Geometry string like "WxH+X+Y"
        window: Tkinter window (for accessing screen dimensions)
    
    Returns:
        True if window is (at least partially) visible on screen, False otherwise
    """
    try:
        import re
        # Parse geometry: WxH+X+Y or WxH-X-Y
        match = re.match(r'(\d+)x(\d+)([\+\-])(\d+)([\+\-])(\d+)', geometry_str)
        if not match:
            return False
        
        width = int(match.group(1))
        height = int(match.group(2))
        x_sign = match.group(3)
        x_coord = int(match.group(4))
        y_sign = match.group(5)
        y_coord = int(match.group(6))
        
        # Apply signs
        if x_sign == '-':
            x_coord = -x_coord
        if y_sign == '-':
            y_coord = -y_coord
        
        # Get screen dimensions
        try:
            # For multi-monitor setup, we check against virtual screen
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
        except:
            # Fallback: assume common screen size
            screen_width = 1920
            screen_height = 1080
        
        # Window bounds
        window_left = x_coord
        window_right = x_coord + width
        window_top = y_coord
        window_bottom = y_coord + height
        
        # Screen bounds (including negative coordinates for multi-monitor)
        # Allow some margin for window decorations
        screen_left = -4000  # Allow far left monitors
        screen_right = screen_width + 4000  # Allow far right monitors
        screen_top = -2000   # Allow above-screen positioning
        screen_bottom = screen_height + 2000  # Allow below-screen positioning
        
        # Check if window overlaps with screen area
        # Window is visible if it intersects the screen rectangle
        window_visible = not (
            window_right < screen_left or
            window_left > screen_right or
            window_bottom < screen_top or
            window_top > screen_bottom
        )
        
        return window_visible
        
    except Exception as e:
        # If we can't determine visibility, assume it's OK
        return True


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
                
                # Check if window is visible on screen
                if not _is_geometry_visible(geom_str, window):
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


def center_window_on_parent(window: tk.Toplevel, parent: tk.Tk, width: int = 400, height: int = 300) -> str:
    """
    Center a child window on its parent window.
    
    Args:
        window: Child window (Toplevel) to center
        parent: Parent window (Tk)
        width: Desired width of child window
        height: Desired height of child window
    
    Returns:
        Geometry string "WxH+X+Y" for the centered position
    """
    try:
        # Get parent window position and size
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        # Calculate centered position
        child_x = parent_x + (parent_width - width) // 2
        child_y = parent_y + (parent_height - height) // 2
        
        # Ensure window doesn't go off-screen (with some margin)
        min_x = -width + 50  # At least 50px visible
        max_x = parent.winfo_screenwidth() - 50
        min_y = -height + 50
        max_y = parent.winfo_screenheight() - 50
        
        child_x = max(min_x, min(child_x, max_x))
        child_y = max(min_y, min(child_y, max_y))
        
        geometry = f"{width}x{height}+{child_x}+{child_y}"
        return geometry
        
    except Exception as e:
        # Fallback to default
        return f"{width}x{height}+200+200"


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
