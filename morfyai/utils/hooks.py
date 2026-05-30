# -*- coding: utf-8 -*-
"""
Hook pluginsystem (Plugin Hook System)

Provides external community extension capabilities for MorfyAI:
  - HookManager: singleexample, manageall hook registerandeventpartsend
  - PluginLoader: scan plugins/ directory, loadpluginmodule
  - PluginContext: passgiveeachplugin contextobject (API enterport) 
  - decorative  API: @hook, @tool, @ui_button

support event:
  on_before_request  — AI API requestprevious (canmodify messages) 
  on_after_response  — AI replycompleteafter
  on_before_tool     — toolexecuteprevious
  on_after_tool      — toolexecuteafter
  on_content_chunk   — AI outputtext chunk
  on_session_start   — newsessionstart
  on_session_end     — sessionend

pluginconvention:
  - putin plugins/ directorybelow  .py file
  - by _ start filenotwillisautoload
  - mustpackagecontaining PLUGIN_INFO dict and register(ctx) function
"""

from __future__ import annotations

import importlib.util
import json
import os

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================
# Hook eventnameconstant
# ============================================================

EVENT_BEFORE_REQUEST = "on_before_request"
EVENT_AFTER_RESPONSE = "on_after_response"
EVENT_BEFORE_TOOL = "on_before_tool"
EVENT_AFTER_TOOL = "on_after_tool"
EVENT_CONTENT_CHUNK = "on_content_chunk"
EVENT_SESSION_START = "on_session_start"
EVENT_SESSION_END = "on_session_end"

ALL_EVENTS = (
    EVENT_BEFORE_REQUEST,
    EVENT_AFTER_RESPONSE,
    EVENT_BEFORE_TOOL,
    EVENT_AFTER_TOOL,
    EVENT_CONTENT_CHUNK,
    EVENT_SESSION_START,
    EVENT_SESSION_END,
)


# ============================================================
# HookManager — singleexample, manageall hook registerandeventpartsend
# ============================================================

