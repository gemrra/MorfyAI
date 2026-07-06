# -*- coding: utf-8 -*-
"""
MorfyAI Web Panel — the redesign, rendered 1:1 from the HTML mockup, driven by
the REAL AITab engine.

Architecture: this panel builds a real `AITab` instance (the exact class the
old Qt panel uses) but never shows its widgets. All chat/tool/session logic —
system-prompt injections (rules, memory, role, sim/build/refine policy),
context auto-compression, node-op checkpoints (undo/keep), confirm mode, plan
mode, reflection, hooks — runs completely unchanged inside that hidden AITab.
This file's only job is to:
  1. drive AITab's real input path (set text into its real input box, click
     its real send/stop) instead of reimplementing the agent loop, and
  2. forward AITab's existing Qt signals to the QWebChannel bridge so the
     mockup HTML can render them.

This means every feature the old panel has "for free" — the web UI is a view,
not a second engine.

Launch (standalone):

    import sys; sys.path.insert(0, r"E:/AILocal/MorfyAI")
    import launch_web; launch_web.show()
"""

import os
import json
import time

from morfyai.qt_compat import QtWidgets, QtCore, QtGui

try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


_WEBUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui")


class Bridge(QtCore.QObject):
    """Python side of the QWebChannel bridge. Thin — the engine (AITab) does the work."""

    thinking = QtCore.Signal(str)
    content = QtCore.Signal(str)
    toolCall = QtCore.Signal(str)      # json {name}
    toolResult = QtCore.Signal(str)    # json {name, ok}
    turnDone = QtCore.Signal()
    turnError = QtCore.Signal(str)
    mcpStatus = QtCore.Signal(bool)
    contextUsage = QtCore.Signal(int)
    sessionsChanged = QtCore.Signal(str)
    titleChanged = QtCore.Signal(str)
    panelError = QtCore.Signal(str)
    nodeOps = QtCore.Signal(str)        # json: list of new ops for the current turn
    opsCountChanged = QtCore.Signal(int)  # pending-ops count → batch bar
    confirmRequest = QtCore.Signal(str)  # json {tool, args}
    askQuestionRequest = QtCore.Signal(str)  # json: list of questions
    planReady = QtCore.Signal(str)       # json: full plan_data, awaiting user decision
    planStepUpdate = QtCore.Signal(str)  # json {stepId, status, summary}
    todoUpdate = QtCore.Signal(str)      # json {id, text, status}
    fontScaleChanged = QtCore.Signal(int)  # broadcast UI font scale % across all open windows
    modelsChanged = QtCore.Signal(str)  # json {models, model} — broadcast so the MAIN
    # window's composer dropdown updates even when the change (provider switch, model
    # enable/disable toggle) happened from the separate Settings window's own document.

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def _err(self, where, e):
        msg = "%s: %s" % (where, e)
        _dbg("[WebPanel] " + msg)
        try:
            self.panelError.emit(msg)
        except Exception:
            pass

    # ---------- bootstrap ----------
    @QtCore.Slot(result=str)
    def bootstrap(self):
        try:
            o = self.owner
            return json.dumps({
                "models": o.list_enabled_models(),
                "model": o.current_model(),
                "provider": o.current_provider(),
                "providers": o.list_providers(),
                "mcp": o.mcp_running(),
                "mode": o.current_mode(),
                "confirmMode": o.confirm_mode(),
                "sessions": o.sessions_summary(),
                "context": o.context_pct(),
                "effort": o.current_effort(),
                "effortCapability": o.effort_capability(),
            })
        except Exception as e:
            self._err("bootstrap failed", e)
            return json.dumps({"models": [], "model": "", "provider": "", "mcp": False, "sessions": []})

    # ---------- model / provider / mode ----------
    @QtCore.Slot(str)
    def setModel(self, model):
        try:
            self.owner.set_model(model)
        except Exception as e:
            self._err("setModel failed", e)

    @QtCore.Slot(str, result=str)
    def setProvider(self, provider):
        try:
            self.owner.set_provider(provider)
            return json.dumps({"models": self.owner.list_models(), "model": self.owner.current_model()})
        except Exception as e:
            self._err("setProvider failed", e)
            return json.dumps({"models": [], "model": ""})

    @QtCore.Slot(str, str, result=str)
    def modelInfo(self, provider, model):
        try:
            return json.dumps(self.owner.model_info(provider, model))
        except Exception as e:
            self._err("modelInfo failed", e)
            return json.dumps({"contextLimit": None, "supportsVision": False})

    @QtCore.Slot(str, result=str)
    def getCustomProviderConfig(self, provider_id):
        try:
            return json.dumps(self.owner.get_custom_provider_config(provider_id or "custom"))
        except Exception as e:
            self._err("getCustomProviderConfig failed", e)
            return json.dumps({})

    @QtCore.Slot(str, result=str)
    def getProviderConnectionInfo(self, provider_id):
        try:
            return json.dumps(self.owner.get_provider_connection_info(provider_id))
        except Exception as e:
            self._err("getProviderConnectionInfo failed", e)
            return json.dumps({"name": provider_id, "apiUrl": "", "editable": False})

    @QtCore.Slot(str, str, result=str)
    def saveCustomProviderConfig(self, provider_id, cfg_json):
        try:
            self.owner.save_custom_provider_config(provider_id or "custom", json.loads(cfg_json or "{}"))
            return json.dumps({"models": self.owner.list_models(), "providers": self.owner.list_providers()})
        except Exception as e:
            self._err("saveCustomProviderConfig failed", e)
            return json.dumps({"models": [], "providers": []})

    @QtCore.Slot(str, str, str, result=str)
    def fetchCustomModels(self, provider_id, api_url, api_key):
        try:
            return json.dumps(self.owner.fetch_custom_models(provider_id or "custom", api_url, api_key))
        except Exception as e:
            self._err("fetchCustomModels failed", e)
            return json.dumps([])

    @QtCore.Slot(str, result=str)
    def addCustomProvider(self, name):
        try:
            provider_id = self.owner.add_custom_provider(name)
            return json.dumps({"providerId": provider_id, "providers": self.owner.list_providers()})
        except Exception as e:
            self._err("addCustomProvider failed", e)
            return json.dumps({"providerId": None, "providers": []})

    @QtCore.Slot(str, result=str)
    def removeCustomProvider(self, provider_id):
        try:
            self.owner.remove_custom_provider(provider_id)
            return json.dumps({
                "providers": self.owner.list_providers(),
                "provider": self.owner.current_provider(),
            })
        except Exception as e:
            self._err("removeCustomProvider failed", e)
            return json.dumps({"providers": [], "provider": ""})

    @QtCore.Slot(str, bool, result=str)
    def setProviderEnabled(self, provider_id, enabled):
        try:
            self.owner.set_provider_enabled(provider_id, bool(enabled))
            return json.dumps({"providers": self.owner.list_providers()})
        except Exception as e:
            self._err("setProviderEnabled failed", e)
            return json.dumps({"providers": []})

    @QtCore.Slot(str)
    def setMode(self, mode):
        try:
            self.owner.set_mode(mode)
        except Exception as e:
            self._err("setMode failed", e)

    @QtCore.Slot(bool)
    def setConfirmMode(self, on):
        try:
            self.owner.set_confirm_mode(bool(on))
        except Exception as e:
            self._err("setConfirmMode failed", e)

    @QtCore.Slot(str)
    def setEffort(self, level):
        try:
            self.owner.set_effort(level)
        except Exception as e:
            self._err("setEffort failed", e)

    @QtCore.Slot(result=str)
    def effortCapability(self):
        try:
            return json.dumps(self.owner.effort_capability())
        except Exception as e:
            self._err("effortCapability failed", e)
            return json.dumps({"kind": "none", "options": []})

    # ---------- turn ----------
    @QtCore.Slot(str)
    def send(self, text):
        try:
            self.owner.send(text, self)
        except Exception as e:
            import traceback
            self._err("send failed", traceback.format_exc())
            self.turnError.emit(str(e))

    @QtCore.Slot()
    def stop(self):
        try:
            self.owner.stop()
        except Exception as e:
            self._err("stop failed", e)

    @QtCore.Slot(bool)
    def confirmDecision(self, accepted):
        try:
            self.owner.confirm_decision(bool(accepted))
        except Exception as e:
            self._err("confirmDecision failed", e)

    @QtCore.Slot(str)
    def answerQuestions(self, answers_json):
        try:
            self.owner.answer_questions(json.loads(answers_json or "{}"))
        except Exception as e:
            self._err("answerQuestions failed", e)

    @QtCore.Slot()
    def cancelQuestions(self):
        try:
            self.owner.cancel_questions()
        except Exception as e:
            self._err("cancelQuestions failed", e)

    # ---------- plan mode ----------
    @QtCore.Slot(bool)
    def acceptPlan(self, confirm_mode):
        try:
            self.owner.accept_plan(bool(confirm_mode))
        except Exception as e:
            self._err("acceptPlan failed", e)

    @QtCore.Slot()
    def rejectPlan(self):
        try:
            self.owner.reject_plan()
        except Exception as e:
            self._err("rejectPlan failed", e)

    @QtCore.Slot(str)
    def revisePlan(self, feedback):
        try:
            self.owner.revise_plan(feedback, self)
        except Exception as e:
            self._err("revisePlan failed", e)

    # ---------- node-op ledger ----------
    @QtCore.Slot(str)
    def undoOp(self, op_id):
        try:
            self.owner.undo_op(op_id)
        except Exception as e:
            self._err("undoOp failed", e)

    @QtCore.Slot(str)
    def keepOp(self, op_id):
        try:
            self.owner.keep_op(op_id)
        except Exception as e:
            self._err("keepOp failed", e)

    @QtCore.Slot()
    def undoAllOps(self):
        try:
            self.owner.undo_all_ops()
        except Exception as e:
            self._err("undoAllOps failed", e)

    @QtCore.Slot()
    def keepAllOps(self):
        try:
            self.owner.keep_all_ops()
        except Exception as e:
            self._err("keepAllOps failed", e)

    # ---------- sessions ----------
    @QtCore.Slot(result=str)
    def newChat(self):
        try:
            self.owner.new_session()
        except Exception as e:
            self._err("newChat failed", e)
        return json.dumps(self.owner.sessions_summary())

    @QtCore.Slot(str, result=str)
    def switchSession(self, sid):
        try:
            self.owner.switch_session(sid)
        except Exception as e:
            self._err("switchSession failed", e)
        return json.dumps(self.owner.sessions_summary())

    @QtCore.Slot(str, result=str)
    def deleteSession(self, sid):
        try:
            self.owner.delete_session(sid)
        except Exception as e:
            self._err("deleteSession failed", e)
        return json.dumps(self.owner.sessions_summary())

    @QtCore.Slot(str, result=str)
    def sessionHistory(self, sid):
        try:
            return json.dumps(self.owner.session_history(sid))
        except Exception as e:
            self._err("sessionHistory failed", e)
            return json.dumps({"messages": [], "truncated": False})

    @QtCore.Slot(result=int)
    def beforeSendIndex(self):
        try:
            return self.owner.history_length()
        except Exception as e:
            self._err("beforeSendIndex failed", e)
            return -1

    @QtCore.Slot(int, int, str)
    def recordTurnStats(self, duration_ms, tokens, ts):
        try:
            # ts arrives as a string — JS millisecond timestamps overflow a
            # 32-bit Qt int slot param, so we pass/parse it as text instead.
            self.owner.record_turn_stats(duration_ms, tokens, int(ts))
        except Exception as e:
            self._err("recordTurnStats failed", e)


    @QtCore.Slot(int, result=bool)
    def rewindTo(self, index):
        try:
            return bool(self.owner.rewind_to(index))
        except Exception as e:
            self._err("rewindTo failed", e)
            return False

    @QtCore.Slot(str, result=str)
    def createWrangle(self, code):
        try:
            return json.dumps(self.owner.create_wrangle(code))
        except Exception as e:
            self._err("createWrangle failed", e)
            return json.dumps({"ok": False, "message": str(e)})

    @QtCore.Slot(str, result=str)
    def jumpToNode(self, path):
        try:
            return json.dumps(self.owner.jump_to_node(path))
        except Exception as e:
            self._err("jumpToNode failed", e)
            return json.dumps({"ok": False, "message": str(e)})

    @QtCore.Slot(result=str)
    def nodePaths(self):
        try:
            return json.dumps(self.owner.node_paths())
        except Exception as e:
            self._err("nodePaths failed", e)
            return json.dumps([])

    @QtCore.Slot(result=str)
    def exportTrainingData(self):
        try:
            return json.dumps(self.owner.export_training_data())
        except Exception as e:
            self._err("exportTrainingData failed", e)
            return json.dumps({"ok": False, "message": str(e)})

    @QtCore.Slot(str)
    def openExternalUrl(self, url):
        try:
            url = (url or "").strip()
            if url.startswith(("http://", "https://")):
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        except Exception as e:
            self._err("openExternalUrl failed", e)

    @QtCore.Slot(str, str, result=str)
    def renameSession(self, sid, new_title):
        try:
            self.owner.rename_session(sid, new_title)
        except Exception as e:
            self._err("renameSession failed", e)
        return json.dumps(self.owner.sessions_summary())

    # ---------- providers / keys ----------
    @QtCore.Slot(str, str, result=str)
    def saveApiKey(self, provider, key):
        try:
            return self.owner.save_api_key(provider, key)
        except Exception as e:
            self._err("saveApiKey failed", e)
            return "error"

    @QtCore.Slot(str, result=str)
    def keyStatus(self, provider):
        try:
            return self.owner.key_status(provider)
        except Exception as e:
            self._err("keyStatus failed", e)
            return "none"

    @QtCore.Slot(result=str)
    def mcpSetupPrompt(self):
        return self.owner.mcp_setup_prompt()

    @QtCore.Slot(result=str)
    def mcpInfo(self):
        try:
            return json.dumps({"text": self.owner.mcp_info_text()})
        except Exception as e:
            self._err("mcpInfo failed", e)
            return json.dumps({"text": "MCP status unavailable"})

    @QtCore.Slot()
    def mcpStart(self):
        try:
            self.owner.mcp_start()
        except Exception as e:
            self._err("mcpStart failed", e)

    @QtCore.Slot(result=str)
    def mcpConnectionReport(self):
        try:
            return json.dumps(self.owner.mcp_connection_report())
        except Exception as e:
            self._err("mcpConnectionReport failed", e)
            return json.dumps({"url": "", "serverRunning": False, "claudeConnected": False})

    @QtCore.Slot(result=str)
    def usageStats(self):
        try:
            return json.dumps(self.owner.usage_stats())
        except Exception as e:
            self._err("usageStats failed", e)
            return json.dumps({"totalTokens": 0, "cost": 0.0, "requests": 0})

    @QtCore.Slot(result=str)
    def hipInfo(self):
        try:
            path, name = self.owner.hip_info()
            return json.dumps({"path": path, "name": name})
        except Exception as e:
            self._err("hipInfo failed", e)
            return json.dumps({"path": "", "name": "untitled.hip"})

    @QtCore.Slot()
    def openHipFolder(self):
        try:
            self.owner.open_hip_folder()
        except Exception as e:
            self._err("openHipFolder failed", e)

    @QtCore.Slot()
    def refreshMcp(self):
        try:
            self.mcpStatus.emit(bool(self.owner.mcp_running()))
        except Exception:
            self.mcpStatus.emit(False)

    @QtCore.Slot(str, result=str)
    def attachImage(self, data_url):
        try:
            return self.owner.attach_image(data_url)
        except Exception as e:
            self._err("attachImage failed", e)
            return "error"

    @QtCore.Slot(result=str)
    def getPendingImages(self):
        try:
            return json.dumps(self.owner.get_pending_images())
        except Exception as e:
            self._err("getPendingImages failed", e)
            return json.dumps([])

    @QtCore.Slot(int, result=str)
    def removePendingImage(self, index):
        try:
            return json.dumps(self.owner.remove_pending_image(index))
        except Exception as e:
            self._err("removePendingImage failed", e)
            return json.dumps([])

    # ---------- staged context (selection / scene / viewport) — attach, don't auto-send ----------
    @QtCore.Slot(str, result=str)
    def stageReadSelection(self, current_text):
        try:
            return json.dumps(self.owner.stage_read_selection(current_text))
        except Exception as e:
            self._err("stageReadSelection failed", e)
            return json.dumps({"ok": False, "text": current_text or ""})

    @QtCore.Slot(str, result=str)
    def stageReadViewport(self, current_text):
        try:
            return json.dumps(self.owner.stage_read_viewport(current_text))
        except Exception as e:
            self._err("stageReadViewport failed", e)
            return json.dumps({"ok": False, "text": current_text or ""})

    @QtCore.Slot(str, result=str)
    def stageAnalyzeScene(self, current_text):
        try:
            return json.dumps(self.owner.stage_analyze_scene(current_text))
        except Exception as e:
            self._err("stageAnalyzeScene failed", e)
            return json.dumps({"ok": False, "text": current_text or ""})

    # ---------- settings dialogs (reuse the real, tested ones) ----------
    @QtCore.Slot(str)
    def openDialog(self, key):
        try:
            self.owner.open_dialog(key)
        except Exception as e:
            self._err("openDialog(%s) failed" % key, e)

    @QtCore.Slot(result=str)
    def cacheSettings(self):
        try:
            return json.dumps(self.owner.get_cache_settings())
        except Exception as e:
            self._err("cacheSettings failed", e)
            return json.dumps({"autoSaveCache": True, "autoOptimize": True, "optimizationStrategy": "balanced"})

    @QtCore.Slot(bool)
    def setAutoSaveCache(self, on):
        try:
            self.owner.set_auto_save_cache(on)
        except Exception as e:
            self._err("setAutoSaveCache failed", e)

    @QtCore.Slot(bool)
    def setAutoOptimize(self, on):
        try:
            self.owner.set_auto_optimize(on)
        except Exception as e:
            self._err("setAutoOptimize failed", e)

    @QtCore.Slot(str)
    def setOptimizationStrategy(self, value):
        try:
            self.owner.set_optimization_strategy(value)
        except Exception as e:
            self._err("setOptimizationStrategy failed", e)

    # ---------- About / Debug / Rules / Plugins / Memory — all inline now ----------
    @QtCore.Slot(result=str)
    def aboutInfo(self):
        try:
            return json.dumps(self.owner.get_about_info())
        except Exception as e:
            self._err("aboutInfo failed", e)
            return json.dumps({})

    @QtCore.Slot(result=str)
    def debugLog(self):
        try:
            return self.owner.get_debug_log()
        except Exception as e:
            self._err("debugLog failed", e)
            return ""

    @QtCore.Slot()
    def clearDebugLog(self):
        try:
            self.owner.clear_debug_log()
        except Exception as e:
            self._err("clearDebugLog failed", e)

    @QtCore.Slot(result=str)
    def getRules(self):
        try:
            return json.dumps(self.owner.get_rules())
        except Exception as e:
            self._err("getRules failed", e)
            return json.dumps([])

    @QtCore.Slot(str, str, str, bool, result=str)
    def saveRule(self, rule_id, title, content, enabled):
        try:
            return self.owner.save_rule(rule_id, title, content, enabled)
        except Exception as e:
            self._err("saveRule failed", e)
            return ""

    @QtCore.Slot(str, result=bool)
    def deleteRule(self, rule_id):
        try:
            return self.owner.delete_rule_entry(rule_id)
        except Exception as e:
            self._err("deleteRule failed", e)
            return False

    @QtCore.Slot(result=str)
    def getToolsList(self):
        try:
            return json.dumps(self.owner.get_tools_list())
        except Exception as e:
            self._err("getToolsList failed", e)
            return json.dumps([])

    @QtCore.Slot(str, bool)
    def setToolEnabled(self, name, enabled):
        try:
            self.owner.set_tool_enabled(name, enabled)
        except Exception as e:
            self._err("setToolEnabled failed", e)

    @QtCore.Slot(result=str)
    def getPlugins(self):
        try:
            return json.dumps(self.owner.get_plugins())
        except Exception as e:
            self._err("getPlugins failed", e)
            return json.dumps([])

    @QtCore.Slot(str, bool, result=bool)
    def setPluginEnabled(self, name, enabled):
        try:
            return self.owner.set_plugin_enabled(name, enabled)
        except Exception as e:
            self._err("setPluginEnabled failed", e)
            return False

    @QtCore.Slot(str, result=bool)
    def reloadPlugin(self, name):
        try:
            return self.owner.reload_plugin(name)
        except Exception as e:
            self._err("reloadPlugin failed", e)
            return False

    @QtCore.Slot(result=str)
    def reloadAllPlugins(self):
        try:
            return json.dumps(self.owner.reload_all_plugins())
        except Exception as e:
            self._err("reloadAllPlugins failed", e)
            return json.dumps([])

    @QtCore.Slot()
    def openPluginsFolder(self):
        try:
            self.owner.open_plugins_folder()
        except Exception as e:
            self._err("openPluginsFolder failed", e)

    @QtCore.Slot(result=str)
    def getSkills(self):
        try:
            return json.dumps(self.owner.get_skills())
        except Exception as e:
            self._err("getSkills failed", e)
            return json.dumps([])

    @QtCore.Slot(result=str)
    def getSkillDir(self):
        try:
            return self.owner.get_skill_dir()
        except Exception as e:
            self._err("getSkillDir failed", e)
            return ""

    @QtCore.Slot(result=str)
    def browseSkillDir(self):
        try:
            return json.dumps(self.owner.browse_skill_dir())
        except Exception as e:
            self._err("browseSkillDir failed", e)
            return json.dumps({"dir": "", "skills": []})

    @QtCore.Slot(result=bool)
    def getMemoryEnabled(self):
        try:
            return self.owner.get_memory_enabled()
        except Exception as e:
            self._err("getMemoryEnabled failed", e)
            return False

    @QtCore.Slot(bool, result=bool)
    def setMemoryEnabled(self, enabled):
        try:
            return self.owner.set_memory_enabled_pref(enabled)
        except Exception as e:
            self._err("setMemoryEnabled failed", e)
            return False

    @QtCore.Slot(str, result=str)
    def getMemoryRecords(self, tier):
        try:
            return json.dumps(self.owner.get_memory_records(tier))
        except Exception as e:
            self._err("getMemoryRecords failed", e)
            return json.dumps([])

    @QtCore.Slot(str, str, result=bool)
    def deleteMemoryRecord(self, tier, record_id):
        try:
            return self.owner.delete_memory_record(tier, record_id)
        except Exception as e:
            self._err("deleteMemoryRecord failed", e)
            return False

    @QtCore.Slot(str)
    def openSettingsWindow(self, target_page=""):
        try:
            self.owner.open_settings_window(target_page or "")
        except Exception as e:
            self._err("openSettingsWindow failed", e)

    @QtCore.Slot()
    def closeSettingsWindow(self):
        try:
            self.owner.close_settings_window()
        except Exception as e:
            self._err("closeSettingsWindow failed", e)

    @QtCore.Slot(int)
    def setFontScale(self, pct):
        try:
            self.owner.apply_font_scale(pct)
            self.fontScaleChanged.emit(int(pct))
        except Exception as e:
            self._err("setFontScale failed", e)


