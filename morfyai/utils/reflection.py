# -*- coding: utf-8 -*-
"""
Reflection module.

Hybrid reflection strategy:
1. Rule-based reflection (after every task): zero-cost, extracts signals from the tool-call chain.
2. LLM deep reflection (every N tasks or condition-triggered): uses a cheap model to produce abstract rules.

This is the AI's "growth engine" — runs automatically after every task.
"""

import json
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

from .memory_store import (
    MemoryStore,
    EpisodicRecord,
    SemanticRecord,
    ProceduralRecord,
    get_memory_store,
)
from .reward_engine import RewardEngine, get_reward_engine

# ============================================================
# reflectionconfig
# ============================================================

# LLM deep-reflection interval (trigger once every N tasks)
DEEP_REFLECT_INTERVAL = 5
# Error-rate spike threshold (trigger urgent reflection)
ERROR_RATE_SPIKE_THRESHOLD = 0.5

# LLM reflection prompt template
REFLECTION_PROMPT = """You are a self-improving AI assistant. Analyze the recent completed-task records and extract reusable experience rules.

## Task records
{episodic_summaries}

## Requirements
Analyze these tasks and extract:
1. **Reusable experience rules**: summarize patterns from successes and failures
2. **Strategy updates**: which problem-solving strategies should be re-prioritized
3. **Skill confidence map**: estimate proficiency level per domain

Output as JSON (no ```json markers):
{{
  "semantic_rules": [
    {{"rule": "ruledescription (refine, 120characterwithin) ", "category": "partclass(preference/command/debug/pitfall/workflow/knowledge/user_profile/general)", "abstraction_level": 2, "confidence": 0.8}}
  ],
  "strategy_updates": [
    {{"name": "strategyname", "priority_delta": 0.1, "reason": "adjustwholeoriginalbecause"}}
  ],
  "skill_confidence": {{
    "vex": 0.8,
    "node_creation": 0.9,
    "terrain": 0.5,
    "general": 0.7
  }}
}}
"""

# ============================================================
# sleepmechanism Prompt template
# ============================================================

# shallowsleep — each N roundconversationtrigger
LIGHT_SLEEP_INTERVAL = 5

LIGHT_SLEEP_PROMPT = """You are the "memory manager" module of a Houdini AI assistant. Analyze the recent conversation records and extract experience and knowledge worth keeping long-term.

## Recent conversation
{conversation_text}

## Requirements
Extract long-term-worthy content from the conversation, including:
1. **Everyday preferences**: user code style, output language, format preferences, interaction habits
2. **Build commands**: compile, test, deploy, render, etc. — commonly-used commands
3. **Debug patterns**: typical issue-debugging approaches and paths
4. **Pitfall log**: special limits and gotchas encountered in the project
5. **Workflow patterns**: node-wiring approaches, operation sequences
6. **Technical knowledge**: Houdini node usage, VEX code patterns, parameter-setting tips
7. **User profile**: user work domain, skill level

## Category and abstraction-level descriptions
category MUST be chosen from one of 8 values:
- preference: everyday preferences (code style, output language, format preferences)
- command: build commands (compile, test, deploy, etc.)
- debug: debug patterns (debug approach and path)
- pitfall: pitfall log (special limits and gotchas)
- workflow: workflow patterns (node wiring, operation sequence)
- knowledge: technical knowledge (node usage, VEX syntax)
- user_profile: user profile (work domain, skill level)
- general: other generic experience

abstraction_level MUST be in 0-5:
- 0 = core identity: user identity, core preferences, language habits (very few, highly refined, highly reusable)
- 1 = core preference: code style, format preferences, interaction habits (high-frequency reuse)
- 2 = experience rule: reusable experience, best practices, debug approaches
- 3 = workflow pattern: concrete workflows, command sequences, node wiring
- 4 = specific case: specific-task success/failure records, pitfall details
- 5 = raw detail: conversation snippets, parameter details, ephemeral records
Note: level 0 should be extremely sparse — only for the most core user identity and preferences. The bulk of memories should live in levels 2-4.

Output as JSON (no ```json markers):
{{
  "episodic_summary": "One-paragraph outline covering the core content and result of these few conversation rounds",
  "semantic_rules": [
    {{"rule": "Extracted experience rule (concise, within 120 characters)", "category": "category", "abstraction_level": 2, "confidence": 0.7}}
  ],
  "key_facts": [
    "Key facts or user preferences worth remembering"
  ]
}}
"""