class HookManager:
    """Global hook manager (singleton).

    - register / unregister: register / unregister an event hook
    - fire:        fire an event (notify-type — callbacks cannot modify data)
    - fire_filter: pipeline-style filter (each callback can modify and return the value)
    - register_tool / get_external_tools / execute_external_tool: external tool management
    """

    _instance: Optional[HookManager] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        # event_name -> [(priority, callback), ...]  by priority riseorder
        self._hooks: Dict[str, List[Tuple[int, Callable]]] = {e: [] for e in ALL_EVENTS}
        # externaltool: tool_name -> {"schema": {...}, "handler": callable, "plugin": str}
        self._external_tools: Dict[str, Dict[str, Any]] = {}
        # UI button: [(plugin_name, icon, tooltip, callback), ...]
        self._ui_buttons: List[Tuple[str, str, str, Callable]] = []
        # UI Bridge reference (by AITab initializationwhenset) 
        self._ui_bridge: Optional[PluginUIBridge] = None

    # ---------- eventregister ----------

    def register(self, event: str, callback: Callable, priority: int = 0):
        """registerhookfunction

        Args:
            event: eventname (see ALL_EVENTS) 
            callback: callbackfunction
            priority: preferredlevel (countcharacterexceedsmallexceedfirstexecute, default 0) 
        """
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append((priority, callback))
        self._hooks[event].sort(key=lambda x: x[0])

    def unregister(self, event: str, callback: Callable):
        """unregisterhookfunction"""
        if event in self._hooks:
            self._hooks[event] = [
                (p, cb) for p, cb in self._hooks[event] if cb is not callback
            ]

    def unregister_all(self, plugin_name: str = ""):
        """unregisterallhook (orspecifiedplugin hook) 

        .. deprecated::
            by plugin_name unregisterpleaseuse PluginContext._cleanup(), 
            itwillfinecertaintrackandcleanupthispluginregister allhook, toolandbutton. 
            thismethodonlyused forglobalcleanup (plugin_name asemptywhen) . 
        """
        if not plugin_name:
            for event in self._hooks:
                self._hooks[event] = []
        else:
            # ★ via PluginContext._cleanup() realnow, hereonlydohint
            import warnings
            warnings.warn(
                "unregister_all(plugin_name) is deprecated. "
                "Use PluginContext._cleanup() instead.",
                DeprecationWarning, stacklevel=2,
            )

    # ---------- eventtrigger ----------

    def fire(self, event: str, **kwargs):
        """Fire an event (notify-type — all callbacks are called in order; they cannot modify data).

        Any callback raising an exception will not interrupt subsequent callbacks or the main flow.
        """
        for _priority, callback in self._hooks.get(event, []):
            try:
                callback(**kwargs)
            except Exception as e:
                _dbg(f"[Hook] ⚠ {event} callback error: {e}")
                traceback.print_exc()

    def fire_filter(self, event: str, value: Any, **kwargs) -> Any:
        """Pipeline-style filter event (each callback receives a value, returns a modified value).

        used for on_before_request etc.needsmodifydata scene. 
        ifcallbackreturn None, keeporiginalvalue. 
        callbacksignaturecanis callback(value) or callback(value, **kwargs). 
        """
        for _priority, callback in self._hooks.get(event, []):
            try:
                try:
                    result = callback(value, **kwargs)
                except TypeError:
                    # downgrade: callbacknotacceptextra kwargs
                    result = callback(value)
                if result is not None:
                    value = result
            except Exception as e:
                _dbg(f"[Hook] ⚠ {event} filter error: {e}")
                traceback.print_exc()
        return value

    # ---------- externaltoolmanage ----------

    def register_tool(self, name: str, schema: dict, description: str,
                      handler: Callable, plugin_name: str = ""):
        """registerexternaltool

        Args:
            name: toolname (AI callwhenuse) 
            schema: OpenAI Function Calling   parameters schema
            description: tooldescription
            handler: executefunction, signature (args: dict) -> dict
            plugin_name: owning plugin name
        """
        full_schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": f"[Plugin] {description}",
                "parameters": schema,
            }
        }
        self._external_tools[name] = {
            "schema": full_schema,
            "handler": handler,
            "plugin": plugin_name,
        }
        # ★ syncregisterto ToolRegistry
        try:
            from .tool_registry import get_tool_registry
            get_tool_registry().register(
                name=name,
                schema=full_schema,
                handler=handler,
                source="plugin",
                plugin_name=plugin_name,
                tags=set(),
                modes={"agent", "ask", "plan_executing"},
            )
        except Exception:
            pass
        _dbg(f"[Hook] Registered external tool: {name} (from {plugin_name or 'unknown'})")

    def unregister_tool(self, name: str):
        """unregisterexternaltool"""
        if name in self._external_tools:
            del self._external_tools[name]
            # ★ syncfrom ToolRegistry unregister
            try:
                from .tool_registry import get_tool_registry
                get_tool_registry().unregister(name)
            except Exception:
                pass

    def unregister_tools_by_plugin(self, plugin_name: str):
        """unregisterspecifiedplugin alltool"""
        to_remove = [n for n, v in self._external_tools.items()
                     if v.get("plugin") == plugin_name]
        for n in to_remove:
            del self._external_tools[n]
        # ★ syncfrom ToolRegistry unregister
        try:
            from .tool_registry import get_tool_registry
            get_tool_registry().unregister_by_source("plugin", plugin_name)
        except Exception:
            pass

    def get_external_tools(self) -> List[dict]:
        """getallexternaltool  OpenAI schema list"""
        return [v["schema"] for v in self._external_tools.values()]

    def has_external_tool(self, name: str) -> bool:
        """checkwhethersaveinspecifiedexternaltool"""
        return name in self._external_tools

    def execute_external_tool(self, name: str, args: dict) -> dict:
        """executeexternaltool"""
        tool_info = self._external_tools.get(name)
        if not tool_info:
            return {"success": False, "error": f"externaltooldoes not exist: {name}"}
        try:
            result = tool_info["handler"](args)
            if not isinstance(result, dict):
                result = {"success": True, "result": str(result)}
            return result
        except Exception as e:
            return {"success": False, "error": f"externaltool {name} execution failed: {e}"}

    # ---------- UI buttonmanage ----------

    def register_button(self, plugin_name: str, icon: str, tooltip: str,
                        callback: Callable):
        """register UI button"""
        self._ui_buttons.append((plugin_name, icon, tooltip, callback))

    def unregister_buttons_by_plugin(self, plugin_name: str):
        """unregisterspecifiedplugin allbutton"""
        self._ui_buttons = [b for b in self._ui_buttons if b[0] != plugin_name]

    def get_buttons(self) -> List[Tuple[str, str, str, Callable]]:
        """getallregister  UI button"""
        return list(self._ui_buttons)

    # ---------- UI Bridge ----------

    def set_ui_bridge(self, bridge: PluginUIBridge):
        """set UI bridgeconnect (by AITab initializationwhencall) """
        self._ui_bridge = bridge

    def get_ui_bridge(self) -> Optional[PluginUIBridge]:
        """get UI bridgeconnect"""
        return self._ui_bridge

    # ---------- replace ----------

    def reset(self):
        """finishallreplace (used forreloadpluginwhen) """
        self._init()


