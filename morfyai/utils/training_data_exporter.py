# -*- coding: utf-8 -*-
"""
Training data exporter
Converts the current chat conversation into training data for LLM fine-tuning.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


class ChatTrainingExporter:
    """Chat history training data exporter

    Converts conversation history into OpenAI fine-tuning format.
    Supports multi-turn dialogue, tool calls, and other complex scenarios.
    """

    @staticmethod
    def _extract_text_content(content) -> str:
        """Extract plain text from a content field

        content may be a str or a list (multimodal message with text/image_url parts).
        Training data keeps only text and discards binary content such as images.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Multimodal format: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return "\n".join(parts)
        return str(content) if content else ""

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize the exporter

        Args:
            output_dir: output directory, defaults to <project_root>/trainData
        """
        if output_dir is None:
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent
            output_dir = project_root / "trainData"

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_conversation(
        self,
        conversation_history: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        split_by_user: bool = True
    ) -> str:
        """Export conversation history as training data

        Args:
            conversation_history: list of conversation messages
            system_prompt: optional system prompt
            split_by_user: whether to split into multiple training samples per user message

        Returns:
            Path of the exported file
        """
        if not conversation_history:
            raise ValueError("Conversation history is empty")

        # Generate training samples based on the strategy
        if split_by_user:
            samples = self._split_by_user_turns(conversation_history, system_prompt)
        else:
            samples = [self._create_single_sample(conversation_history, system_prompt)]

        # Filter out empty samples
        samples = [s for s in samples if s and s.get("messages")]

        if not samples:
            raise ValueError("Could not produce any valid training samples")

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chat_train_{timestamp}_{len(samples)}samples.jsonl"
        filepath = self.output_dir / filename

        # Write JSONL file
        with open(filepath, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')

        return str(filepath)

    def _split_by_user_turns(
        self,
        history: List[Dict[str, Any]],
        system_prompt: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Split into multiple training samples per user message

        Each user request + the corresponding AI response = one training sample.
        Produces several high-quality short samples.
        """
        samples = []

        # Base system message
        base_system = {
            "role": "system",
            "content": system_prompt or self._get_default_system_prompt()
        }

        # Accumulated context (used for multi-turn dialogue)
        context_messages = []
        current_sample_messages = []

        i = 0
        while i < len(history):
            msg = history[i]
            role = msg.get("role", "")

            if role == "user":
                # Start a new sample
                if current_sample_messages:
                    # Save the previous sample
                    sample = self._finalize_sample(base_system, context_messages, current_sample_messages)
                    if sample:
                        samples.append(sample)
                    # Add prior messages to context
                    context_messages.extend(current_sample_messages)
                    # Limit context length
                    context_messages = self._trim_context(context_messages)

                current_sample_messages = [self._clean_message(msg)]

            elif role == "assistant":
                # Clean the assistant message
                cleaned = self._clean_assistant_message(msg)
                if cleaned:
                    current_sample_messages.append(cleaned)

            elif role == "tool":
                # Convert tool message format (ensure tool_call_id is present)
                tool_msg = self._convert_tool_message(msg)
                if tool_msg:
                    current_sample_messages.append(tool_msg)

            i += 1

        # Handle the last sample
        if current_sample_messages:
            sample = self._finalize_sample(base_system, context_messages, current_sample_messages)
            if sample:
                samples.append(sample)

        return samples

    def _create_single_sample(
        self,
        history: List[Dict[str, Any]],
        system_prompt: Optional[str]
    ) -> Dict[str, Any]:
        """Create a single full training sample"""
        messages = []

        # Add the system message
        messages.append({
            "role": "system",
            "content": system_prompt or self._get_default_system_prompt()
        })

        # Process historical messages
        for msg in history:
            cleaned = self._clean_message(msg)
            if cleaned:
                messages.append(cleaned)

        return {"messages": messages} if len(messages) > 1 else None

    def _finalize_sample(
        self,
        system_msg: Dict,
        context: List[Dict],
        current: List[Dict]
    ) -> Optional[Dict[str, Any]]:
        """Finalize a training sample

        Ensures the sample is valid:
        - Must contain a user message
        - Must contain an AI response
        - Tool calls and tool responses must be paired
        """
        if not current:
            return None

        # Check for user message and AI response
        has_user = any(m.get("role") == "user" for m in current)
        has_assistant = any(m.get("role") == "assistant" for m in current)

        if not has_user or not has_assistant:
            return None

        # Build message list
        messages = [system_msg.copy()]

        # Add context (if any)
        if context:
            # Only add recent context to avoid excessive length
            recent_context = context[-6:]  # at most 3 turns
            messages.extend(recent_context)

        # Add current conversation
        messages.extend(current)

        # Validate tool call pairing
        messages = self._validate_tool_calls(messages)

        return {"messages": messages}

    def _clean_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Clean message format"""
        role = msg.get("role", "")
        content = self._extract_text_content(msg.get("content", ""))

        if role == "user":
            if not content or not content.strip():
                return None
            return {"role": "user", "content": content.strip()}

        elif role == "assistant":
            return self._clean_assistant_message(msg)

        elif role == "tool":
            return self._convert_tool_message(msg)

        elif role == "system":
            # Skip system message (we add our own)
            return None

        return None

    def _clean_assistant_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Clean an assistant message"""
        content = self._extract_text_content(msg.get("content", ""))
        tool_calls = msg.get("tool_calls")

        result = {"role": "assistant"}

        if tool_calls:
            # Has tool calls
            result["content"] = None
            result["tool_calls"] = self._clean_tool_calls(tool_calls)
        elif content and content.strip():
            # Plain text response
            result["content"] = content.strip()
        else:
            return None

        return result

    def _clean_tool_calls(self, tool_calls: List[Dict]) -> List[Dict]:
        """Clean tool-call format"""
        cleaned = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                tool_id = tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                function = tc.get("function", {})

                cleaned.append({
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments", "{}")
                    }
                })
        return cleaned

    def _convert_tool_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert tool message format

        Old format: {"role": "tool", "name": "xxx", "content": "..."}
        New format: {"role": "tool", "tool_call_id": "xxx", "content": "..."}
        """
        content = self._extract_text_content(msg.get("content", ""))
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name", "")

        if not content:
            return None

        # If no tool_call_id, generate one
        if not tool_call_id:
            tool_call_id = f"call_{uuid.uuid4().hex[:12]}"

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content[:500]  # cap length
        }

    def _validate_tool_calls(self, messages: List[Dict]) -> List[Dict]:
        """Validate and repair tool-call pairing

        Ensure every tool message has a corresponding assistant tool_calls.
        """
        result = []
        pending_tool_calls = {}  # {tool_call_id: tool_call}

        for msg in messages:
            role = msg.get("role")

            if role == "assistant" and msg.get("tool_calls"):
                # Track tool-call IDs
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id")
                    if tc_id:
                        pending_tool_calls[tc_id] = tc
                result.append(msg)

            elif role == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id in pending_tool_calls:
                    # Has matching assistant tool_calls
                    result.append(msg)
                    del pending_tool_calls[tc_id]
                else:
                    # No matching tool_calls, create one
                    # Extract tool name from content
                    content = msg.get("content", "")
                    tool_name = "execute_tool"
                    if ":" in content:
                        tool_name = content.split(":")[0].strip()

                    # Add assistant message
                    new_tc_id = f"call_{uuid.uuid4().hex[:12]}"
                    assistant_msg = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": new_tc_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": "{}"
                            }
                        }]
                    }
                    result.append(assistant_msg)

                    # Fix up the tool message ID
                    tool_msg = msg.copy()
                    tool_msg["tool_call_id"] = new_tc_id
                    result.append(tool_msg)
            else:
                result.append(msg)

        return result

    def _trim_context(self, context: List[Dict], max_messages: int = 10) -> List[Dict]:
        """Limit context length"""
        if len(context) <= max_messages:
            return context
        return context[-max_messages:]

    def _get_default_system_prompt(self) -> str:
        """Get the default system prompt"""
        return """You are a Houdini executor. Execute operations directly, no explanations.

Rules:
- Call tools directly to execute
- Do not output thinking process
- Check that a node exists before operating on it
- For VEX code prefer create_wrangle_node
- Call verify_and_summarize to verify after completion"""


def export_chat_training_data(
    conversation_history: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
    split_by_user: bool = True
) -> str:
    """Convenience function for exporting chat training data"""
    exporter = ChatTrainingExporter()
    return exporter.export_conversation(conversation_history, system_prompt, split_by_user)