# Deep sleep — triggered when context is compressed
DEEP_SLEEP_PROMPT = """You are the "deep memory manager" module of a Houdini AI assistant. The current context is about to be compressed; extract all knowledge worth permanently keeping from the full conversation.

## Full conversation context
{conversation_text}

## Requirements
This is a deep memory pass — extract as comprehensively as possible:
1. **Everyday preferences**: user code style, output language, format preferences, interaction habits
2. **Build commands**: compile, test, deploy, render, etc. — commonly-used commands
3. **Debug patterns**: typical issue-debugging approaches and paths
4. **Pitfall log**: special limits and gotchas encountered in the project
5. **Workflow patterns**: complete workflows, node-wiring approaches, commonly-used operation sequences
6. **Technical knowledge**: all Houdini node usage, VEX code patterns, parameter settings involved
7. **User profile**: user work domain, skill level
8. **Strategy updates**: which problem-solving strategies were proven effective or not

## Category and abstraction-level descriptions
category MUST be chosen from one of 8 values:
- preference: everyday preferences (code style, output language, format preferences)
- command: build commands (compile, test, deploy, etc.)
- debug: debug patterns (debug approach and path)
- pitfall: pitfall log (special limits and gotchas)
- workflow: workflow patterns (node wiring, operation sequence)
- knowledge: technical knowledge (node usage, VEX syntax)
- user_profile: user profile (work domain, skill level)
- general: other generic experience

abstraction_level MUST be in 0-5:
- 0 = core identity: user identity, core preferences, language habits (very few, highly refined, highly reusable)
- 1 = core preference: code style, format preferences, interaction habits (high-frequency reuse)
- 2 = experience rule: reusable experience, best practices, debug approaches
- 3 = workflow pattern: concrete workflows, command sequences, node wiring
- 4 = specific case: specific-task success/failure records, pitfall details
- 5 = raw detail: conversation snippets, parameter details, ephemeral records
Note: level 0 should be extremely sparse — only for the most core user identity and preferences. The bulk of memories should live in levels 2-4.

Output as JSON (no ```json markers):
{{
  "episodic_summary": "A 2-3 paragraph comprehensive outline covering the entire conversation content, process, and result",
  "semantic_rules": [
    {{"rule": "Extracted experience rule (concise, within 120 characters)", "category": "category", "abstraction_level": 2, "confidence": 0.8}}
  ],
  "procedural_strategies": [
    {{"name": "strategy_name (English snake_case)", "description": "strategy description", "conditions": ["applicable condition"]}}
  ],
  "key_facts": [
    "Key facts worth permanently remembering"
  ]
}}
"""