# ============================================================
# PluginUIBridge — UI API bridgeconnectlayer
# ============================================================

class PluginUIBridge:
    """bridgeconnectpluginwith UI layer, raiseforthreadsafe  UI operation

    Created by AITab.__init__ which passes in a chat_layout reference.
    Plugins access these capabilities indirectly via PluginContext.
    """

    def __init__(self):
        self._chat_layout = None         # QVBoxLayout reference
        self._button_container = None    # QHBoxLayout reference
        self._insert_card_signal = None  # Signal reference (threadsafeinsert) 
        self._ai_tab = None              # AITab reference

    def set_chat_layout(self, layout):
        self._chat_layout = layout

    def set_button_container(self, container):
        self._button_container = container

    def set_insert_card_signal(self, signal):
        self._insert_card_signal = signal

    def set_ai_tab(self, ai_tab):
        self._ai_tab = ai_tab

    def insert_chat_card(self, widget):
        """inchatareainsertcustom QWidget (mainthreadsafe) """
        if self._insert_card_signal:
            # viasignaladjustdegreetomainthread
            self._insert_card_signal.emit(widget)
        elif self._chat_layout:
            # directlyinsert (onlyinmainthreadcallwhensafe) 
            try:
                self._chat_layout.insertWidget(
                    self._chat_layout.count() - 1, widget)
            except Exception as e:
                _dbg(f"[Hook] ⚠ insert_chat_card error: {e}")

    def mount_buttons(self):
        """willallregister pluginbuttonhangloadtotoolbar"""
        if not self._button_container:
            return
        manager = get_hook_manager()
        try:
            from morfyai.qt_compat import QtWidgets, QtCore
        except ImportError:
            return

        # ★ firstclearemptyoldbutton, preventduplicatehangload
        while self._button_container.count():
            item = self._button_container.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        for plugin_name, icon, tooltip, callback in manager.get_buttons():
            btn = QtWidgets.QPushButton(icon)
            btn.setToolTip(tooltip)
            btn.setObjectName("pluginToolbarBtn")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setFixedSize(28, 28)
            btn.clicked.connect(callback)
            self._button_container.addWidget(btn)


# ============================================================
# PluginContext — passgiveeachplugin register()  contextobject
# ============================================================

class PluginContext:
    """plugin  API enterportobject

    Each plugin's register(ctx) accesses all capabilities via ctx.
    """

    def __init__(self, plugin_name: str, manager: HookManager,
                 settings: dict, config_path: Path):
        self._plugin_name = plugin_name
        self._manager = manager
        self._settings = settings           # thisplugin setvalue dict
        self._config_path = config_path     # plugins.json path
        self._registered_hooks: List[Tuple[str, Callable]] = []  # trackregister hook

    @property
    def plugin_name(self) -> str:
        return self._plugin_name

    # ---------- event Hook ----------

    def on(self, event: str, callback: Callable, priority: int = 0):
        """registereventhook"""
        self._manager.register(event, callback, priority)
        self._registered_hooks.append((event, callback))

    # ---------- toolregister ----------

    def register_tool(self, name: str, description: str, schema: dict,
                      handler: Callable):
        """registercustomtool (AI cancall) """
        self._manager.register_tool(
            name=name, schema=schema, description=description,
            handler=handler, plugin_name=self._plugin_name,
        )

    # ---------- UI ----------

    def register_button(self, icon: str, tooltip: str, callback: Callable):
        """registertoolbarbutton"""
        self._manager.register_button(
            self._plugin_name, icon, tooltip, callback)

    def insert_chat_card(self, widget):
        """inchatareainsertcustom QWidget"""
        bridge = self._manager.get_ui_bridge()
        if bridge:
            bridge.insert_chat_card(widget)
        else:
            _dbg(f"[Hook] ⚠ UI bridge not available, cannot insert chat card")

    # ---------- set ----------

    def get_setting(self, key: str, default: Any = None) -> Any:
        """readpluginset"""
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any):
        """writepluginset (autopersistentization) """
        self._settings[key] = value
        _save_plugin_config(self._config_path)

    # ---------- log ----------

    def log(self, msg: str):
        """pluginlogoutput"""
        _dbg(f"[Plugin:{self._plugin_name}] {msg}")

    # ---------- cleanup ----------

    def _cleanup(self):
        """unregisterthispluginregister allhookandtool"""
        for event, callback in self._registered_hooks:
            self._manager.unregister(event, callback)
        self._registered_hooks.clear()
        self._manager.unregister_tools_by_plugin(self._plugin_name)
        self._manager.unregister_buttons_by_plugin(self._plugin_name)


