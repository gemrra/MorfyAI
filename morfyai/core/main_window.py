# -*- coding: utf-8 -*-
"""
MorfyAI - Main Window
Workspace save/restore (window state + context cache).
"""

import os
import json
import atexit
import hou
from pathlib import Path
from morfyai.qt_compat import QtWidgets, QtGui, QtCore
from morfyai.ui.web_panel import MorfyWebPanel

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


class MainWindow(QtWidgets.QMainWindow):
    """MorfyAI main window"""
    
    def __init__(self, parent=None):
        # Try to use the Houdini main window as parent
        if parent is None:
            try:
                parent = hou.qt.mainWindow()
            except:
                pass

        super().__init__(parent)
        self.setWindowTitle("MorfyAI - Houdini Assistant")
        self.setMinimumSize(420, 600)

        # Workspace config directory
        self._workspace_dir = Path(__file__).parent.parent.parent / "cache" / "workspace"
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_file = self._workspace_dir / "workspace.json"

        # Do not use WindowStaysOnTopHint — keep this window at the same level as Houdini
        self.setWindowFlags(QtCore.Qt.Window)

        # Deep blue-black background (matches the AITab glassmorphism theme)
        self.setStyleSheet("QMainWindow { background-color: #0a0a12; }")

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        self.force_quit = False
        self._already_saved = False  # guard against duplicate saves

        self.init_ui(central_widget)

        # Load workspace (window state + context)
        self._load_workspace()

        # Register several exit hooks to make sure we save on Houdini exit:
        # 1. QApplication.aboutToQuit — fires on normal Qt shutdown
        app = QtWidgets.QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._on_app_about_to_quit)
        # 2. atexit — fires when the Python interpreter shuts down
        atexit.register(self._atexit_save)
        # 3. Houdini-specific: subscribe to hipFile events (save on scene switch too)
        try:
            hou.hipFile.addEventCallback(self._on_hip_event)
        except Exception:
            pass

    def init_ui(self, central_widget):
        """Initialise the UI."""
        layout = QtWidgets.QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.web_panel = MorfyWebPanel(parent=central_widget, workspace_dir=self._workspace_dir)
        layout.addWidget(self.web_panel)
        # Workspace save/restore below drives the real engine underneath the web view.
        self.ai_tab = self.web_panel.engine

    def force_quit_application(self):
        """Force the application to quit."""
        self.force_quit = True
        self.close()

    def _save_workspace(self):
        """Save the workspace (window state + all session caches)."""
        try:
            geometry = self.geometry()
            window_state = {
                'x': geometry.x(),
                'y': geometry.y(),
                'width': geometry.width(),
                'height': geometry.height(),
                'is_maximized': self.isMaximized()
            }
            
            has_sessions = False
            tab_count = 0
            if hasattr(self, 'ai_tab') and self.ai_tab:
                has_sessions = self.ai_tab._save_all_sessions()
                tab_count = self.ai_tab.session_tabs.count()
            
            workspace_data = {
                'version': '1.1',
                'window_state': window_state,
                'cache_info': {
                    'has_conversation': has_sessions,
                    'tab_count': tab_count,
                    'use_manifest': True,
                }
            }
            
            with open(self._workspace_file, 'w', encoding='utf-8') as f:
                json.dump(workspace_data, f, ensure_ascii=False, indent=2)
            
            _dbg(f"[Workspace] Saved: window({window_state['width']}x{window_state['height']}), {tab_count} session tabs")
            
        except Exception as e:
            _dbg(f"[Workspace] Save failed: {str(e)}")
    
    def _load_workspace(self):
        """Load the workspace (window state + context cache)."""
        try:
            if not self._workspace_file.exists():
                self.resize(450, 700)
                return
            
            with open(self._workspace_file, 'r', encoding='utf-8') as f:
                workspace_data = json.load(f)
            
            window_state = workspace_data.get('window_state', {})
            if window_state:
                x = window_state.get('x', 100)
                y = window_state.get('y', 100)
                width = window_state.get('width', 450)
                height = window_state.get('height', 700)
                is_maximized = window_state.get('is_maximized', False)
                
                self.setGeometry(x, y, width, height)
                if is_maximized:
                    self.setWindowState(QtCore.Qt.WindowMaximized)
            
            cache_info = workspace_data.get('cache_info', {})
            # Always attempt to restore — no longer dependent on the has_conversation flag,
            # since the manifest or cache_latest may still contain content even when all
            # sessions were empty on the previous exit.
            if hasattr(self, 'ai_tab'):
                # Delay 200 ms so the UI has finished initialising
                QtCore.QTimer.singleShot(200, self._load_workspace_cache)
            
            _dbg(f"[Workspace] Loaded: {self._workspace_file}")
            
        except Exception as e:
            _dbg(f"[Workspace] Load failed: {str(e)}")
            self.resize(450, 700)
    
    def _load_workspace_cache(self):
        """Deferred workspace-cache load."""
        try:
            if not hasattr(self, 'ai_tab'):
                return
            
            if self.ai_tab._restore_all_sessions():
                return
            
            cache_dir = self.ai_tab._cache_dir
            latest_cache = cache_dir / "cache_latest.json"
            if latest_cache.exists():
                self.ai_tab._load_cache_silent(latest_cache)
        except Exception as e:
            _dbg(f"[Workspace] Cache load failed: {str(e)}")
    
    def _on_app_about_to_quit(self):
        self._save_workspace_once()
    
    def _atexit_save(self):
        self._save_workspace_once()
    
    def _on_hip_event(self, event_type):
        try:
            if event_type in (hou.hipFileEventType.BeforeClear,
                              hou.hipFileEventType.BeforeLoad):
                self._save_workspace_once()
        except Exception:
            pass
    
    def _save_workspace_once(self):
        """Make sure we save exactly once on shutdown (aboutToQuit / atexit / closeEvent may all fire)."""
        if self._already_saved or self.force_quit:
            return
        self._already_saved = True
        try:
            self._save_workspace()
        except Exception as e:
            _dbg(f"[Workspace] Exit save failed: {e}")
    
    def closeEvent(self, event):
        if not self.force_quit:
            self._save_workspace()
        event.accept()
        super().closeEvent(event)
