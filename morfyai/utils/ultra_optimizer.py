# -*- coding: utf-8 -*-
"""
Token optimizer
Preserves key information so the AI can understand tools while saving tokens.
"""

import copy
import json
import re
from typing import List, Dict, Any, Optional


class UltraOptimizer:
    """Token optimizer - preserves semantic integrity"""

    @staticmethod
    def compress_system_prompt(prompt: str) -> str:
        """Compress the system prompt: remove redundancy but keep core rules"""
        if not prompt:
            return ""
        # Remove excess blank lines
        prompt = re.sub(r'\n{3,}', '\n\n', prompt)
        # Remove comment-only lines
        prompt = re.sub(r'^\s*//.*$', '', prompt, flags=re.MULTILINE)
        return prompt.strip()

    @staticmethod
    def optimize_tool_definitions(tools: List[Dict]) -> List[Dict]:
        """Optimize tool definitions - lightweight trim on a deep copy, preserving full semantics

        Key principles:
        - Never modify the original tools list (deep copy)
        - Keep all description text (AI needs it to understand tool usage)
        - Only strip purely decorative emoji
        """
        optimized = []
        for tool in tools:
            # Deep copy: never modify the original definition
            tool_copy = copy.deepcopy(tool)
            func = tool_copy.get('function', {})
            if not func:
                optimized.append(tool_copy)
                continue

            # Only strip decorative emoji (keep bracketed tags and all text descriptions)
            desc = func.get('description', '')
            desc = re.sub(r'[🔥🎨💡✅❌🟡⚠️🔗]', '', desc)
            func['description'] = desc.strip()

            optimized.append(tool_copy)
        return optimized

    @staticmethod
    def compress_tool_result(result: Dict[str, Any], max_chars: int = 100) -> str:
        """Compress tool result (used for UI display summary, does not affect AI context)"""
        if not result.get('success'):
            error = result.get('error', '')
            return f"Error: {error[:80]}" if error else "Failed"

        result_text = str(result.get('result', ''))
        if not result_text:
            return "OK"

        # Remove excess whitespace
        result_text = re.sub(r'\s+', ' ', result_text).strip()

        if len(result_text) <= max_chars:
            return result_text

        # Keep head and tail
        half = max_chars // 2
        return f"{result_text[:half]}...{result_text[-half:]}"

    @staticmethod
    def optimize_tool_result_message(tool_name: str, result: Dict[str, Any]) -> str:
        """Optimize tool result message format (UI summary only)"""
        compressed = UltraOptimizer.compress_tool_result(result, max_chars=120)
        return f"{tool_name}: {compressed}"

    @staticmethod
    def compress_message_content(content: str, max_tokens: int = 80) -> str:
        """Compress message content (used for summarizing history messages)"""
        if not content:
            return ""

        # Estimate tokens (~4 chars/token)
        estimated_tokens = int(len(content) / 4)

        if estimated_tokens <= max_tokens:
            return content

        # Truncate to a reasonable length
        max_chars = max_tokens * 3
        return content[:max_chars] + "..."

    @staticmethod
    def remove_formatting_overhead(text: str) -> str:
        """Remove Markdown formatting overhead"""
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
        text = re.sub(r'\*([^*]+)\*', r'\1', text)  # *italic*
        text = re.sub(r'`([^`]+)`', r'\1', text)  # `code`
        text = re.sub(r'#{1,6}\s+', '', text)  # headers
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # links
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