def _grant_clipboard_permission(page):
    """navigator.clipboard.writeText() (used by the chat/code-block copy
    buttons) is the modern async Clipboard API — unlike execCommand('copy'),
    Chromium requires the page to hold the clipboard-write permission for
    it, which QWebEnginePage does NOT grant by default. Without this, the
    promise silently rejects (swallowed by the JS's own .catch), so the
    "Copy" button looked like it worked (UI flash) but nothing ever reached
    the clipboard. Auto-grant it here since this is fully first-party,
    locally-loaded content — there's no real permission decision to make.
    """
    try:
        from PySide6.QtWebEngineCore import QWebEnginePage

        def _on_permission_requested(url, feature):
            try:
                page.setFeaturePermission(url, feature, QWebEnginePage.PermissionGrantedByUser)
            except Exception:
                pass
        page.featurePermissionRequested.connect(_on_permission_requested)
    except Exception:
        pass
    try:
        # Newer PySide6 (Qt6.8+) uses a permission-request object API instead
        # of the feature/PermissionGrantedByUser enum above.
        def _on_permission_request(request):
            try:
                request.grant()
            except Exception:
                pass
        page.permissionRequested.connect(_on_permission_request)
    except Exception:
        pass


def _make_web_view_class():
    """Built lazily so importing this module doesn't require QtWebEngine."""
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class MorfyWebView(QWebEngineView):
        """QWebEngineView that also accepts a Houdini node-path drag from the
        Network Editor (plain-text mime, like the old ChatInput widget) and
        forwards it into the composer field via JS."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAcceptDrops(True)

        @staticmethod
        def _dragged_node_path(event):
            mime = event.mimeData()
            if not mime.hasText():
                return None
            text = mime.text().strip()
            if text.startswith('/') and '/' in text[1:]:
                return text
            return None

        def dragEnterEvent(self, event):
            if self._dragged_node_path(event) is not None:
                event.acceptProposedAction()
                return
            super().dragEnterEvent(event)

        def dragMoveEvent(self, event):
            if self._dragged_node_path(event) is not None:
                event.acceptProposedAction()
                return
            super().dragMoveEvent(event)

        def dropEvent(self, event):
            path = self._dragged_node_path(event)
            if path is not None:
                js = "window.__insertNodePath && window.__insertNodePath(%s);" % json.dumps(path)
                self.page().runJavaScript(js)
                event.acceptProposedAction()
                return
            super().dropEvent(event)

    return MorfyWebView


class MorfyWebPanel(QtWidgets.QWidget):
    """QWebEngineView host for the MorfyAI redesign — a view over a headless AITab."""

    def __init__(self, parent=None, workspace_dir=None):
        super().__init__(parent)
        self.setObjectName("morfyWebPanel")
        self.setMinimumSize(380, 560)

        self._bridge_ref = None   # the live Bridge, so engine-signal forwarders can reach it
        self._op_labels = {}      # op_id -> NodeOperationLabel (for undo/keep)
        self._op_counter = 0
        self._known_op_labels = set()  # id(label) already forwarded to JS
        self._last_plan_data = None    # the plan awaiting the user's accept/revise/reject
        self._settings_win = None      # separate top-level Settings window (lazy-created)
        self._font_scale_pct = 100     # native Qt page zoom %, shared across all open windows

        # ---- build the REAL engine, hidden ----
        # web_headless=True from the very first line of AITab.__init__ — so
        # even startup session-restore (which renders history into widgets)
        # skips that work instead of building a widget tree nobody sees.
        from .ai_tab import AITab
        self.engine = AITab(parent=self, workspace_dir=workspace_dir, web_headless=True)
        self.engine.hide()
        self._wire_engine_signals()

        self._disabled_providers = self._load_disabled_providers()
        custom_name = self._load_custom_provider_name()
        if custom_name != 'Custom':
            self.engine._custom_provider_config['name'] = custom_name
            for i in range(self.engine.provider_combo.count()):
                if self.engine.provider_combo.itemData(i) == 'custom':
                    self.engine.provider_combo.setItemText(i, custom_name)
                    break

        # ---- restore any additional custom-provider profiles ("Add Provider") ----
        self._extra_custom = {}
        for profile in self._load_extra_custom_providers():
            pid = profile.get('id')
            if pid:
                self._extra_custom[pid] = profile
                self._register_extra_custom_provider(pid, profile)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtCore import QUrl

        MorfyWebView = _make_web_view_class()
        self.view = MorfyWebView(self)
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            st = self.view.settings()
            st.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            st.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        except Exception:
            pass
        self.channel = QWebChannel(self.view.page())
        self.bridge = Bridge(self)
        self._bridge_ref = self.bridge
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        _grant_clipboard_permission(self.view.page())

        index_path = os.path.join(_WEBUI_DIR, "index.html")
        self.view.setUrl(QUrl.fromLocalFile(index_path))
        lay.addWidget(self.view)

    # ================================================================
    # Engine signal forwarding — connected IN ADDITION to AITab's own
    # internal connections, so the real widget-building logic still runs
    # (harmlessly, into hidden widgets) and we just also mirror it to JS.
    # ================================================================
    def _wire_engine_signals(self):
        e = self.engine
        e._appendContent.connect(self._fwd_content)
        e._addThinking.connect(self._fwd_thinking)
        e._addNodeOperation.connect(self._fwd_node_operation)
        e._agentDone.connect(self._fwd_turn_done)
        e._agentError.connect(self._fwd_turn_error)
        e._agentStopped.connect(self._fwd_turn_stopped)
        e._autoTitleDone.connect(self._fwd_title_done)
        e._confirmToolRequest.connect(self._fwd_confirm_request, QtCore.Qt.QueuedConnection)
        e._askQuestionRequest.connect(self._fwd_ask_question, QtCore.Qt.QueuedConnection)
        e._showToolStatus.connect(self._fwd_tool_status)
        e._hideToolStatus.connect(self._fwd_tool_hidden)
        e._updateTodo.connect(self._fwd_todo)
        e._renderPlanViewer.connect(self._fwd_plan_ready)
        e._updatePlanStep.connect(self._fwd_plan_step)

    def _b(self):
        return self._bridge_ref

    def _fwd_content(self, text):
        b = self._b()
        if b and text:
            b.content.emit(text)

    def _fwd_thinking(self, text):
        b = self._b()
        if b and text:
            b.thinking.emit(text)

    def _fwd_tool_status(self, tool_name):
        b = self._b()
        if b:
            b.toolCall.emit(json.dumps({"name": tool_name}))
            self._last_tool_name = tool_name

    def _fwd_tool_hidden(self):
        """Fires when a tool call finishes (success or fail — the engine doesn't
        expose per-call success separately here, so we mark it done/ok and let
        the node-op ledger — which does carry success/failure — be the source
        of truth for mutating tools)."""
        b = self._b()
        if b and getattr(self, "_last_tool_name", None):
            b.toolResult.emit(json.dumps({"name": self._last_tool_name, "ok": True}))
            self._last_tool_name = None

    def _fwd_node_operation(self, name, result):
        """Runs AFTER AITab's own _on_add_node_operation (connected first),
        so self.engine._pending_ops already has the new entries. We just
        diff against what we've already forwarded and mirror the rest."""
        b = self._b()
        if not b:
            return
        try:
            new_ops = []
            for entry in self.engine._pending_ops:
                label, op_type, paths, snapshot = entry
                if id(label) in self._known_op_labels:
                    continue
                self._known_op_labels.add(id(label))
                self._op_counter += 1
                op_id = "op%d" % self._op_counter
                self._op_labels[op_id] = label
                param_diff = None
                if op_type == "modify" and isinstance(snapshot, dict) and "param_name" in snapshot:
                    param_diff = {
                        "param": snapshot.get("param_name", ""),
                        "old": str(snapshot.get("old_value", "")),
                        "new": str(snapshot.get("new_value", "")),
                    }
                new_ops.append({
                    "id": op_id,
                    "kind": op_type,
                    "count": len(paths) or 1,
                    "paths": paths,
                    "paramDiff": param_diff,
                })
                # Reflect back into JS when the user decides via the widget itself
                # (shouldn't normally happen headless, but keep in sync defensively)
                label.decided.connect(lambda l=label, oid=op_id: self._on_op_decided(oid))
            if new_ops:
                b.nodeOps.emit(json.dumps(new_ops))
            b.opsCountChanged.emit(len([e for e in self.engine._pending_ops if not e[0]._decided]))
        except Exception as e:
            _dbg("[WebPanel] node-op forward failed: %s" % e)

    def _on_op_decided(self, op_id):
        b = self._b()
        if b:
            try:
                pending = len([e for e in self.engine._pending_ops if not e[0]._decided])
                b.opsCountChanged.emit(pending)
            except Exception:
                pass

    def _fwd_todo(self, todo_id, text, status):
        b = self._b()
        if b:
            b.todoUpdate.emit(json.dumps({"id": todo_id, "text": text, "status": status}))

    def _fwd_turn_done(self, result):
        b = self._b()
        if b:
            b.turnDone.emit()

    def _fwd_turn_error(self, err_text):
        b = self._b()
        if b:
            b.turnError.emit(str(err_text))

    def _fwd_turn_stopped(self):
        b = self._b()
        if b:
            b.turnDone.emit()

    def _fwd_title_done(self, session_id, title):
        b = self._b()
        if b and session_id == self.engine._session_id:
            b.titleChanged.emit(title)
            b.sessionsChanged.emit(json.dumps(self.sessions_summary()))

    def _fwd_confirm_request(self):
        b = self._b()
        if not b:
            return
        tool = getattr(self.engine, "_pending_confirm_tool", "")
        args = getattr(self.engine, "_pending_confirm_args", {})
        try:
            b.confirmRequest.emit(json.dumps({"tool": tool, "args": args}))
        except Exception:
            b.confirmRequest.emit(json.dumps({"tool": tool, "args": {}}))

    def _fwd_ask_question(self):
        b = self._b()
        if not b:
            return
        questions = getattr(self.engine, "_pending_ask_questions", []) or []
        try:
            b.askQuestionRequest.emit(json.dumps(questions))
        except Exception as e:
            _dbg("[WebPanel] ask-question forward failed: %s" % e)
            b.askQuestionRequest.emit(json.dumps([]))

    def _fwd_plan_ready(self, plan_data):
        self._last_plan_data = plan_data
        b = self._b()
        if b:
            try:
                b.planReady.emit(json.dumps(plan_data))
            except Exception as e:
                _dbg("[WebPanel] plan-ready forward failed: %s" % e)

    def _fwd_plan_step(self, step_id, status, summary):
        b = self._b()
        if b:
            b.planStepUpdate.emit(json.dumps({"stepId": step_id, "status": status, "summary": summary}))

    # ================================================================
    # Bridge-facing API — every method here drives the REAL engine widgets
    # / calls the REAL engine methods. No parallel logic.
    # ================================================================

    # ---------- model / provider / mode ----------
    def list_models(self):
        e = self.engine
        provider = e._current_provider()
        return list(e._model_map.get(provider, []))

    def list_enabled_models(self):
        """Every model across every ENABLED provider — the composer's model
        picker shows all of these at once (not just the current provider's),
        so turning two providers on genuinely lets you pick either one's
        models in the same menu."""
        e = self.engine
        result = []
        for i in range(e.provider_combo.count()):
            pid = e.provider_combo.itemData(i)
            if pid in self._disabled_providers:
                continue
            pname = e.provider_combo.itemText(i)
            for mid in e._model_map.get(pid, []):
                result.append({"providerId": pid, "providerName": pname, "id": mid})
        return result

    def list_providers(self):
        e = self.engine
        return [{"id": e.provider_combo.itemData(i), "name": e.provider_combo.itemText(i),
                  "enabled": e.provider_combo.itemData(i) not in self._disabled_providers}
                for i in range(e.provider_combo.count())]

    def _load_disabled_providers(self):
        try:
            from shared.common_utils import load_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            if cfg and cfg.get('disabled_providers'):
                return set(json.loads(cfg['disabled_providers']))
        except Exception:
            pass
        return set()

    def _save_disabled_providers(self):
        try:
            from shared.common_utils import load_config, save_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
            cfg['disabled_providers'] = json.dumps(sorted(self._disabled_providers))
            save_config('ai', cfg, dcc_type='houdini')
        except Exception:
            pass

    def set_provider_enabled(self, provider_id, enabled):
        if enabled:
            self._disabled_providers.discard(provider_id)
        else:
            self._disabled_providers.add(provider_id)
        self._save_disabled_providers()
        self._broadcast_models_changed()

    def current_provider(self):
        return self.engine._current_provider()

    def current_model(self):
        return self.engine.model_combo.currentText()

    def set_provider(self, provider):
        e = self.engine
        for i in range(e.provider_combo.count()):
            if e.provider_combo.itemData(i) == provider:
                e.provider_combo.setCurrentIndex(i)  # fires _on_provider_changed → refreshes model list
                self._broadcast_models_changed()
                return

    def _broadcast_models_changed(self):
        """Emit modelsChanged so every open window's composer dropdown stays
        in sync — the Settings window is a SEPARATE QWebEngineView/document
        from the main chat window, so a plain JS populateModels() call made
        from Settings only ever updates Settings' own (hidden) copy of the
        composer, never the real one the user is looking at."""
        try:
            self.bridge.modelsChanged.emit(json.dumps({
                "models": self.list_enabled_models(),
                "model": self.current_model(),
                "provider": self.current_provider(),
            }))
        except Exception:
            pass

    def set_model(self, model):
        e = self.engine
        idx = e.model_combo.findText(model)
        if idx >= 0:
            e.model_combo.setCurrentIndex(idx)
        else:
            e.model_combo.setEditText(model)
        self._broadcast_models_changed()

    def model_info(self, provider, model):
        e = self.engine
        from ..utils.ai_client import AIClient
        from ..utils.token_optimizer import _match_pricing
        pricing = _match_pricing(model)
        return {
            "contextLimit": e._model_context_limits.get(model),
            "supportsVision": bool(e._model_features.get(model, {}).get('supports_vision', False)),
            "supportsReasoning": AIClient.is_reasoning_model(model),
            "supportsFc": e.client._supports_function_calling(provider, model),
            "inputPrice": pricing.get("input"),
            "outputPrice": pricing.get("output"),
        }

    # -- Custom-provider per-model metadata (context/vision/function-calling/
    # enabled), persisted separately from header.py's plain model-id list so
    # the old Qt panel's format stays untouched but the web UI never needs
    # the user to type capability info by hand. --
    def _load_custom_provider_name(self):
        try:
            from shared.common_utils import load_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            if cfg and cfg.get('custom_provider_name'):
                return cfg['custom_provider_name']
        except Exception:
            pass
        return 'Custom'

    def _save_custom_provider_name(self, name):
        try:
            from shared.common_utils import load_config, save_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
            cfg['custom_provider_name'] = name
            save_config('ai', cfg, dcc_type='houdini')
        except Exception:
            pass

    def _load_custom_model_meta(self):
        try:
            from shared.common_utils import load_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            if cfg and cfg.get('custom_model_meta'):
                return json.loads(cfg['custom_model_meta'])
        except Exception:
            pass
        return {}

    def _save_custom_model_meta(self, meta):
        try:
            from shared.common_utils import load_config, save_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
            cfg['custom_model_meta'] = json.dumps(meta)
            save_config('ai', cfg, dcc_type='houdini')
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Multiple custom-provider profiles ("Add Provider"). The original
    # single 'custom' slot (above/header.py's _custom_provider_config) is
    # left completely untouched — the old Qt Custom Provider dialog keeps
    # working exactly as before. Any ADDITIONAL profiles created from the
    # web Settings live here, each under its own provider id ('custom_2',
    # 'custom_3', ...), with its own combo item, model map and client
    # registration (see ai_client.AIClient._extra_custom_providers).
    # ------------------------------------------------------------------
    def _load_extra_custom_providers(self):
        try:
            from shared.common_utils import load_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            if cfg and cfg.get('extra_custom_providers'):
                return json.loads(cfg['extra_custom_providers'])
        except Exception:
            pass
        return []

    def _save_extra_custom_providers(self):
        try:
            from shared.common_utils import load_config, save_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
            cfg['extra_custom_providers'] = json.dumps(list(self._extra_custom.values()))
            save_config('ai', cfg, dcc_type='houdini')
        except Exception:
            pass

    def _register_extra_custom_provider(self, provider_id, profile):
        e = self.engine
        name = profile.get('name') or provider_id
        found = False
        for i in range(e.provider_combo.count()):
            if e.provider_combo.itemData(i) == provider_id:
                e.provider_combo.setItemText(i, name)
                found = True
                break
        if not found:
            e.provider_combo.addItem(name, provider_id)
        enabled_ids = []
        for m in profile.get('models', []):
            mid = m.get('id')
            if not mid or not m.get('enabled', True):
                continue
            enabled_ids.append(mid)
            e._model_context_limits[mid] = int(m.get('contextLimit') or 128000)
            e._model_features[mid] = {
                'supports_prompt_caching': True,
                'supports_vision': bool(m.get('supportsVision')),
            }
            if m.get('inputPrice') is not None:
                from ..utils.token_optimizer import MODEL_PRICING
                MODEL_PRICING[mid.lower()] = {
                    "input": float(m["inputPrice"]),
                    "input_cache": float(m["inputPrice"]) * 0.25,
                    "output": float(m.get("outputPrice") or 0.0),
                }
        e._model_map[provider_id] = enabled_ids
        e.client.add_custom_provider(provider_id, profile.get('api_url', ''), profile.get('api_key', ''), True)

    def add_custom_provider(self, name):
        n = 2
        while f'custom_{n}' in self._extra_custom:
            n += 1
        provider_id = f'custom_{n}'
        # "custom_2" is just the internal id (numbered because 'custom' is
        # the pre-existing slot) — the display name shouldn't carry that
        # number, since to the user this IS their first added provider.
        profile = {"id": provider_id, "name": (name or '').strip() or "New Provider",
                   "api_url": "", "api_key": "", "models": []}
        self._extra_custom[provider_id] = profile
        self._register_extra_custom_provider(provider_id, profile)
        self._save_extra_custom_providers()
        return provider_id

    def remove_custom_provider(self, provider_id):
        e = self.engine
        if provider_id == 'custom':
            # The original slot is hardcoded into AITab's provider_combo at
            # construction time (header.py) — actually removeItem()-ing it
            # only lasts until the panel widget is next rebuilt (e.g. the
            # Houdini pane being closed/reopened creates a fresh AITab),
            # at which point it silently reappears — confusing, and it was
            # also re-triggering the legacy Qt "Custom Model configuration"
            # dialog on next selection since its stored URL was blank.
            # Disabling + clearing it instead reaches the same practical
            # "gone" result, but persists reliably through the same
            # disabled_providers mechanism as every other provider's toggle.
            e._custom_provider_config.update({
                'api_url': '', 'api_key': '', 'models': [],
                'context_limit': 128000, 'supports_vision': False, 'supports_fc': True,
            })
            e._model_map['custom'] = []
            e._save_custom_provider_config()
            self._save_custom_model_meta({})
            e.client._CUSTOM_API_URL = ''
            e.client._CUSTOM_SUPPORTS_FC = True
            e.client._api_keys.pop('custom', None)
            if e._current_provider() == 'custom':
                for i in range(e.provider_combo.count()):
                    if e.provider_combo.itemData(i) != 'custom':
                        e.provider_combo.setCurrentIndex(i)
                        break
            self.set_provider_enabled('custom', False)  # also broadcasts the updated aggregate
            return

        if provider_id not in self._extra_custom:
            return
        was_current = (e._current_provider() == provider_id)
        for i in range(e.provider_combo.count()):
            if e.provider_combo.itemData(i) == provider_id:
                e.provider_combo.removeItem(i)
                break
        self._extra_custom.pop(provider_id, None)
        e._model_map.pop(provider_id, None)
        self._save_extra_custom_providers()
        try:
            e.client.remove_custom_provider(provider_id)
        except Exception:
            pass
        if was_current and e.provider_combo.count():
            e.provider_combo.setCurrentIndex(0)
        self._broadcast_models_changed()

    def _backfill_price(self, m):
        """Self-heal model records saved before priceEstimated existed (or
        by any older code path) so a stale cache doesn't just show no price
        forever — re-run the same guess used for a fresh fetch."""
        if m.get('inputPrice') is None and not m.get('priceEstimated'):
            from ..utils.ai_client import AIClient
            guess = AIClient.guess_model_capabilities(m.get('id', ''))
            m['inputPrice'] = guess.get('inputPrice')
            m['outputPrice'] = guess.get('outputPrice')
            m['priceEstimated'] = guess.get('priceEstimated', False)
        return m

    def get_provider_connection_info(self, provider_id):
        """Unified Name/API URL/editable info for the Connection card — for a
        built-in provider these are the fixed vendor name/endpoint (shown but
        not editable, so the Providers page reads consistently regardless of
        provider type); for a custom one they're the real editable fields."""
        e = self.engine
        if self._is_custom_provider_id(provider_id):
            cc = self.get_custom_provider_config(provider_id)
            return {"name": cc.get("name", "Custom"), "apiUrl": cc.get("apiUrl", ""), "editable": True}
        name = provider_id
        for i in range(e.provider_combo.count()):
            if e.provider_combo.itemData(i) == provider_id:
                name = e.provider_combo.itemText(i)
                break
        try:
            api_url = e.client._get_api_url(provider_id)
        except Exception:
            api_url = ""
        return {"name": name, "apiUrl": api_url, "editable": False}

    def _is_custom_provider_id(self, provider_id):
        return provider_id == 'custom' or provider_id in self._extra_custom

    def get_custom_provider_config(self, provider_id='custom'):
        if provider_id != 'custom':
            profile = self._extra_custom.get(provider_id, {})
            return {
                "apiUrl": profile.get("api_url", ""),
                "apiKeySet": bool(profile.get("api_key", "")),
                "name": profile.get("name", provider_id),
                "models": [self._backfill_price(dict(m)) for m in profile.get("models", [])],
            }
        e = self.engine
        cc = e._custom_provider_config
        meta = self._load_custom_model_meta()
        models = []
        seen = set()
        for mid in cc.get('models', []):
            mm = meta.get(mid, {})
            models.append(self._backfill_price({
                "id": mid,
                "contextLimit": mm.get("contextLimit") or e._model_context_limits.get(mid, 128000),
                "supportsVision": mm.get("supportsVision", e._model_features.get(mid, {}).get('supports_vision', False)),
                "supportsReasoning": mm.get("supportsReasoning", False),
                "supportsFc": mm.get("supportsFc", True),
                "inputPrice": mm.get("inputPrice"),
                "outputPrice": mm.get("outputPrice"),
                "priceEstimated": mm.get("priceEstimated", False),
                "enabled": True,
            }))
            seen.add(mid)
        for mid, mm in meta.items():
            if mid not in seen and not mm.get('enabled', True):
                models.append(self._backfill_price({
                    "id": mid,
                    "contextLimit": mm.get("contextLimit", 128000),
                    "supportsVision": mm.get("supportsVision", False),
                    "supportsReasoning": mm.get("supportsReasoning", False),
                    "supportsFc": mm.get("supportsFc", True),
                    "inputPrice": mm.get("inputPrice"),
                    "outputPrice": mm.get("outputPrice"),
                    "priceEstimated": mm.get("priceEstimated", False),
                    "enabled": False,
                }))
        return {
            "apiUrl": cc.get("api_url", ""),
            "apiKeySet": bool(cc.get("api_key", "")),
            "name": cc.get("name", "Custom"),
            "models": models,
        }

    def save_custom_provider_config(self, provider_id, cfg):
        if provider_id != 'custom':
            profile = self._extra_custom.setdefault(provider_id, {"id": provider_id, "name": provider_id})
            if cfg.get("apiUrl") is not None:
                profile["api_url"] = cfg["apiUrl"].strip()
            if cfg.get("apiKey"):
                profile["api_key"] = cfg["apiKey"].strip()
            if cfg.get("name"):
                profile["name"] = cfg["name"].strip()
            profile["models"] = cfg.get("models") or []
            self._register_extra_custom_provider(provider_id, profile)
            self._save_extra_custom_providers()
            if self.engine._current_provider() == provider_id:
                self.engine._refresh_models(provider_id)
                self.engine._update_key_status()
            self._broadcast_models_changed()
            return

        e = self.engine
        cc = e._custom_provider_config
        if cfg.get("apiUrl") is not None:
            cc["api_url"] = cfg["apiUrl"].strip()
        if cfg.get("apiKey"):  # blank = keep the existing stored key
            cc["api_key"] = cfg["apiKey"].strip()
        if cfg.get("name"):
            cc["name"] = cfg["name"].strip()
            for i in range(e.provider_combo.count()):
                if e.provider_combo.itemData(i) == 'custom':
                    e.provider_combo.setItemText(i, cc["name"])
                    break
            self._save_custom_provider_name(cc["name"])

        model_meta = {}
        enabled_ids = []
        for m in (cfg.get("models") or []):
            mid = (m.get("id") or "").strip()
            if not mid:
                continue
            meta = {
                "contextLimit": int(m.get("contextLimit") or 128000),
                "supportsVision": bool(m.get("supportsVision")),
                "supportsReasoning": bool(m.get("supportsReasoning")),
                "supportsFc": bool(m.get("supportsFc", True)),
                "inputPrice": m.get("inputPrice"),
                "outputPrice": m.get("outputPrice"),
                "priceEstimated": bool(m.get("priceEstimated")),
                "enabled": bool(m.get("enabled", True)),
            }
            model_meta[mid] = meta
            if meta["enabled"]:
                enabled_ids.append(mid)
                e._model_context_limits[mid] = meta["contextLimit"]
                e._model_features[mid] = {
                    'supports_prompt_caching': True,
                    'supports_vision': meta["supportsVision"],
                }
                if meta.get("inputPrice") is not None:
                    # Register real per-token pricing so the existing usage/
                    # cost tracker (token_optimizer) prices custom-provider
                    # calls correctly instead of falling back to its default.
                    from ..utils.token_optimizer import MODEL_PRICING
                    MODEL_PRICING[mid.lower()] = {
                        "input": float(meta["inputPrice"]),
                        "input_cache": float(meta["inputPrice"]) * 0.25,
                        "output": float(meta["outputPrice"] or 0.0),
                    }

        cc["models"] = enabled_ids
        if enabled_ids:
            first = model_meta[enabled_ids[0]]
            cc["context_limit"] = first["contextLimit"]
            cc["supports_vision"] = first["supportsVision"]
            cc["supports_fc"] = first["supportsFc"]
        e._model_map['custom'] = enabled_ids
        e._sync_custom_to_client()
        e._save_custom_provider_config()
        self._save_custom_model_meta(model_meta)
        if e._current_provider() == 'custom':
            e._refresh_models('custom')
            e._update_key_status()
        self._broadcast_models_changed()

    def fetch_custom_models(self, provider_id, api_url, api_key):
        try:
            return self.engine.client.get_custom_models(api_url, api_key, provider_id or 'custom')
        except Exception:
            return []

    def current_mode(self):
        idx = self.engine.mode_combo.currentIndex()
        return {0: "auto", 1: "ask", 2: "plan"}.get(idx, "auto")

    def set_mode(self, mode):
        idx = {"auto": 0, "agent": 0, "plan": 2}.get((mode or "auto").lower(), 0)
        self.engine.mode_combo.setCurrentIndex(idx)

    def set_confirm_mode(self, on):
        self.engine.chk_confirm_mode.setChecked(bool(on))

    def confirm_mode(self):
        return bool(self.engine.chk_confirm_mode.isChecked())

    def set_effort(self, level):
        """Stores the requested effort level; _run_agent resolves it against
        the current model's real capability (reasoning_capabilities.py,
        modeled on how OpenCode/models.dev classify per-model reasoning
        control) — effort vs budget_tokens vs boolean-only vs unsupported."""
        e = self.engine
        level = (level or "medium").lower()
        e._effort_level = level
        e.think_check.setChecked(level != "low")

    def current_effort(self):
        return (getattr(self.engine, "_effort_level", None) or
                ("medium" if self.engine.think_check.isChecked() else "low")).capitalize()

    def effort_capability(self):
        """Which effort levels the CURRENT model actually supports, for the
        composer's effort dropdown to gray out/hide what won't do anything."""
        from morfyai.utils.reasoning_capabilities import get_reasoning_capability
        e = self.engine
        return get_reasoning_capability(e.model_combo.currentText(), e._current_provider())

    # ---------- turn ----------
    def send(self, text, bridge):
        text = (text or "").strip()
        if not text:
            return
        e = self.engine
        if e._agent_session_id is not None:
            bridge.turnError.emit("Still working on the previous message — please wait.")
            return
        provider = e._current_provider()
        if provider not in ("ollama",) and not e.client.has_api_key(provider):
            bridge.turnError.emit(
                "No API key set for %s — open Settings › Providers to add one." % provider)
            return
        e.input_edit.setPlainText(text)
        # Record the timestamp HERE, inside the single choke point every
        # caller goes through (JS doSend AND Python callers like
        # revise_plan) — recording it only from the JS side let Python-
        # originated sends (e.g. plan revision) skip it, which silently
        # desynced session_history()'s ordinal-based user_msg_ts alignment
        # for every message after that point in the session.
        self.record_user_message_ts(int(time.time() * 1000))
        e._on_send()  # real send path: builds the AI response card, spawns the real _run_agent thread

    def stop(self):
        self.engine._on_stop()

    def attach_image(self, data_url):
        """data_url: 'data:image/png;base64,....' from a browser FileReader."""
        e = self.engine
        if not e._current_model_supports_vision():
            return "unsupported"
        import base64
        from morfyai.qt_compat import QtGui
        header, _, b64 = (data_url or "").partition(",")
        if not b64:
            return "error"
        raw_bytes = base64.b64decode(b64)
        qimg = QtGui.QImage()
        if not qimg.loadFromData(raw_bytes):
            return "error"
        qimg = e._resize_image_if_needed(qimg, e._MAX_IMAGE_DIMENSION)
        media_type = "image/jpeg" if "jpeg" in header or "jpg" in header else (
            "image/webp" if "webp" in header else "image/png")
        fmt = {"image/jpeg": "JPEG", "image/webp": "WEBP"}.get(media_type, "PNG")
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        qimg.save(buf, fmt, 90 if fmt == "JPEG" else -1)
        out_bytes = buf.data().data()
        buf.close()
        if len(out_bytes) > e._MAX_IMAGE_BYTES and fmt != "JPEG":
            buf2 = QtCore.QBuffer()
            buf2.open(QtCore.QIODevice.WriteOnly)
            qimg.save(buf2, "JPEG", 85)
            out_bytes = buf2.data().data()
            buf2.close()
            media_type = "image/jpeg"
        e._add_pending_image(base64.b64encode(out_bytes).decode("utf-8"), media_type)
        return "ok"

    def get_pending_images(self):
        """Web equivalent of the old Qt panel's inline thumbnail preview
        strip — reads the SAME e._pending_images list the old panel's
        _rebuild_image_preview() draws from, so both stay in sync."""
        e = self.engine
        return [
            {"index": i, "dataUrl": "data:%s;base64,%s" % (mt, b64)}
            for i, entry in enumerate(e._pending_images)
            if entry is not None
            for b64, mt, _thumb in [entry]
        ]

    def remove_pending_image(self, index):
        self.engine._remove_pending_image(index)
        return self.get_pending_images()

    def confirm_decision(self, accepted):
        q = getattr(self.engine, "_confirm_result_queue", None)
        if q is not None:
            q.put(bool(accepted))

    def answer_questions(self, answers):
        q = getattr(self.engine, "_ask_question_result_queue", None)
        if q is not None:
            q.put(answers)

    def cancel_questions(self):
        q = getattr(self.engine, "_ask_question_result_queue", None)
        if q is not None:
            q.put(None)

    # ---------- plan mode ----------
    def accept_plan(self, confirm_mode):
        """Start execution of the pending plan — reuses the real
        _on_plan_confirmed path (spawns the real execution-phase agent run).
        confirm_mode=True additionally gates each mutating tool call behind
        a per-step Cancel/Execute card, same as the standalone Confirm mode."""
        plan_data = self._last_plan_data
        if not plan_data:
            return
        self.engine.chk_confirm_mode.setChecked(bool(confirm_mode))
        self.engine._on_plan_confirmed(plan_data)
        self._last_plan_data = None

    def reject_plan(self):
        self.engine._on_plan_rejected()
        self._last_plan_data = None

    def revise_plan(self, feedback, bridge):
        """Discard the pending plan and continue the same conversation with
        the user's revision feedback — Plan mode re-enters the planning
        phase automatically for a fresh, non-executing turn."""
        self.engine._on_plan_rejected()
        self._last_plan_data = None
        text = (feedback or "").strip() or "Please revise the plan."
        self.send(text, bridge)

    # ---------- node-op ledger ----------
    def undo_op(self, op_id):
        label = self._op_labels.get(op_id)
        if label is not None:
            label._on_undo()

    def keep_op(self, op_id):
        label = self._op_labels.get(op_id)
        if label is not None:
            label._on_keep()

    def undo_all_ops(self):
        self.engine._undo_all_ops()

    def keep_all_ops(self):
        self.engine._keep_all_ops()

    # ---------- sessions (engine's tab bar IS the source of truth) ----------
    def sessions_summary(self):
        e = self.engine
        out = []
        for i in range(e.session_tabs.count()):
            sid = e.session_tabs.tabData(i)
            label = e.session_tabs.tabText(i)
            prefix = getattr(e, "_TAB_RUNNING_PREFIX", "")
            bare = label[len(prefix):] if prefix and label.startswith(prefix) else label
            out.append({"id": sid, "title": bare, "active": i == e.session_tabs.currentIndex()})
        return out

    def new_session(self):
        self.engine._new_session()

    def switch_session(self, sid):
        e = self.engine
        for i in range(e.session_tabs.count()):
            if e.session_tabs.tabData(i) == sid:
                e.session_tabs.setCurrentIndex(i)  # fires _switch_session
                return

    def delete_session(self, sid):
        e = self.engine
        for i in range(e.session_tabs.count()):
            if e.session_tabs.tabData(i) == sid:
                e._close_session_tab(i)
                return

    def rename_session(self, sid, new_title):
        e = self.engine
        target = sid or e._session_id
        for i in range(e.session_tabs.count()):
            if e.session_tabs.tabData(i) == target:
                e.session_tabs.setTabText(i, (new_title or "New chat").strip()[:60])
                e._sync_tabs_backup()
                return

    @staticmethod
    def _extract_text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(p for p in parts if p)
        return ""

    # Replaying an entire long session on every switch was the main cause of
    # the "lag when clicking a session" complaint — both the QWebChannel
    # JSON payload and the DOM rebuild scale with message count. Cap it.
    _HISTORY_REPLAY_LIMIT = 40

    def session_history(self, sid):
        """Plain-text replay of the *tail* of a session's conversation — used
        to repaint the web chat when switching sessions (the real message
        widgets live on the hidden engine and aren't reachable from JS)."""
        e = self.engine
        if sid == e._session_id:
            history = e._conversation_history
        else:
            sdata = e._sessions.get(sid)
            history = sdata.get("conversation_history", []) if sdata else []
        history = history or []
        sdata = e._sessions.get(sid) or {}
        turn_stats = sdata.get("turn_stats", [])
        user_msg_ts = sdata.get("user_msg_ts", [])
        # Scan only a bounded window from the end — avoids walking the full
        # history of very long sessions just to find the last N text turns.
        scan_window = history[-(self._HISTORY_REPLAY_LIMIT * 3):]
        offset = len(history) - len(scan_window)
        # How many assistant/user text-turns precede the scan window — lines
        # up each message with its saved stats/timestamp, which are stored
        # as plain parallel lists (not embedded in the message dicts, since
        # those get sent verbatim to the LLM API).
        assistant_ordinal = sum(
            1 for m in history[:offset]
            if m.get("role") == "assistant" and self._extract_text(m.get("content"))
        )
        user_ordinal = sum(
            1 for m in history[:offset]
            if m.get("role") == "user" and self._extract_text(m.get("content"))
        )
        out = []
        for local_i, msg in enumerate(scan_window):
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            text = self._extract_text(msg.get("content"))
            if not text:
                continue
            entry = {"role": role, "text": text, "index": offset + local_i}
            if role == "assistant":
                if assistant_ordinal < len(turn_stats):
                    entry["stats"] = turn_stats[assistant_ordinal]
                assistant_ordinal += 1
            else:
                if user_ordinal < len(user_msg_ts):
                    entry["ts"] = user_msg_ts[user_ordinal]
                user_ordinal += 1
            out.append(entry)
        truncated = len(out) > self._HISTORY_REPLAY_LIMIT or len(scan_window) < len(history)
        out = out[-self._HISTORY_REPLAY_LIMIT:]
        return {"messages": out, "truncated": truncated}

    def history_length(self):
        return len(self.engine._conversation_history)

    def record_turn_stats(self, duration_ms, tokens, ts):
        """Save a completed turn's duration/token/timestamp so it survives a
        session switch or history replay (session_history() reattaches it)."""
        e = self.engine
        sdata = e._sessions.get(e._session_id)
        if sdata is None:
            return
        sdata.setdefault("turn_stats", []).append(
            {"duration_ms": duration_ms, "tokens": tokens, "ts": ts})

    def record_user_message_ts(self, ts):
        """Save the send-time of the user message just added to history, so
        the timestamp survives a session switch or history replay."""
        e = self.engine
        sdata = e._sessions.get(e._session_id)
        if sdata is None:
            return
        sdata.setdefault("user_msg_ts", []).append(ts)

    def rewind_to(self, index):
        """Truncate the current session's history to before `index` (the
        absolute position returned by session_history()/history_length()) —
        removes that message and everything after it. Read-only, no editing:
        the user re-types whatever they want to say from that point."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        e = self.engine
        history = e._conversation_history
        if index < 0 or index >= len(history):
            return False
        del history[index:]
        sdata = e._sessions.get(e._session_id)
        if sdata is not None:
            sdata["conversation_history"] = history
            stats_list = sdata.get("turn_stats")
            if stats_list is not None:
                remaining_assistant_turns = sum(
                    1 for m in history
                    if m.get("role") == "assistant" and self._extract_text(m.get("content")))
                sdata["turn_stats"] = stats_list[:remaining_assistant_turns]
            ts_list = sdata.get("user_msg_ts")
            if ts_list is not None:
                remaining_user_turns = sum(
                    1 for m in history
                    if m.get("role") == "user" and self._extract_text(m.get("content")))
                sdata["user_msg_ts"] = ts_list[:remaining_user_turns]
        return True

    def create_wrangle(self, code):
        """Create a Wrangle node from a VEX code block in the AI's reply,
        via the same real MCP tool the agent itself uses — so it lands in
        the current network, gets selected, and the view homes to it."""
        code = (code or "").strip()
        if not code:
            return {"ok": False, "message": "No VEX code to create a node from."}
        e = self.engine
        try:
            result = e.mcp.execute_tool("create_wrangle_node", {"vex_code": code})
        except Exception as ex:
            return {"ok": False, "message": str(ex)}
        if not result.get("success"):
            return {"ok": False, "message": result.get("error", "create_wrangle_node failed")}
        return {"ok": True, "message": result.get("message", "Wrangle node created")}

    def jump_to_node(self, path):
        """Select + frame an existing node path mentioned in the AI's reply."""
        path = (path or "").strip()
        if not path:
            return {"ok": False, "message": "Empty node path."}
        try:
            import hou  # type: ignore
        except ImportError:
            return {"ok": False, "message": "Houdini API not available."}
        node = hou.node(path)
        if node is None:
            return {"ok": False, "message": "Node not found: %s" % path}
        try:
            node.setSelected(True, clear_all_selected=True)
            editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                parent = node.parent()
                if parent is not None:
                    editor.setPwd(parent)
                editor.homeToSelection()
        except Exception as ex:
            return {"ok": False, "message": str(ex)}
        return {"ok": True, "message": "Jumped to %s" % path}

    def node_paths(self):
        """All node paths in the scene, for the composer's @-mention popup."""
        roots = ['/obj', '/out', '/shop', '/mat', '/stage', '/img', '/ch']
        try:
            import hou  # type: ignore
        except ImportError:
            return roots
        paths = []
        for ctx in roots:
            try:
                node = hou.node(ctx)
            except Exception:
                node = None
            if node is None:
                continue
            paths.append(ctx)
            try:
                for child in node.allSubChildren():
                    paths.append(child.path())
            except Exception:
                pass
        return paths or roots

    def export_training_data(self):
        e = self.engine
        if not e._conversation_history:
            return {"ok": False, "message": "Nothing to export — this conversation is empty."}
        try:
            from ..utils.training_data_exporter import ChatTrainingExporter
            exporter = ChatTrainingExporter()
            filepath = exporter.export_conversation(
                e._conversation_history,
                system_prompt=getattr(e, "_system_prompt", None),
                split_by_user=True,
            )
        except Exception as ex:
            return {"ok": False, "message": str(ex)}
        self._reveal_in_explorer(filepath)
        return {"ok": True, "message": "Exported to %s" % filepath, "path": filepath}

    @staticmethod
    def _reveal_in_explorer(path):
        if not path or not os.path.exists(path):
            return
        path = os.path.normpath(path)
        import subprocess
        import sys as _sys
        if _sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", path])
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    def current_title(self):
        s = self.sessions_summary()
        for item in s:
            if item["active"]:
                return item["title"]
        return "New chat"

    # ---------- usage / context ----------
    def context_pct(self):
        e = self.engine
        try:
            total = e._token_stats.get("total_tokens", 0)
            limit = e._get_current_context_limit()
            return max(0, min(100, int(total * 100 / max(1, limit))))
        except Exception:
            return 0

    def usage_stats(self):
        s = self.engine._token_stats
        records = getattr(self.engine, '_call_records', None) or []
        # Context occupancy tracks the LAST call's input size (= full history
        # sent that round), not the cumulative sum across every call — the
        # latter only ever grows and never reflects the real window usage.
        last_input_tokens = records[-1].get('input_tokens', 0) if records else 0
        model = self.current_model()
        context_limit = self.engine._model_context_limits.get(model) or 0
        return {
            "totalTokens": s.get("total_tokens", 0),
            "inputTokens": s.get("input_tokens", 0),
            "outputTokens": s.get("output_tokens", 0),
            "cacheRead": s.get("cache_read", 0),
            "cacheWrite": s.get("cache_write", 0),
            "cost": s.get("estimated_cost", 0.0),
            "requests": s.get("requests", 0),
            "contextTokens": last_input_tokens,
            "contextLimit": context_limit,
        }

    # ---------- providers / keys ----------
    def save_api_key(self, provider, key):
        key = (key or "").strip()
        if key:
            self.engine.client.set_api_key(key, persist=True, provider=provider)
            self.engine._update_key_status()
        return self.key_status(provider)

    def key_status(self, provider):
        try:
            if provider == "ollama":
                return "local"
            if self.engine.client.has_api_key(provider):
                return "set:%s" % self.engine.client.get_masked_key(provider)
            return "none"
        except Exception:
            return "none"

    def mcp_setup_prompt(self):
        try:
            from ..utils import claude_connect as cc
            url = cc.connection_report().get("url", "http://127.0.0.1:9000/mcp")
        except Exception:
            url = "http://127.0.0.1:9000/mcp"
        return ('Add an MCP server named "morfyai-houdini" using the streamable-http '
                'transport at %s' % url)

    def mcp_running(self):
        try:
            from ..utils import claude_connect as cc
            return bool(cc.connection_report().get("server_running"))
        except Exception:
            return False

    def mcp_info_text(self):
        try:
            from ..utils import claude_connect as cc
            report = cc.connection_report()
            url = report.get("url", "?")
            if report.get("claude_connected"):
                return "MCP connected — client attached at %s" % url
            if report.get("server_running"):
                return "MCP server running at %s — waiting for a client" % url
            return "MCP not running yet — open Settings > MCP Server to start it"
        except Exception:
            return "MCP status unavailable"

    def mcp_start(self):
        try:
            from ..utils import claude_connect as cc
            cc.start()
        except Exception:
            pass

    def mcp_connection_report(self):
        """Same live status/config data the old 'Connect to Claude' dialog
        showed (header.py._open_claude_connect) — server running?, Claude
        client connected? (+ seconds since last activity), and copy-pasteable
        Claude Code / Claude Desktop configs — none of which the web page's
        static setup-prompt block ever surfaced."""
        try:
            from ..utils import claude_connect as cc
            report = cc.connection_report()
            return {
                "url": report.get("url", ""),
                "serverRunning": bool(report.get("server_running")),
                "claudeConnected": bool(report.get("claude_connected")),
                "lastActivitySec": report.get("last_client_activity_sec"),
                "claudeCodeCommand": report.get("claude_code_command", ""),
                "claudeCodeJson": report.get("claude_code_json", ""),
                "claudeDesktopJson": report.get("claude_desktop_json", ""),
                "note": report.get("note", ""),
            }
        except Exception:
            return {"url": "", "serverRunning": False, "claudeConnected": False}

    def hip_info(self):
        try:
            import hou
            path = hou.hipFile.path() or ""
            name = hou.hipFile.basename() or "untitled.hip"
            return path, name
        except Exception:
            return "", "untitled.hip"

    def open_hip_folder(self):
        """Reveal the current .hip file in the OS file explorer, selected."""
        path, _ = self.hip_info()
        if not path or not os.path.exists(path):
            return
        path = os.path.normpath(path)
        import subprocess
        import sys as _sys
        if _sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", path])
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    # ---------- staged context (selection / scene) ----------
    def stage_read_selection(self, current_text):
        """Reuses the engine's real _on_read_selection (stages @mentions for
        the selected nodes into the hidden input widget) instead of firing a
        full agent turn — the user can still add their own question first."""
        e = self.engine
        e.input_edit.setPlainText(current_text or "")
        before = e.input_edit.toPlainText()
        e._on_read_selection()
        after = e.input_edit.toPlainText()
        if after == before:
            return {"ok": False, "text": current_text or "", "reason": "No nodes selected in Houdini"}
        return {"ok": True, "text": after}

    def stage_read_viewport(self, current_text):
        """Captures the viewport and queues it on the real engine's pending-
        image list (same queue the file-picker/paste use) — does not send a
        turn, so the user can add their own question before pressing Send."""
        e = self.engine
        if not e._current_model_supports_vision():
            return {"ok": False, "text": current_text or "",
                    "reason": "Model %s doesn't support image input — switch to a vision-capable model" % e.model_combo.currentText()}
        try:
            result = e.mcp.execute_tool("capture_viewport", {})
        except Exception as ex:
            _dbg("[WebPanel] capture_viewport raised: %s" % ex)
            return {"ok": False, "text": current_text or "", "reason": str(ex)}
        if not result.get("success"):
            return {"ok": False, "text": current_text or "", "reason": result.get("error", "capture_viewport failed")}
        b64 = result.get("_viewport_image")
        if not b64:
            return {"ok": False, "text": current_text or "", "reason": "capture succeeded but returned no image data"}
        e._add_pending_image(b64, result.get("_image_media_type", "image/jpeg"))
        return {"ok": True, "text": current_text or ""}

    def stage_analyze_scene(self, current_text):
        e = self.engine
        ctx = e._collect_scene_context()
        parts = []
        if ctx.get("network_path"):
            parts.append("network: %s" % ctx["network_path"])
        names = ctx.get("selected_names") or []
        types = ctx.get("selected_types") or []
        if names:
            pairs = ["%s (%s)" % (n, t) for n, t in zip(names, types)]
            parts.append("selected: " + ", ".join(pairs))
        if not parts:
            return {"ok": False, "text": current_text or "", "reason": "No active network or selection to summarize"}
        note = "[Scene context — %s] " % "; ".join(parts)
        return {"ok": True, "text": note + (current_text or "")}

    # ---------- settings dialogs — the real, tested ones on the real engine ----------
    def open_dialog(self, key):
        e = self.engine
        openers = {
            "rules": e._open_rules_editor,
            "plugins": e._open_plugin_manager,
            "vision": e._open_vision_setup,
            "debug": e._open_debug_console,
            "about": e._open_about_dialog,
            "memory": e._slash_memories,
            "cache": e._on_cache_menu,
            "optimize": e._on_optimize_menu,
            "usage": e._show_token_stats_dialog,
            "archive-cache": e._archive_cache,
            "load-cache": e._load_cache_dialog,
            "compress-summary": e._compress_to_summary,
            "view-caches": e._list_caches,
            "compress-now": e._optimize_now,
        }
        fn = openers.get(key)
        if fn:
            fn()

    # ---------- Context & Cache toggles (real engine attributes) ----------
    def get_cache_settings(self):
        e = self.engine
        return {
            "autoSaveCache": bool(e._auto_save_cache),
            "autoOptimize": bool(e._auto_optimize),
            "optimizationStrategy": e._optimization_strategy.value,
        }

    def set_auto_save_cache(self, on):
        self.engine._auto_save_cache = bool(on)

    def set_auto_optimize(self, on):
        self.engine._auto_optimize = bool(on)

    def set_optimization_strategy(self, value):
        from morfyai.utils.token_optimizer import CompressionStrategy
        try:
            self.engine._optimization_strategy = CompressionStrategy(value)
        except ValueError:
            pass

    # ---------- About (inline, no separate dialog) ----------
    def get_about_info(self):
        import pathlib
        try:
            version_file = pathlib.Path(__file__).resolve().parent.parent.parent / "VERSION"
            version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"
        except Exception:
            version = "unknown"
        return {
            "name": "MorfyAI", "tagline": "Houdini Assistant",
            "subtagline": "Part of the MorfyFX ecosystem", "version": version or "unknown",
            "author": "gemrra",
            "license": "MIT License",
            "discordUrl": "https://discord.gg/vpqC66mUY3",
            "changelogUrl": "https://morfyfx.com/morfyai/changelog",
            "websiteUrl": "",
        }

    # ---------- Debug console (inline) ----------
    def get_debug_log(self):
        from morfyai.utils.debug_log import get_lines
        return "\n".join(get_lines())

    def clear_debug_log(self):
        from morfyai.utils.debug_log import clear
        clear()

    # ---------- Rules (inline) ----------
    def get_rules(self):
        from morfyai.utils.rules_manager import get_all_rules
        return get_all_rules()

    def save_rule(self, rule_id, title, content, enabled):
        from morfyai.utils import rules_manager as rm
        if not rule_id:
            r = rm.add_rule(title, content)
            rm.set_rule_enabled(r["id"], bool(enabled))
            return r["id"]
        rm.update_rule(rule_id, title=title, content=content)
        rm.set_rule_enabled(rule_id, bool(enabled))
        return rule_id

    def delete_rule_entry(self, rule_id):
        from morfyai.utils.rules_manager import delete_rule
        return bool(delete_rule(rule_id))

    # ---------- Plugins & Skills — matches the old PluginManagerDialog's 3
    # tabs (Plugins / Tools / Skills), reusing the exact same backends
    # (hooks.py, tool_registry, skills/) rather than the flat single-tab
    # tools-only view this used to be. ----------
    def get_tools_list(self):
        from morfyai.utils.tool_registry import get_tool_registry
        return get_tool_registry().list_all()

    def set_tool_enabled(self, name, enabled):
        from morfyai.utils.tool_registry import get_tool_registry
        reg = get_tool_registry()
        reg.set_enabled(name, bool(enabled))
        reg.save_disabled_to_config()

    def get_plugins(self):
        from morfyai.utils.hooks import list_plugins
        return list_plugins()

    def set_plugin_enabled(self, name, enabled):
        from morfyai.utils.hooks import enable_plugin, disable_plugin
        return bool(enable_plugin(name) if enabled else disable_plugin(name))

    def reload_plugin(self, name):
        from morfyai.utils.hooks import reload_plugin
        return bool(reload_plugin(name))

    def reload_all_plugins(self):
        from morfyai.utils.hooks import reload_all_plugins
        reload_all_plugins()
        return self.get_plugins()

    def open_plugins_folder(self):
        from morfyai.utils.hooks import get_plugins_dir
        path = str(get_plugins_dir())
        if not os.path.isdir(path):
            return
        import subprocess
        import sys as _sys
        if _sys.platform.startswith("win"):
            subprocess.Popen(["explorer", path])
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def get_skills(self):
        from morfyai.skills import list_skills
        from morfyai.utils.tool_registry import get_tool_registry
        by_name = {t["name"]: t for t in get_tool_registry().list_all()}
        result = []
        for s in list_skills():
            s = dict(s)
            tool = by_name.get("skill__" + s.get("name", ""))
            # Hidden skills (see skills/__init__.py's _register_skills_to_registry)
            # never get registered as a standalone tool, so there's nothing to
            # toggle — reflected as enabled=True/toggleable=False.
            s["enabled"] = tool["enabled"] if tool else True
            s["toggleable"] = tool is not None
            result.append(s)
        return result

    def get_skill_dir(self):
        from morfyai.skills import _get_user_skill_dir
        d = _get_user_skill_dir()
        return str(d) if d else ""

    def browse_skill_dir(self):
        """Native folder picker + persist to config/houdini_ai.ini, same
        [skills] user_skill_dir key the old dialog's _browse_skill_dir()
        wrote — then reload so the newly-pointed directory's skills show up
        immediately without needing a full app restart."""
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(self.window(), "Select skill directory", "")
        if not dir_path:
            return {"dir": self.get_skill_dir(), "skills": self.get_skills()}
        try:
            import configparser
            from pathlib import Path
            config_dir = Path(__file__).resolve().parent.parent.parent / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            ini_path = config_dir / "houdini_ai.ini"
            cfg = configparser.ConfigParser()
            if ini_path.exists():
                cfg.read(str(ini_path), encoding="utf-8")
            if not cfg.has_section("skills"):
                cfg.add_section("skills")
            cfg.set("skills", "user_skill_dir", dir_path)
            with open(ini_path, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass
        from morfyai.skills import reload_skills
        reload_skills()
        return {"dir": dir_path, "skills": self.get_skills()}

    # ---------- Memory (inline; simplified — browse + delete per tier, no
    # add/edit forms yet) ----------
    def get_memory_enabled(self):
        return bool(self.engine._memory_enabled)

    def set_memory_enabled_pref(self, enabled):
        self.engine.set_memory_enabled(bool(enabled))
        return bool(self.engine._memory_enabled)

    def get_memory_records(self, tier):
        from morfyai.utils.memory_store import get_memory_store
        store = get_memory_store()
        if tier == "episodic":
            return [{
                "id": r.id, "timestamp": r.timestamp, "sessionId": r.session_id,
                "task": r.task_description, "result": r.result_summary,
                "success": r.success, "importance": r.importance,
                "reward": r.reward_score, "tags": r.tags,
            } for r in store.get_recent_episodic(limit=50)]
        if tier == "semantic":
            return [{
                "id": r.id, "rule": r.rule, "category": r.category,
                "confidence": r.confidence, "activationCount": r.activation_count,
                "abstractionLevel": r.abstraction_level,
            } for r in store.get_all_semantic()]
        if tier == "procedural":
            return [{
                "id": r.id, "name": r.strategy_name, "description": r.description,
                "priority": r.priority, "successRate": r.success_rate,
                "usageCount": r.usage_count, "conditions": r.conditions,
            } for r in store.get_all_procedural()]
        return []

    def delete_memory_record(self, tier, record_id):
        from morfyai.utils.memory_store import get_memory_store
        store = get_memory_store()
        if tier == "episodic":
            return bool(store.delete_episodic(record_id))
        if tier == "semantic":
            store.delete_semantic(record_id)
            return True
        if tier == "procedural":
            return bool(store.delete_procedural(record_id))
        return False

    # ---------- Settings as a real separate top-level window ----------
    def open_settings_window(self, target_page=""):
        if self._settings_win is not None:
            try:
                self._settings_win.show()
                self._settings_win.raise_()
                self._settings_win.activateWindow()
                if target_page:
                    # Window's already open (and already past its own
                    # bootstrap) — a fresh page load won't happen, so push
                    # the navigation directly into its existing JS instead
                    # of relying on the localStorage flag it'd only read on
                    # first load.
                    try:
                        self._settings_win._view.page().runJavaScript(
                            "if (typeof selectSettingsPage === 'function') selectSettingsPage(%r);" % target_page
                        )
                    except Exception:
                        pass
                return
            except RuntimeError:
                self._settings_win = None  # underlying Qt object was deleted

        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtCore import QUrl

        MorfyWebView = _make_web_view_class()
        win = QtWidgets.QMainWindow(self.window())
        win.setWindowTitle("MorfyAI Settings")
        win.setWindowFlags(QtCore.Qt.Window)
        win.resize(900, 600)

        view = MorfyWebView(win)
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            st = view.settings()
            st.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            st.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        except Exception:
            pass
        channel = QWebChannel(view.page())
        # Reuse the SAME bridge object — every Settings action (save API key,
        # open Rules/Plugins/Memory, etc.) drives the exact same real engine.
        channel.registerObject("bridge", self.bridge)
        view.page().setWebChannel(channel)
        _grant_clipboard_permission(view.page())
        index_path = os.path.join(_WEBUI_DIR, "index.html")
        url = QUrl.fromLocalFile(index_path)
        url.setFragment("settings-standalone")
        view.setUrl(url)
        win.setCentralWidget(view)
        win._view = view  # keep a reference alive
        try:
            view.page().setZoomFactor(max(0.5, min(2.0, self._font_scale_pct / 100.0)))
        except Exception:
            pass
        win.show()
        win.raise_()
        win.activateWindow()
        self._settings_win = win

    def close_settings_window(self):
        if self._settings_win is not None:
            try:
                self._settings_win.close()
            except RuntimeError:
                pass
            self._settings_win = None

    def apply_font_scale(self, pct):
        """Native Qt page zoom instead of CSS `zoom` on body — avoids layout
        breakage (composer clipped by the fixed 100vh/overflow:hidden shell)
        that plain CSS zoom caused at the extremes."""
        self._font_scale_pct = int(pct)
        factor = max(0.5, min(2.0, pct / 100.0))
        try:
            self.view.page().setZoomFactor(factor)
        except Exception:
            pass
        if self._settings_win is not None:
            try:
                self._settings_win._view.page().setZoomFactor(factor)
            except Exception:
                pass
