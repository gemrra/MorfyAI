import os
import sys
import hou
from morfyai.qt_compat import QtWidgets

# Force-reload modules on each panel open to avoid stale-cache issues.
def _reload_modules():
    # ---- Purge legacy package name leftovers (HOUDINI_HIP_MANAGER → morfyai migration) ----
    old_mods = [k for k in sys.modules if k.startswith('HOUDINI_HIP_MANAGER')]
    for k in old_mods:
        del sys.modules[k]
    
    # Force-purge skill submodules (loaded via importlib.util.spec_from_file_location
    # under the synthetic package 'houdini_skills', so a normal importlib.reload won't
    # touch them — we drop them from sys.modules and let _load_all() rebuild fresh).
    _skill_keys = [k for k in list(sys.modules.keys()) if k.startswith('houdini_skills')]
    for k in _skill_keys:
        try:
            del sys.modules[k]
        except KeyError:
            pass

    modules_to_reload = [
        'morfyai.qt_compat',  # ★ Qt compat layer first
        'morfyai.utils.token_optimizer',
        'morfyai.utils.ultra_optimizer',
        'morfyai.utils.training_data_exporter',
        'morfyai.utils.updater',
        'morfyai.utils.hooks',
        'morfyai.utils.tool_registry',
        'morfyai.utils.rules_manager',
        'morfyai.utils.ai_client',
        'morfyai.utils.mcp.client',
        'morfyai.utils.mcp',
        'morfyai.skills',  # ★ Reset skill registry so updated SKILL_INFO is picked up
        'morfyai.ui.i18n',
        'morfyai.ui.cursor_widgets',
        # ★ Split mixin modules — reload to avoid referencing stale classes
        'morfyai.ui.font_settings_dialog',
        'morfyai.ui.header',
        'morfyai.ui.input_area',
        'morfyai.ui.chat_view',
        'morfyai.core.agent_runner',
        'morfyai.core.session_manager',
        'morfyai.ui.ai_tab',
        'morfyai.ui.web_panel',
        'morfyai.core.main_window',
    ]
    for mod_name in modules_to_reload:
        if mod_name in sys.modules:
            try:
                import importlib
                # For morfyai.skills, also reset the internal cache flags before reload
                if mod_name == 'morfyai.skills':
                    _sk_mod = sys.modules[mod_name]
                    try:
                        _sk_mod._registry.clear()
                        _sk_mod._loaded = False
                    except Exception:
                        pass
                importlib.reload(sys.modules[mod_name])
            except Exception:
                pass

from morfyai.core.main_window import MainWindow

_main_window = None

def show_tool():
    global _main_window, MainWindow
    
    # Force reload modules on every call
    _reload_modules()

    # ★ After reload, refresh MainWindow reference to avoid using a stale class
    try:
        from morfyai.core.main_window import MainWindow as _MW
        MainWindow = _MW
    except Exception:
        pass
    
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication([])
    else:
        app = QtWidgets.QApplication.instance()

    try:
        if _main_window is not None:
            if _main_window.isVisible():
                _main_window.raise_()
                _main_window.activateWindow()
                return _main_window
            else:
                # Detach the old instance's atexit save callback so it doesn't overwrite the new instance's data
                try:
                    import atexit as _atexit
                    if hasattr(_main_window, 'ai_tab'):
                        _main_window.ai_tab._destroyed = True
                        _atexit.unregister(_main_window.ai_tab._atexit_save)
                    _atexit.unregister(_main_window._atexit_save)
                    app = QtWidgets.QApplication.instance()
                    if app:
                        try:
                            app.aboutToQuit.disconnect(_main_window._on_app_about_to_quit)
                        except (TypeError, RuntimeError):
                            pass
                except Exception:
                    pass
                _main_window.force_quit = True
                _main_window.close()
                _main_window.deleteLater()
                _main_window = None
    except Exception:
        _main_window = None

    try:
        _main_window = MainWindow()
        _main_window.show()
        _main_window.raise_()
        _main_window.activateWindow()
        return _main_window
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "Error", f"Failed to create MorfyAI window:\n{e}", QtWidgets.QMessageBox.Ok)
        return None

if __name__ == "__main__":
    show_tool()
