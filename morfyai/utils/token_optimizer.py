# -*- coding: utf-8 -*-
"""
Token optimization manager
Multiple systematic strategies for reducing token consumption.

Aligned with Cursor's token accounting:
- tiktoken-precise counting when available, otherwise an improved estimate
- Per-model pricing (USD / 1M tokens)
- Cost computation via calculate_cost()
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

# ============================================================
# tiktoken precise counting (optional dependency)
# ============================================================
_tiktoken = None
_encoding_cache: Dict[str, Any] = {}

def _get_encoding(model: str):
    """Get the tiktoken encoder (with caching)"""
    global _tiktoken, _encoding_cache
    if _tiktoken is None:
        try:
            import tiktoken as _tk  # type: ignore
            _tiktoken = _tk
        except ImportError:
            _tiktoken = False
    if _tiktoken is False:
        return None
    # Model name -> encoding mapping
    try:
        key = model or 'gpt-5.2'
        if key not in _encoding_cache:
            try:
                _encoding_cache[key] = _tiktoken.encoding_for_model(key)
            except KeyError:
                # Unknown model falls back to cl100k_base (common for GPT-4 / Claude)
                if 'cl100k' not in _encoding_cache:
                    _encoding_cache['cl100k'] = _tiktoken.get_encoding('cl100k_base')
                _encoding_cache[key] = _encoding_cache['cl100k']
        return _encoding_cache[key]
    except Exception:
        return None


def count_tokens(text: str, model: str = '') -> int:
    """Compute an accurate token count

    Prefers tiktoken (if available), otherwise uses an improved estimate.
    """
    if not text:
        return 0
    enc = _get_encoding(model)
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # ---- Improved heuristic estimate ----
    # JSON / code blocks contain many single-token symbols like { } " , :
    # CJK character ranges (Han, full-width punct, half-width punct) — kept in
    # \u escape form so this source file stays Chinese-character-free.
    chinese_chars = len(re.findall(
        '[\\u4e00-\\u9fff\\u3000-\\u303f\\uff00-\\uffef]', text))
    # Code / JSON characteristic characters (each is one token)
    code_chars = len(re.findall(r'[{}\[\]:,;()=<>+\-*/|&^~!@#$%]', text))
    other_chars = len(text) - chinese_chars - code_chars
    tokens = chinese_chars / 1.5 + code_chars + other_chars / 3.8
    return max(1, int(tokens))


# ============================================================
# Per-model pricing (USD / 1M tokens) — aligned with Cursor
# ============================================================

# Format: {model_pattern: {input, input_cache, output, reasoning(optional)}}
# input_cache: input price on cache hit
# reasoning: output price for reasoning tokens (falls back to output if absent)
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # ---- DeepSeek ----
    'deepseek-v4-flash':    {'input': 0.27,  'input_cache': 0.07,  'output': 1.10},
    'deepseek-v4-pro':      {'input': 0.55,  'input_cache': 0.14,  'output': 2.19, 'reasoning': 2.19},
    'deepseek-chat':        {'input': 0.27,  'input_cache': 0.07,  'output': 1.10},
    'deepseek-reasoner':    {'input': 0.55,  'input_cache': 0.14,  'output': 2.19, 'reasoning': 2.19},
    # ---- OpenAI ----
    'gpt-5.2':              {'input': 2.50,  'input_cache': 1.25,  'output': 10.00},
    'gpt-5.3-codex':        {'input': 3.00,  'input_cache': 1.50,  'output': 12.00},
    'o3':                   {'input': 10.00, 'input_cache': 2.50,  'output': 40.00, 'reasoning': 40.00},
    'o3-mini':              {'input': 1.10,  'input_cache': 0.55,  'output': 4.40,  'reasoning': 4.40},
    'o4-mini':              {'input': 1.10,  'input_cache': 0.275, 'output': 4.40,  'reasoning': 4.40},
    # ---- Claude (via Duojie) ----
    'claude-opus-4-5':      {'input': 15.00, 'input_cache': 1.50,  'output': 75.00, 'reasoning': 75.00},
    'claude-opus-4-5-kiro': {'input': 15.00, 'input_cache': 1.50,  'output': 75.00, 'reasoning': 75.00},
    'claude-opus-4-5-max':  {'input': 15.00, 'input_cache': 1.50,  'output': 75.00, 'reasoning': 75.00},
    'claude-opus-4-6-normal': {'input': 15.00, 'input_cache': 1.50, 'output': 75.00, 'reasoning': 75.00},
    'claude-opus-4-6-kiro': {'input': 15.00, 'input_cache': 1.50,  'output': 75.00, 'reasoning': 75.00},
    'claude-opus-4-6-gemini': {'input': 15.00, 'input_cache': 1.50, 'output': 75.00, 'reasoning': 75.00},
    'claude-opus-4-6-max': {'input': 15.00, 'input_cache': 1.50, 'output': 75.00, 'reasoning': 75.00},
    'claude-sonnet-4-5':    {'input': 3.00,  'input_cache': 0.30,  'output': 15.00, 'reasoning': 15.00},
    'claude-sonnet-4-6':    {'input': 3.00,  'input_cache': 0.30,  'output': 15.00, 'reasoning': 15.00},
    'claude-haiku-4-5':     {'input': 0.80,  'input_cache': 0.08,  'output': 4.00},
    # ---- Gemini ----
    'gemini-3-pro-image-preview': {'input': 1.25, 'input_cache': 0.30, 'output': 10.00},
    'gemini-3-flash':       {'input': 0.50,  'input_cache': 0.125, 'output': 3.00},
    'gemini-3.1-pro':       {'input': 1.25,  'input_cache': 0.30,  'output': 10.00},
    # ---- GLM (Zhipu) ----
    'glm-4.7':              {'input': 0.50,  'input_cache': 0.50,  'output': 0.50},
    'glm-5-turbo':          {'input': 0.50,  'input_cache': 0.50,  'output': 0.50},
    'glm-5.1':              {'input': 0.50,  'input_cache': 0.50,  'output': 0.50},
    # ---- Kimi ----
    'kimi-k2.5':            {'input': 2.00,  'input_cache': 0.50,  'output': 8.00},
    # ---- MiniMax ----
    'MiniMax-M2.5':         {'input': 1.00,  'input_cache': 0.25,  'output': 4.00},
    'MiniMax-M2.7':         {'input': 1.00,  'input_cache': 0.25,  'output': 4.00},
    'MiniMax-M2.7-highspeed': {'input': 1.00, 'input_cache': 0.25, 'output': 4.00},
    # ---- Qwen ----
    'qwen3.5-plus':         {'input': 0.80,  'input_cache': 0.20,  'output': 2.00},
    'qwen-plus':            {'input': 0.80,  'input_cache': 0.20,  'output': 2.00},
    'qwen-max':             {'input': 2.00,  'input_cache': 0.50,  'output': 6.00},
    'qwen-turbo':           {'input': 0.30,  'input_cache': 0.05,  'output': 0.60},
    # ---- Ollama local (free) ----
    # See _match_pricing for wildcard matching
}

# Default pricing (used when no match is found; priced like DeepSeek-chat)
_DEFAULT_PRICING = {'input': 0.27, 'input_cache': 0.07, 'output': 1.10}


def _match_pricing(model: str) -> Dict[str, float]:
    """Model name -> pricing dict (with fuzzy matching)"""
    if not model:
        return _DEFAULT_PRICING
    m = model.lower().strip()
    # Exact match
    if m in MODEL_PRICING:
        return MODEL_PRICING[m]
    # Prefix match (e.g. claude-sonnet-4-5-xxx -> claude-sonnet-4-5)
    for key in sorted(MODEL_PRICING.keys(), key=len, reverse=True):
        if m.startswith(key):
            return MODEL_PRICING[key]
    # Ollama local model: free
    # Provider info would be more reliable but is not available here
    # Fallback: model names containing ':' are usually ollama format (e.g. qwen2.5:14b)
    if ':' in m:
        return {'input': 0.0, 'input_cache': 0.0, 'output': 0.0}
    return _DEFAULT_PRICING


def calculate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_hit: int = 0,
    cache_miss: int = 0,
    reasoning_tokens: int = 0,
) -> float:
    """Compute the cost of a single API call (USD)

    Args:
        model: model name
        input_tokens: total input tokens (prompt_tokens)
        output_tokens: total output tokens (completion_tokens, including reasoning)
        cache_hit: cache-hit tokens
        cache_miss: cache-miss tokens
        reasoning_tokens: reasoning tokens (a subset of output_tokens)

    Returns:
        Estimated cost (USD)
    """
    p = _match_pricing(model)
    M = 1_000_000.0

    # Input cost
    # cache_hit uses cache price; cache_miss uses normal input price
    # If cache_hit + cache_miss > 0, prefer the split; otherwise count all input_tokens
    if cache_hit > 0 or cache_miss > 0:
        in_cost = (cache_hit * p.get('input_cache', p['input']) + cache_miss * p['input']) / M
    else:
        in_cost = input_tokens * p['input'] / M

    # Output cost
    reasoning_price = p.get('reasoning', p['output'])
    normal_out = max(0, output_tokens - reasoning_tokens)
    out_cost = (normal_out * p['output'] + reasoning_tokens * reasoning_price) / M

    return in_cost + out_cost


def calculate_cost_from_stats(model: str, stats: dict) -> float:
    """Compute cost from an aggregated stats dict"""
    return calculate_cost(
        model=model,
        input_tokens=stats.get('input_tokens', 0),
        output_tokens=stats.get('output_tokens', 0),
        cache_hit=stats.get('cache_read', stats.get('cache_hit', stats.get('cache_hit_tokens', 0))),
        cache_miss=stats.get('cache_write', stats.get('cache_miss', stats.get('cache_miss_tokens', 0))),
        reasoning_tokens=stats.get('reasoning_tokens', 0),
    )


# ============================================================
# Compression strategy & Token budget
# ============================================================

class CompressionStrategy(Enum):
    """Compression strategy"""
    NONE = "none"  # no compression
    AGGRESSIVE = "aggressive"  # aggressive compression (max savings)
    BALANCED = "balanced"  # balanced compression (default)
    CONSERVATIVE = "conservative"  # conservative compression (keep more detail)


@dataclass
class TokenBudget:
    """Token budget configuration"""
    max_tokens: int = 128000  # maximum tokens
    warning_threshold: float = 0.7  # warning threshold (70%)
    compression_threshold: float = 0.8  # compression threshold (80%)
    emergency_threshold: float = 0.9  # emergency-compression threshold (90%)
    keep_recent_messages: int = 4  # keep the most recent N messages
    strategy: CompressionStrategy = CompressionStrategy.BALANCED


class TokenOptimizer:
    """Token optimizer - systematic token-consumption reduction"""

    def __init__(self, budget: Optional[TokenBudget] = None, model: str = ''):
        self.budget = budget or TokenBudget()
        self.model = model  # used by tiktoken
        self._compression_history: List[Dict[str, Any]] = []  # compression history

    def estimate_tokens(self, text: str) -> int:
        """Estimate the token count of text (prefers tiktoken)"""
        return count_tokens(text, self.model)

    def calculate_message_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Compute total token count for a list of messages (incl. tool_calls and multimodal content)"""
        total = 0
        for msg in messages:
            content = msg.get('content', '') or ''
            if isinstance(content, list):
                # Multimodal message: extract text for token counting, images use a fixed estimate
                for part in content:
                    if isinstance(part, dict):
                        if part.get('type') == 'text':
                            total += self.estimate_tokens(part.get('text', ''))
                        elif part.get('type') == 'image_url':
                            total += 765  # images are fixed at ~765 tokens (low-resolution mode)
                    elif isinstance(part, str):
                        total += self.estimate_tokens(part)
            else:
                total += self.estimate_tokens(content)
            # tool_calls function name and arguments also consume tokens
            tool_calls = msg.get('tool_calls')
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get('function', {})
                    total += self.estimate_tokens(fn.get('name', ''))
                    total += self.estimate_tokens(fn.get('arguments', ''))
                    total += 8  # tool_call struct overhead (id, type, function wrapper)
            # Message format overhead (role, format characters, etc.)
            total += 4
        return total

    def compress_tool_result(self, result: Dict[str, Any], max_length: int = 200) -> str:
        """Compress a tool-call result

        Args:
            result: tool execution result
            max_length: max character length

        Returns:
            Compressed result summary
        """
        if not result:
            return ""

        success = result.get('success', False)
        if not success:
            error = result.get('error', 'Unknown error')
            return f"Error: {error[:max_length]}"

        result_text = result.get('result', '')
        if not result_text:
            return "Success"

        # If the result is short, return as-is
        if len(result_text) <= max_length:
            return f"{result_text}"

        # Extract key information
        lines = [l.strip() for l in result_text.split('\n') if l.strip()]

        # Strategy 1: take the first and last lines
        if len(lines) >= 2:
            summary = f"{lines[0][:max_length//2]} ... {lines[-1][:max_length//2]}"
        elif len(lines) == 1:
            summary = f"{lines[0][:max_length]}"
        else:
            summary = f"{result_text[:max_length]}..."

        return summary

    def compress_messages(
        self,
        messages: List[Dict[str, Any]],
        keep_recent: Optional[int] = None,
        strategy: Optional[CompressionStrategy] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Compress a message list

        Args:
            messages: original messages
            keep_recent: keep the most recent N messages (defaults to budget config)
            strategy: compression strategy (defaults to budget config)

        Returns:
            (compressed messages, compression stats)
        """
        if not messages:
            return [], {'compressed': 0, 'saved_tokens': 0}

        keep_recent = keep_recent or self.budget.keep_recent_messages
        strategy = strategy or self.budget.strategy

        if len(messages) <= keep_recent:
            return messages, {'compressed': 0, 'saved_tokens': 0}

        # Convert role="tool" messages to assistant format (avoids API 400 errors)
        converted_messages = []
        for m in messages:
            if m.get('role') == 'tool':
                tool_name = m.get('name', 'unknown')
                content = m.get('content', '')
                converted_messages.append({
                    'role': 'assistant',
                    'content': f"[Tool result] {tool_name}: {content}"
                })
            else:
                converted_messages.append(m)

        # Split old vs. recent messages
        old_messages = converted_messages[:-keep_recent] if len(converted_messages) > keep_recent else []
        recent_messages = converted_messages[-keep_recent:] if len(converted_messages) >= keep_recent else converted_messages

        # Original token count
        original_tokens = self.calculate_message_tokens(messages)

        # Compress per strategy
        compressed_messages = []
        if old_messages:
            if strategy == CompressionStrategy.AGGRESSIVE:
                summary = self._generate_aggressive_summary(old_messages)
            elif strategy == CompressionStrategy.CONSERVATIVE:
                summary = self._generate_conservative_summary(old_messages)
            else:  # BALANCED
                summary = self._generate_balanced_summary(old_messages)

            if summary:
                compressed_messages.append({
                    'role': 'system',
                    'content': summary
                })

        # Keep recent messages
        compressed_messages.extend(recent_messages)

        # Compute saved tokens
        compressed_tokens = self.calculate_message_tokens(compressed_messages)
        saved_tokens = original_tokens - compressed_tokens

        stats = {
            'compressed': len(old_messages),
            'kept': len(recent_messages),
            'original_tokens': original_tokens,
            'compressed_tokens': compressed_tokens,
            'saved_tokens': saved_tokens,
            'saved_percent': (saved_tokens / original_tokens * 100) if original_tokens > 0 else 0
        }

        return compressed_messages, stats

    def _generate_balanced_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Generate a balanced summary (default strategy)"""
        parts = ["[Conversation history summary - compressed to save tokens]"]

        user_requests = []
        ai_responses = []
        tool_calls = []

        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')

            if role == 'user':
                req = content[:150].replace('\n', ' ').strip()
                if len(content) > 150:
                    req += "..."
                if req:
                    user_requests.append(req)

            elif role == 'assistant':
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                if lines:
                    res = lines[-1][:100].replace('\n', ' ').strip()
                    if len(lines[-1]) > 100:
                        res += "..."
                    if res:
                        ai_responses.append(res)

            elif role == 'tool':
                tool_call_id = msg.get('tool_call_id', '')
                if tool_call_id:
                    tool_calls.append(f"Tool call: {tool_call_id[:50]}")

        if user_requests:
            parts.append(f"\nUser requests ({len(user_requests)}):")
            for i, req in enumerate(user_requests[:8], 1):
                parts.append(f"  {i}. {req}")
            if len(user_requests) > 8:
                parts.append(f"  ... {len(user_requests) - 8} more request(s)")

        if ai_responses:
            parts.append(f"\nAI completions ({len(ai_responses)}):")
            for i, res in enumerate(ai_responses[:8], 1):
                parts.append(f"  {i}. {res}")
            if len(ai_responses) > 8:
                parts.append(f"  ... {len(ai_responses) - 8} more result(s)")

        if tool_calls:
            parts.append(f"\nTool calls: {len(tool_calls)} time(s)")

        return "\n".join(parts)

    def _generate_aggressive_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Generate an aggressive summary (max savings)"""
        parts = ["[Conversation history summary - aggressive compression]"]

        user_count = sum(1 for m in messages if m.get('role') == 'user')
        assistant_count = sum(1 for m in messages if m.get('role') == 'assistant')
        tool_count = sum(1 for m in messages if m.get('role') == 'tool')

        parts.append(f"User requests: {user_count}")
        parts.append(f"AI replies: {assistant_count}")
        if tool_count > 0:
            parts.append(f"Tool calls: {tool_count} time(s)")

        if messages:
            last_user = next((m for m in reversed(messages) if m.get('role') == 'user'), None)
            if last_user:
                content = last_user.get('content', '')[:100]
                parts.append(f"\nLast request: {content.replace(chr(10), ' ')}")

        return "\n".join(parts)

    def _generate_conservative_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Generate a conservative summary (keep more detail)"""
        parts = ["[Conversation history summary - conservative compression]"]

        user_requests = []
        ai_responses = []

        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')

            if role == 'user':
                req = content[:250].replace('\n', ' ').strip()
                if len(content) > 250:
                    req += "..."
                if req:
                    user_requests.append(req)

            elif role == 'assistant':
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                if lines:
                    res = " | ".join(lines[:3])[:200]
                    if len(lines) > 3:
                        res += "..."
                    if res:
                        ai_responses.append(res)

        if user_requests:
            parts.append(f"\nUser requests ({len(user_requests)}):")
            for i, req in enumerate(user_requests[:12], 1):
                parts.append(f"  {i}. {req}")
            if len(user_requests) > 12:
                parts.append(f"  ... {len(user_requests) - 12} more")

        if ai_responses:
            parts.append(f"\nAI completions ({len(ai_responses)}):")
            for i, res in enumerate(ai_responses[:12], 1):
                parts.append(f"  {i}. {res}")
            if len(ai_responses) > 12:
                parts.append(f"  ... {len(ai_responses) - 12} more")

        return "\n".join(parts)

    def optimize_tool_results(
        self,
        tool_calls_history: List[Dict[str, Any]],
        max_result_length: int = 150
    ) -> List[Dict[str, Any]]:
        """Optimize tool-call history by compressing results"""
        optimized = []

        for call in tool_calls_history:
            result = call.get('result', {})

            if isinstance(result, dict):
                compressed_result = self.compress_tool_result(result, max_result_length)
                optimized_call = call.copy()
                optimized_call['result'] = {
                    'success': result.get('success', False),
                    'summary': compressed_result,
                    'original_length': len(str(result.get('result', '')))
                }
                optimized.append(optimized_call)
            else:
                optimized.append(call)

        return optimized

    def should_compress(self, current_tokens: int, limit: Optional[int] = None) -> Tuple[bool, str]:
        """Decide whether compression should run"""
        limit = limit or self.budget.max_tokens

        if current_tokens >= limit * self.budget.emergency_threshold:
            return True, f"Emergency compression: tokens {current_tokens}/{limit} ({current_tokens/limit*100:.1f}%)"

        if current_tokens >= limit * self.budget.compression_threshold:
            return True, f"Compression recommended: tokens {current_tokens}/{limit} ({current_tokens/limit*100:.1f}%)"

        if current_tokens >= limit * self.budget.warning_threshold:
            return False, f"Warning: tokens {current_tokens}/{limit} ({current_tokens/limit*100:.1f}%)"

        return False, ""

    def optimize_system_prompt(self, prompt: str, max_length: int = 2000) -> str:
        """Optimize the system prompt, removing redundancy"""
        if len(prompt) <= max_length:
            return prompt

        lines = [l for l in prompt.split('\n') if l.strip()]

        seen = set()
        unique_lines = []
        for line in lines:
            key = line[:50].strip()
            if key not in seen:
                seen.add(key)
                unique_lines.append(line)

        optimized = '\n'.join(unique_lines)

        if len(optimized) > max_length:
            optimized = optimized[:max_length] + "...\n[System prompt optimized to save tokens]"

        return optimized

    def filter_redundant_messages(
        self,
        messages: List[Dict[str, Any]],
        keep_patterns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Filter redundant messages"""
        if not keep_patterns:
            keep_patterns = [
                'error', 'success', 'complete', 'create', 'delete', 'failed', 'warning',
                # Indonesian equivalents for the maintainer's native messages
                'gagal', 'berhasil', 'selesai', 'buat', 'hapus',
            ]

        filtered = []

        for msg in messages:
            content = msg.get('content', '').lower()
            role = msg.get('role', '')

            if role == 'system':
                filtered.append(msg)
                continue

            if role == 'tool':
                tool_name = msg.get('name', 'unknown')
                content = msg.get('content', '')
                filtered.append({
                    'role': 'assistant',
                    'content': f"[Tool result] {tool_name}: {content}"
                })
                continue

            is_important = any(pattern.lower() in content for pattern in keep_patterns)

            if is_important or len(filtered) < 5:
                filtered.append(msg)

        return filtered

    def get_optimization_report(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate an optimization report"""
        limit = limit or self.budget.max_tokens

        report = {
            'current_tokens': current_tokens,
            'limit': limit,
            'usage_percent': (current_tokens / limit * 100) if limit > 0 else 0,
            'should_compress': False,
            'compression_recommendation': '',
            'estimated_savings': 0,
            'suggestions': []
        }

        should_compress, reason = self.should_compress(current_tokens, limit)
        report['should_compress'] = should_compress
        report['compression_recommendation'] = reason

        if should_compress:
            compressed, stats = self.compress_messages(messages)
            report['estimated_savings'] = stats.get('saved_tokens', 0)
            report['suggestions'].append(f"Compression could save ~{stats.get('saved_percent', 0):.1f}% tokens")

        if current_tokens > limit * 0.5:
            report['suggestions'].append("Consider using the cache feature to save the current conversation")

        tool_results = [m for m in messages if m.get('role') == 'tool']
        if len(tool_results) > 10:
            report['suggestions'].append(f"{len(tool_results)} tool results present; consider compression")

        return report


# ============================================================
# LLM-driven conversation summarizer
# ============================================================

class LLMSummarizer:
    """Uses a cheap model to produce a structured conversation summary,
    replacing naive truncation.

    Difference from TokenOptimizer._generate_balanced_summary:
    - That one is rule-based fragment stitching (first 150 chars + last 100 chars)
    - This class uses an LLM to understand semantics and produce a structured summary
    """

    # Summary prompt template
    SUMMARY_PROMPT = """Summarize the following conversation history concisely, in the same language as the conversation.
Extract the following information and output as structured text:

1. **User Goals**: What the user wanted to achieve
2. **Completed Actions**: What operations were performed and their results (only outcomes, not tool call details)
3. **Current State**: The current state of the Houdini scene or project
4. **Key Decisions**: Important decisions made during the conversation
5. **Errors & Resolutions**: Any errors encountered and how they were resolved

IMPORTANT:
- Be concise but comprehensive (aim for ~200-400 words)
- Do NOT include raw tool call details or JSON
- Focus on OUTCOMES, not process
- Include all node paths mentioned
- If errors occurred, include the resolution

Conversation to summarize:
---
{conversation}
---"""

    @staticmethod
    def format_rounds_for_summary(rounds: list, max_total_chars: int = 8000) -> str:
        """Format multi-round dialogue as plain text for summarization.

        Args:
            rounds: each round is a message list [[msg1, msg2, ...], [msg3, ...], ...]
            max_total_chars: maximum characters (to prevent oversized summary input)
        """
        lines = []
        total_chars = 0
        for r_idx, r in enumerate(rounds):
            for msg in r:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                if not content:
                    # For assistant messages with tool_calls
                    if role == 'assistant' and 'tool_calls' in msg:
                        tc_names = [tc.get('function', {}).get('name', '?')
                                    for tc in msg.get('tool_calls', [])]
                        content = f"[Called tools: {', '.join(tc_names)}]"
                    else:
                        continue

                # Truncate overly long single messages
                if len(content) > 500:
                    content = content[:500] + '...'

                prefix = {'user': 'User', 'assistant': 'AI', 'tool': 'Tool Result', 'system': 'System'}.get(role, role)
                line = f"[{prefix}]: {content}"
                if total_chars + len(line) > max_total_chars:
                    lines.append(f"... (earlier rounds omitted, {len(rounds) - r_idx} rounds remain)")
                    return '\n'.join(lines)
                lines.append(line)
                total_chars += len(line) + 1

        return '\n'.join(lines)

    @classmethod
    def summarize_rounds(cls, ai_client, rounds: list,
                         model: str = 'deepseek-v4-flash',
                         provider: str = 'deepseek') -> Optional[str]:
        """Use a cheap model to generate a conversation summary.

        Args:
            ai_client: AIClient instance
            rounds: dialogue rounds to summarize
            model: model used for summary (should be a cheap/fast model)
            provider: model provider

        Returns:
            Summary text, or None on failure
        """
        if not rounds:
            return None

        try:
            conversation_text = cls.format_rounds_for_summary(rounds)
            if not conversation_text.strip():
                return None

            prompt = cls.SUMMARY_PROMPT.format(conversation=conversation_text)

            # Call the cheap model via chat (non-streaming)
            summary_messages = [
                {'role': 'user', 'content': prompt}
            ]

            result = ai_client.chat(
                messages=summary_messages,
                model=model,
                provider=provider,
                temperature=0.1,
                max_tokens=600,
                timeout=15,  # 15-second timeout to avoid blocking the main agent loop
            )

            if result and result.get('content'):
                return result['content'].strip()
            return None

        except Exception as e:
            _dbg(f"[LLMSummarizer] Summary generation failed: {e}")
            return None