class ReflectionModule:
    """Hybrid reflection module: rule-based reflection + periodic LLM deep reflection."""

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        reward_engine: Optional[RewardEngine] = None,
    ):
        self.store = store or get_memory_store()
        self.reward_engine = reward_engine or get_reward_engine()
        self._task_count_since_reflect = 0
        self._recent_error_counts: List[int] = []  # recent N task errortimecount
        self._max_recent = 10

    # ==========================================================
    # Rule-based reflection (after every task; zero-cost)
    # ==========================================================

    def rule_reflect(self, episodic: EpisodicRecord, tool_calls: List[Dict]) -> EpisodicRecord:
        """rulereflection: fromtoolcallchainextractsignalandupdate episodic tags

        Args:
            episodic: episodic memory record
            tool_calls: toolcallordercolumn [{"name": ..., "success": ..., "error": ...}, ...]

        Returns:
            updateafter  episodic record
        """
        tags = list(episodic.tags)

        # 1. detectretrytimecount
        retry_count = episodic.retry_count
        if retry_count > 2:
            tags.append("retry_heavy")

        # 2. Detect success after errors (correction behavior)
        has_error = False
        has_success_after_error = False
        for tc in tool_calls:
            if tc.get("error") or not tc.get("success", True):
                has_error = True
            elif has_error and tc.get("success", True):
                has_success_after_error = True
                break

        if has_error and has_success_after_error and episodic.success:
            tags.append("error_correction")

        if has_error and not episodic.success:
            tags.append("unresolved_error")

        # 3. detectcomplextask (toolcall > 10) 
        if len(tool_calls) > 10:
            tags.append("complex_task")

        # 4. detecthigheffecttask (toolcall <= 3 andsucceeded) 
        if len(tool_calls) <= 3 and episodic.success:
            tags.append("efficient_task")

        # 5. analyzetooltype
        tool_names = [tc.get("name", "") for tc in tool_calls]
        if any("vex" in n.lower() or "wrangle" in n.lower() for n in tool_names):
            tags.append("vex_related")
        if any("create_node" in n for n in tool_names):
            tags.append("node_creation")
        if any("terrain" in n.lower() or "heightfield" in n.lower() for n in tool_names):
            tags.append("terrain_related")

        # gore
        tags = list(dict.fromkeys(tags))
        episodic.tags = tags

        # updatedatalibrary
        self.store.update_episodic_tags(episodic.id, tags)

        return episodic

    # ==========================================================
    # complete taskafterreflectionflow
    # ==========================================================

    def reflect_on_task(
        self,
        session_id: str,
        task_description: str,
        result_summary: str,
        success: bool,
        error_count: int,
        retry_count: int,
        tool_calls: List[Dict],
        ai_client: Any = None,
        model: str = "deepseek-v4-flash",
        provider: str = "deepseek",
    ) -> Dict:
        """complete taskafterreflectionflow

        Args:
            session_id: session ID
            task_description: taskdescription (userrequestsummary) 
            result_summary: resultsummary
            success: whethersucceeded
            error_count: errortimecount
            retry_count: retrytimecount
            tool_calls: toolcallordercolumn
            ai_client: AI clientendinstance (used for LLM depthreflection) 
            model: reflectionuse model
            provider: reflectionuse raiseforvendor

        Returns:
            reflectionresultdict
        """
        result = {
            "episodic_id": None,
            "reward": 0.0,
            "importance": 1.0,
            "tags": [],
            "deep_reflected": False,
            "new_rules": [],
        }

        try:
            # 1. create episodic memory
            episodic = EpisodicRecord(
                session_id=session_id,
                task_description=task_description,
                actions=[
                    {"name": tc.get("name", ""), "success": tc.get("success", True)}
                    for tc in tool_calls
                ],
                result_summary=result_summary,
                success=success,
                error_count=error_count,
                retry_count=retry_count,
            )

            # 2. rulereflection (extractsignallabel) 
            episodic = self.rule_reflect(episodic, tool_calls)
            result["tags"] = episodic.tags

            # 3. write episodic memory
            self.store.add_episodic(episodic)
            result["episodic_id"] = episodic.id

            # 4. Reward compute + importance update
            reward_result = self.reward_engine.process_task_completion(
                episodic_record=episodic,
                tool_call_count=len(tool_calls),
            )
            result["reward"] = reward_result["reward"]
            result["importance"] = reward_result["importance"]

            # 5. updatestatistics
            self._task_count_since_reflect += 1
            self._recent_error_counts.append(error_count)
            if len(self._recent_error_counts) > self._max_recent:
                self._recent_error_counts = self._recent_error_counts[-self._max_recent:]

            # 6. decidebreakwhethertrigger LLM depthreflection
            should_deep_reflect = self._should_deep_reflect()
            if should_deep_reflect and ai_client is not None:
                try:
                    deep_result = self._deep_reflect(ai_client, model, provider)
                    result["deep_reflected"] = True
                    result["new_rules"] = deep_result.get("new_rules", [])
                except Exception as e:
                    _dbg(f"[Reflection] LLM deep reflection failed: {e}")
                    traceback.print_exc()

        except Exception as e:
            _dbg(f"[Reflection] Reflection flow error: {e}")
            traceback.print_exc()

        return result

    # ==========================================================
    # LLM depthreflection
    # ==========================================================

    def _should_deep_reflect(self) -> bool:
        """decidebreakwhethershouldthistrigger LLM depthreflection"""
        # 1. each N task
        if self._task_count_since_reflect >= DEEP_REFLECT_INTERVAL:
            return True

        # 2. Error-rate spike
        if len(self._recent_error_counts) >= 3:
            recent = self._recent_error_counts[-3:]
            error_rate = sum(1 for e in recent if e > 0) / len(recent)
            if error_rate >= ERROR_RATE_SPIKE_THRESHOLD:
                return True

        return False

    def _deep_reflect(self, ai_client: Any, model: str, provider: str) -> Dict:
        """execute LLM depthreflection

        input: recent N item episodic memory
        output: new semantic rules + procedural strategy update

        Args:
            ai_client: AIClient instance
            model: modelname
            provider: raiseforvendor

        Returns:
            {"new_rules": [...], "strategy_updates": [...]}
        """
        # replacecountcount 
        self._task_count_since_reflect = 0

        # getrecent  episodic memory
        recent_episodes = self.store.get_recent_episodic(limit=DEEP_REFLECT_INTERVAL * 2)
        if not recent_episodes:
            return {"new_rules": []}

        # buildsummary
        summaries = []
        for i, ep in enumerate(recent_episodes[:10], 1):
            status = "✅ succeeded" if ep.success else "❌ failed"
            tags_str = ", ".join(ep.tags) if ep.tags else "no"
            summaries.append(
                f"{i}. [{status}] task: {ep.task_description}\n"
                f"   result: {ep.result_summary}\n"
                f"   errortimecount: {ep.error_count}, retry: {ep.retry_count}, Reward: {ep.reward_score:.2f}\n"
                f"   label: {tags_str}"
            )

        episodic_text = "\n\n".join(summaries)
        prompt = REFLECTION_PROMPT.format(episodic_summaries=episodic_text)

        # call LLM
        messages = [
            {"role": "system", "content": "youisoneselfIimproved  AI assistant. pleaseuse JSON formatanswer. "},
            {"role": "user", "content": prompt},
        ]

        full_response = ""
        try:
            for chunk in ai_client.chat_stream(
                messages=messages,
                model=model,
                provider=provider,
                temperature=0.3,
                max_tokens=1500,
                tools=None,
                enable_thinking=False,
                response_format={'type': 'json_object'},
            ):
                if chunk.get("type") == "content":
                    full_response += chunk.get("content", "")
                elif chunk.get("type") == "error":
                    _dbg(f"[Reflection] LLM reflection error: {chunk.get('error')}")
                    return {"new_rules": []}
        except Exception as e:
            _dbg(f"[Reflection] LLM call failed: {e}")
            return {"new_rules": []}

        # parse JSON respondshould
        return self._parse_reflection_response(full_response, recent_episodes)

    def _parse_reflection_response(self, response: str, source_episodes: List[EpisodicRecord]) -> Dict:
        """parse LLM reflectionrespondshouldandwritememory"""
        result = {"new_rules": [], "strategy_updates": []}

        # cleanup JSON
        text = response.strip()
        # removemay  markdown codeblock
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # tryextract JSON partpart
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    _dbg(f"[Reflection] Cannot parse reflection response")
                    return result
            else:
                _dbg(f"[Reflection] No JSON found in reflection response")
                return result

        source_ids = [ep.id for ep in source_episodes]

        # 1. process semantic rules (containing abstraction_level) 
        for rule_data in data.get("semantic_rules", []):
            rule_text = rule_data if isinstance(rule_data, str) else rule_data.get("rule", "")
            if not rule_text:
                continue

            category = rule_data.get("category", "general") if isinstance(rule_data, dict) else "general"
            confidence = rule_data.get("confidence", 0.6) if isinstance(rule_data, dict) else 0.6
            abs_level = rule_data.get("abstraction_level", 2) if isinstance(rule_data, dict) else 2
            # limitrefinelength
            rule_text = rule_text[:120]

            # checkwhetheralreadyhasheightsimilar rule
            existing = self.store.find_duplicate_semantic(rule_text, threshold=0.80)
            if existing:
                # addstrongalreadyhasrule placeinfodegree
                new_conf = min(1.0, existing.confidence + 0.1)
                self.store.update_semantic_confidence(existing.id, new_conf)
                self.store.increment_semantic_activation(existing.id)
                _dbg(f"[Reflection] Reinforced existing rule: {existing.rule[:50]}... (conf={new_conf:.2f})")
            else:
                # createnewrule
                record = SemanticRecord(
                    rule=rule_text,
                    source_episodes=source_ids[:5],
                    confidence=confidence,
                    category=category,
                    abstraction_level=max(0, min(5, abs_level)),
                )
                self.store.add_semantic(record)
                result["new_rules"].append(rule_text)
                _dbg(f"[Reflection] New rule: {rule_text[:50]}...")

        # 2. processstrategyupdate
        for update in data.get("strategy_updates", []):
            name = update.get("name", "")
            priority_delta = update.get("priority_delta", 0.0)
            if name and priority_delta != 0:
                existing = self.store.get_procedural_by_name(name)
                if existing:
                    self.store.update_procedural_priority(existing.id, priority_delta)
                    result["strategy_updates"].append(update)
                    _dbg(f"[Reflection] Strategy update: {name} priority += {priority_delta}")

        # 3. processskillcanplaceinfodegree (saveenter growth tracker, viaexternalcall) 
        skill_conf = data.get("skill_confidence", {})
        if skill_conf:
            result["skill_confidence"] = skill_conf

        return result

    # ==========================================================
    # ★ sleepmechanism: conversationlevelmemorywholemanage
    # ==========================================================

    def light_sleep(
        self,
        session_id: str,
        recent_messages: List[Dict],
        ai_client: Any,
        model: str,
        provider: str,
    ) -> Dict:
        """shallowsleep: summaryrecent N roundconversationwritelong-termmemory

        Triggered every LIGHT_SLEEP_INTERVAL user questions.
        usecurrent LLM willrecentconversationsummaryas episodic + semantic memory. 

        Args:
            session_id: session ID
            recent_messages: recent N round messagelist (user/assistant/tool)
            ai_client: AI clientendinstance
            model: currentuse model
            provider: currentuse raiseforvendor

        Returns:
            {"success": bool, "episodic_id": str, "new_rules": [...]}
        """
        result = {"success": False, "episodic_id": None, "new_rules": []}

        if not recent_messages:
            return result

        try:
            # buildconversationtext
            conv_text = self._messages_to_text(recent_messages, max_chars=4000)
            prompt = LIGHT_SLEEP_PROMPT.format(conversation_text=conv_text)

            # call LLM
            response = self._call_llm(ai_client, prompt, model, provider, max_tokens=1500)
            if not response:
                return result

            # parseandwritememory
            data = self._parse_json_response(response)
            if not data:
                return result

            # 1. write episodic memory (conversationlevelsummary) 
            summary = data.get("episodic_summary", "")
            if summary:
                episodic = EpisodicRecord(
                    session_id=session_id,
                    task_description=f"[Sleep] conversationsummary ({len(recent_messages)} msgs)",
                    result_summary=summary[:300],
                    success=True,
                    tags=["sleep_light", "conversation_summary"],
                    importance=1.5,  # wholemanageafter memoryreneeddegreemorehigh
                )
                self.store.add_episodic(episodic)
                result["episodic_id"] = episodic.id

            # 2. write semantic rule (containing abstraction_level) 
            for rule_data in data.get("semantic_rules", []):
                rule_text = rule_data.get("rule", "") if isinstance(rule_data, dict) else str(rule_data)
                if not rule_text:
                    continue
                category = rule_data.get("category", "general") if isinstance(rule_data, dict) else "general"
                confidence = rule_data.get("confidence", 0.7) if isinstance(rule_data, dict) else 0.7
                abs_level = rule_data.get("abstraction_level", 2) if isinstance(rule_data, dict) else 2
                # limitrefinelength
                rule_text = rule_text[:120]

                existing = self.store.find_duplicate_semantic(rule_text, threshold=0.80)
                if existing:
                    new_conf = min(1.0, existing.confidence + 0.1)
                    self.store.update_semantic_confidence(existing.id, new_conf)
                    self.store.increment_semantic_activation(existing.id)
                else:
                    record = SemanticRecord(
                        rule=rule_text,
                        confidence=confidence,
                        category=category,
                        abstraction_level=max(0, min(5, abs_level)),
                    )
                    self.store.add_semantic(record)
                    result["new_rules"].append(rule_text)

            # 3. key_facts → appendas level=1 corepreference semantic rule
            for fact in data.get("key_facts", []):
                if fact and len(fact) > 5:
                    existing = self.store.find_duplicate_semantic(fact, threshold=0.80)
                    if not existing:
                        record = SemanticRecord(
                            rule=fact[:120],
                            confidence=0.8,
                            category="preference",
                            abstraction_level=1,
                        )
                        self.store.add_semantic(record)
                        result["new_rules"].append(fact[:120])

            result["success"] = True
            n_rules = len(result["new_rules"])
            _dbg(f"[Sleep] 💤 Light-sleep complete: episodic={bool(summary)}, {n_rules} new rules")

        except Exception as e:
            _dbg(f"[Sleep] Light-sleep failed: {e}")
            traceback.print_exc()

        return result

    def deep_sleep(
        self,
        session_id: str,
        all_messages: List[Dict],
        ai_client: Any,
        model: str,
        provider: str,
    ) -> Dict:
        """depthsleep: contextcompressprevious, summaryallpartcontextwritelong-termmemory

        whencontextwindowtriggerautocompresswhenforcetrigger. 
        usecurrent LLM willwholeconversationcontextdepthsummaryaslong-termmemory. 

        Args:
            session_id: session ID
            all_messages: complete conversationmessagelist
            ai_client: AI clientendinstance
            model: currentuse model
            provider: currentuse raiseforvendor

        Returns:
            {"success": bool, "episodic_id": str, "new_rules": [...], "new_strategies": [...]}
        """
        result = {"success": False, "episodic_id": None, "new_rules": [], "new_strategies": []}

        if not all_messages:
            return result

        try:
            # buildconversationtext (depthsleepallowmorelong input) 
            conv_text = self._messages_to_text(all_messages, max_chars=8000)
            prompt = DEEP_SLEEP_PROMPT.format(conversation_text=conv_text)

            # call LLM (depthsleepallowmorelong output) 
            response = self._call_llm(ai_client, prompt, model, provider, max_tokens=3000)
            if not response:
                return result

            # parseandwritememory
            data = self._parse_json_response(response)
            if not data:
                return result

            # 1. write episodic memory (depthsummary) 
            summary = data.get("episodic_summary", "")
            if summary:
                episodic = EpisodicRecord(
                    session_id=session_id,
                    task_description=f"[DeepSleep] contextdepthwholemanage ({len(all_messages)} msgs)",
                    result_summary=summary[:500],
                    success=True,
                    tags=["sleep_deep", "context_consolidation"],
                    importance=2.0,  # depthwholemanage memoryreneeddegreemosthigh
                )
                self.store.add_episodic(episodic)
                result["episodic_id"] = episodic.id

            # 2. write semantic rule (containing abstraction_level) 
            for rule_data in data.get("semantic_rules", []):
                rule_text = rule_data.get("rule", "") if isinstance(rule_data, dict) else str(rule_data)
                if not rule_text:
                    continue
                category = rule_data.get("category", "general") if isinstance(rule_data, dict) else "general"
                confidence = rule_data.get("confidence", 0.8) if isinstance(rule_data, dict) else 0.8
                abs_level = rule_data.get("abstraction_level", 2) if isinstance(rule_data, dict) else 2
                # limitrefinelength
                rule_text = rule_text[:120]

                existing = self.store.find_duplicate_semantic(rule_text, threshold=0.80)
                if existing:
                    new_conf = min(1.0, existing.confidence + 0.15)
                    self.store.update_semantic_confidence(existing.id, new_conf)
                    self.store.increment_semantic_activation(existing.id)
                else:
                    record = SemanticRecord(
                        rule=rule_text,
                        confidence=confidence,
                        category=category,
                        abstraction_level=max(0, min(5, abs_level)),
                    )
                    self.store.add_semantic(record)
                    result["new_rules"].append(rule_text)

            # 3. write procedural strategy
            for strat_data in data.get("procedural_strategies", []):
                name = strat_data.get("name", "")
                desc = strat_data.get("description", "")
                if not name or not desc:
                    continue

                existing = self.store.get_procedural_by_name(name)
                if existing:
                    # strategyalreadysavein → updateusestatistics
                    self.store.update_procedural_usage(existing.id, success=True)
                else:
                    record = ProceduralRecord(
                        strategy_name=name,
                        description=desc,
                        priority=0.6,
                        conditions=strat_data.get("conditions", []),
                    )
                    self.store.add_procedural(record)
                    result["new_strategies"].append(name)

            # 4. key_facts → level=1 corepreference
            for fact in data.get("key_facts", []):
                if fact and len(fact) > 5:
                    existing = self.store.find_duplicate_semantic(fact, threshold=0.80)
                    if not existing:
                        record = SemanticRecord(
                            rule=fact[:120],
                            confidence=0.85,
                            category="preference",
                            abstraction_level=1,
                        )
                        self.store.add_semantic(record)
                        result["new_rules"].append(fact[:120])

            result["success"] = True
            n_rules = len(result["new_rules"])
            n_strats = len(result["new_strategies"])
            _dbg(f"[Sleep] 😴 Deep-sleep complete: episodic={bool(summary)}, "
                  f"{n_rules} new rules, {n_strats} new strategies")

        except Exception as e:
            _dbg(f"[Sleep] Deep-sleep failed: {e}")
            traceback.print_exc()

        return result

    # ==========================================================
    # sleephelpermethod
    # ==========================================================

    @staticmethod
    def _messages_to_text(messages: List[Dict], max_chars: int = 4000) -> str:
        """willmessagelistconvertswapascanreadtext (for LLM analyze) """
        parts = []
        total = 0
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')

            # skipnocontent message
            if not content:
                # assistant with tool_calls → marker note
                if role == 'assistant' and msg.get('tool_calls'):
                    tc_names = [tc.get('function', {}).get('name', '?')
                                for tc in msg.get('tool_calls', [])]
                    line = f"[Assistant] calltool: {', '.join(tc_names)}"
                else:
                    continue
            elif role == 'system':
                continue  # skip system message (notneedsmemorysystemhintword) 
            elif role == 'user':
                # multimodalcontent
                if isinstance(content, list):
                    text_parts = [p.get('text', '') for p in content
                                  if isinstance(p, dict) and p.get('type') == 'text']
                    content = ' '.join(t for t in text_parts if t)
                    if not content:
                        content = "[imagemessage]"
                line = f"[User] {content}"
            elif role == 'assistant':
                # godrop think label
                import re
                content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                if not content:
                    continue
                line = f"[Assistant] {content}"
            elif role == 'tool':
                tool_name = msg.get('name', 'unknown')
                # compresstoolresult
                if len(content) > 200:
                    content = content[:200] + "..."
                line = f"[Tool:{tool_name}] {content}"
            else:
                continue

            if total + len(line) > max_chars:
                parts.append("... (earlier content truncated)")
                break
            parts.append(line)
            total += len(line) + 1

        return "\n".join(parts)

    def _call_llm(self, ai_client: Any, prompt: str, model: str,
                  provider: str, max_tokens: int = 1500) -> str:
        """call LLM andreturncompleterespondshouldtext"""
        messages = [
            {"role": "system", "content": "youisone AI assistant memorywholemanagemodule. pleaseuse JSON formatanswer. "},
            {"role": "user", "content": prompt},
        ]

        full_response = ""
        try:
            for chunk in ai_client.chat_stream(
                messages=messages,
                model=model,
                provider=provider,
                temperature=0.3,
                max_tokens=max_tokens,
                tools=None,
                enable_thinking=False,
                response_format={'type': 'json_object'},
            ):
                if chunk.get("type") == "content":
                    full_response += chunk.get("content", "")
                elif chunk.get("type") == "error":
                    _dbg(f"[Sleep] LLM error: {chunk.get('error')}")
                    return ""
        except Exception as e:
            _dbg(f"[Sleep] LLM call failed: {e}")
            return ""

        return full_response

    @staticmethod
    def _parse_json_response(response: str) -> Optional[Dict]:
        """parse LLM   JSON respondshould"""
        import re
        text = response.strip()
        # remove markdown codeblock
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            _dbg(f"[Sleep] Cannot parse JSON response")
            return None

    # ==========================================================
    # toolmethod
    # ==========================================================

    def get_reflection_stats(self) -> Dict:
        """getreflectionstatisticsinfo"""
        return {
            "tasks_since_reflect": self._task_count_since_reflect,
            "recent_errors": self._recent_error_counts[-5:] if self._recent_error_counts else [],
            "next_deep_reflect_in": max(0, DEEP_REFLECT_INTERVAL - self._task_count_since_reflect),
        }


# ============================================================
# globalsingleexample
# ============================================================

_reflection_instance: Optional[ReflectionModule] = None

def get_reflection_module() -> ReflectionModule:
    """getglobal ReflectionModule instance"""
    global _reflection_instance
    if _reflection_instance is None:
        _reflection_instance = ReflectionModule()
    return _reflection_instance