# ============================================================
# PluginLoader — scan plugins/ directory, loadplugin
# ============================================================

# pluginconfigfile path
_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_CONFIG_FILE = _CONFIG_DIR / "plugins.json"

# globalconfigcache
_plugin_config: Dict[str, Any] = {}

# alreadyload plugin: plugin_name -> {"module": mod, "info": PLUGIN_INFO, "ctx": PluginContext, "enabled": bool, "file": Path}
_loaded_plugins: Dict[str, Dict[str, Any]] = {}
_plugins_loaded = False


def _load_plugin_config() -> Dict[str, Any]:
    """loadpluginconfig"""
    global _plugin_config
    try:
        if _CONFIG_FILE.exists():
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                _plugin_config = json.load(f)
        else:
            _plugin_config = {}
    except Exception:
        _plugin_config = {}
    return _plugin_config


def _save_plugin_config(config_path: Optional[Path] = None):
    """savepluginconfig"""
    path = config_path or _CONFIG_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(_plugin_config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _dbg(f"[Hook] ⚠ Save plugin config failed: {e}")


def _get_plugins_dir() -> Path:
    """get plugins/ directory path"""
    return Path(__file__).parent.parent.parent / "plugins"


def load_all_plugins():
    """scanandloadallplugin"""
    global _loaded_plugins, _plugins_loaded

    if _plugins_loaded:
        return

    plugins_dir = _get_plugins_dir()
    if not plugins_dir.exists():
        plugins_dir.mkdir(parents=True, exist_ok=True)
        _plugins_loaded = True
        return

    config = _load_plugin_config()
    disabled_list = config.get("disabled", [])
    manager = get_hook_manager()

    for f in sorted(plugins_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue  # belowplanlinestart notautoload

        module_name = f.stem
        try:
            _load_single_plugin(f, module_name, disabled_list, manager)
        except Exception as e:
            _dbg(f"[Hook] ✖ Load plugin {module_name} failed: {e}")
            traceback.print_exc()

    _plugins_loaded = True
    if _loaded_plugins:
        enabled = [n for n, v in _loaded_plugins.items() if v["enabled"]]
        _dbg(f"[Hook] Loaded {len(_loaded_plugins)} plugin(s), "
              f"enable {len(enabled)} : {', '.join(enabled) or '(no)'}")

    # ★ fromconfigloaddisabletoollistto ToolRegistry
    try:
        disabled_tools = config.get("disabled_tools", [])
        if disabled_tools:
            from .tool_registry import get_tool_registry
            get_tool_registry().load_disabled_from_config(disabled_tools)
            _dbg(f"[Hook] Disabled {len(disabled_tools)} tool(s): {', '.join(disabled_tools)}")
    except Exception:
        pass


def _load_single_plugin(filepath: Path, module_name: str,
                         disabled_list: List[str],
                         manager: HookManager):
    """Load a single plugin."""
    # ★ Clear decorator-collection sets so multiple plugins don't interfere with each other.
    global _pending_hooks, _pending_tools, _pending_buttons
    _pending_hooks = []
    _pending_tools = []
    _pending_buttons = []

    spec = importlib.util.spec_from_file_location(
        f"houdini_plugins.{module_name}", str(filepath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    info = getattr(mod, "PLUGIN_INFO", None)
    register_fn = getattr(mod, "register", None)

    if not info or not isinstance(info, dict):
        _dbg(f"[Hook] ⚠ Plugin {module_name} missing PLUGIN_INFO dict, skipped")
        return
    if not register_fn or not callable(register_fn):
        _dbg(f"[Hook] ⚠ Plugin {module_name} missing register(ctx) function, skipped")
        return

    plugin_name = info.get("name", module_name)
    is_disabled = plugin_name in disabled_list
    is_enabled = not is_disabled

    # buildpluginset
    plugin_settings = _plugin_config.get("settings", {}).get(plugin_name, {})
    # use schema in  default valuefillfillnotset item
    for setting_def in info.get("settings", []):
        key = setting_def.get("key")
        if key and key not in plugin_settings:
            plugin_settings[key] = setting_def.get("default")

    # createcontext
    ctx = PluginContext(
        plugin_name=plugin_name,
        manager=manager,
        settings=plugin_settings,
        config_path=_CONFIG_FILE,
    )

    # registerpluginrecord
    _loaded_plugins[plugin_name] = {
        "module": mod,
        "info": info,
        "ctx": ctx,
        "enabled": is_enabled,
        "file": filepath,
    }

    # ifenable, call register
    if is_enabled:
        try:
            register_fn(ctx)
            # ★ applicationdecorative collectset hook/tool/button
            _apply_decorators(ctx)
            _dbg(f"[Hook] ✔ Plugin {plugin_name} v{info.get('version', '?')} loaded")
        except Exception as e:
            _dbg(f"[Hook] ✖ Plugin {plugin_name} register() failed: {e}")
            traceback.print_exc()
            _loaded_plugins[plugin_name]["enabled"] = False


def reload_plugin(plugin_name: str) -> bool:
    """reloadspecifiedplugin"""
    plugin_data = _loaded_plugins.get(plugin_name)
    if not plugin_data:
        _dbg(f"[Hook] ⚠ Plugin {plugin_name} not found")
        return False

    # cleanupoldregister
    ctx = plugin_data["ctx"]
    ctx._cleanup()

    # renewloadmodule
    filepath = plugin_data["file"]
    module_name = filepath.stem
    manager = get_hook_manager()
    config = _load_plugin_config()
    disabled_list = config.get("disabled", [])

    try:
        # removeoldrecord
        del _loaded_plugins[plugin_name]
        # renewload
        _load_single_plugin(filepath, module_name, disabled_list, manager)
        # renewhangload UI button
        bridge = manager.get_ui_bridge()
        if bridge:
            bridge.mount_buttons()
        _dbg(f"[Hook] ↻ Plugin {plugin_name} reloaded")
        return True
    except Exception as e:
        _dbg(f"[Hook] ✖ Reload plugin {plugin_name} failed: {e}")
        traceback.print_exc()
        return False


def enable_plugin(plugin_name: str) -> bool:
    """enableplugin"""
    plugin_data = _loaded_plugins.get(plugin_name)
    if not plugin_data:
        return False

    if plugin_data["enabled"]:
        return True  # enabled

    manager = get_hook_manager()
    ctx = plugin_data["ctx"]
    register_fn = getattr(plugin_data["module"], "register", None)

    if register_fn:
        try:
            register_fn(ctx)
            plugin_data["enabled"] = True
            # updateconfig
            disabled = _plugin_config.get("disabled", [])
            if plugin_name in disabled:
                disabled.remove(plugin_name)
                _plugin_config["disabled"] = disabled
                _save_plugin_config()
            # renewhangloadbutton
            bridge = manager.get_ui_bridge()
            if bridge:
                bridge.mount_buttons()
            _dbg(f"[Hook] ✔ Plugin {plugin_name} enabled")
            return True
        except Exception as e:
            _dbg(f"[Hook] ✖ Enable plugin {plugin_name} failed: {e}")
            return False
    return False


def disable_plugin(plugin_name: str) -> bool:
    """disableplugin"""
    plugin_data = _loaded_plugins.get(plugin_name)
    if not plugin_data:
        return False

    if not plugin_data["enabled"]:
        return True  # disabled

    # cleanuphookandtool
    ctx = plugin_data["ctx"]
    ctx._cleanup()
    plugin_data["enabled"] = False

    # updateconfig
    disabled = _plugin_config.get("disabled", [])
    if plugin_name not in disabled:
        disabled.append(plugin_name)
        _plugin_config["disabled"] = disabled
        _save_plugin_config()

    # renewhangloadbutton (removedisabled ) 
    manager = get_hook_manager()
    bridge = manager.get_ui_bridge()
    if bridge:
        bridge.mount_buttons()

    _dbg(f"[Hook] ✖ Plugin {plugin_name} disabled")
    return True


def get_plugin_setting(plugin_name: str, key: str, default: Any = None) -> Any:
    """getpluginsetvalue"""
    return _plugin_config.get("settings", {}).get(plugin_name, {}).get(key, default)


def set_plugin_setting(plugin_name: str, key: str, value: Any):
    """setpluginsetvalue"""
    if "settings" not in _plugin_config:
        _plugin_config["settings"] = {}
    if plugin_name not in _plugin_config["settings"]:
        _plugin_config["settings"][plugin_name] = {}
    _plugin_config["settings"][plugin_name][key] = value
    _save_plugin_config()


def list_plugins() -> List[Dict[str, Any]]:
    """columnoutallplugin metadatadata"""
    load_all_plugins()
    result = []
    for name, data in _loaded_plugins.items():
        info = dict(data["info"])
        info["_enabled"] = data["enabled"]
        info["_file"] = str(data["file"])
        result.append(info)
    return result


def get_plugins_dir() -> Path:
    """get plugins directory path (forexternaluse) """
    return _get_plugins_dir()


def reload_all_plugins():
    """reloadallplugin"""
    global _loaded_plugins, _plugins_loaded
    # cleanupall
    for name, data in _loaded_plugins.items():
        data["ctx"]._cleanup()
    _loaded_plugins.clear()
    _plugins_loaded = False
    # renewload
    load_all_plugins()
    # renewhangloadbutton
    manager = get_hook_manager()
    bridge = manager.get_ui_bridge()
    if bridge:
        bridge.mount_buttons()


# ============================================================
# decorative  API — letplugincodemoreconcise
# ============================================================

# decorative collectset  (used forautoregistermode) 
_pending_hooks: List[Tuple[str, Callable, int]] = []
_pending_tools: List[Dict[str, Any]] = []
_pending_buttons: List[Dict[str, Any]] = []


def hook(event: str, priority: int = 0):
    """decorative : registereventhook

    usemethod:
        @hook("on_after_tool")
        def my_callback(tool_name, args, result):
            print(f"Tool {tool_name} called")
    """
    def decorator(func):
        _pending_hooks.append((event, func, priority))
        return func
    return decorator


def tool(name: str, description: str, parameters: dict):
    """decorative : registercustomtool

    usemethod:
        @tool(name="my_tool", description="...", parameters={...})
        def handler(args):
            return {"success": True, "result": "..."}
    """
    def decorator(func):
        _pending_tools.append({
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": func,
        })
        return func
    return decorator


def ui_button(icon: str, tooltip: str):
    """decorative : register UI button

    usemethod:
        @ui_button(icon="📊", tooltip="Stats")
        def on_click(ctx):
            print("Clicked!")
    """
    def decorator(func):
        _pending_buttons.append({
            "icon": icon,
            "tooltip": tooltip,
            "callback": func,
        })
        return func
    return decorator


def _apply_decorators(ctx: PluginContext):
    """willdecorative collectset hook/tool/buttonregisterto ctx"""
    global _pending_hooks, _pending_tools, _pending_buttons

    for event, callback, priority in _pending_hooks:
        ctx.on(event, callback, priority)
    for t in _pending_tools:
        ctx.register_tool(
            name=t["name"], description=t["description"],
            schema=t["parameters"], handler=t["handler"],
        )
    for b in _pending_buttons:
        ctx.register_button(
            icon=b["icon"], tooltip=b["tooltip"], callback=b["callback"],
        )

    # clearemptycollectset 
    _pending_hooks = []
    _pending_tools = []
    _pending_buttons = []


# ============================================================
# singleexampleget 
# ============================================================

def get_hook_manager() -> HookManager:
    """getglobal HookManager singleexample"""
    return HookManager()
