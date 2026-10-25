#!/usr/bin/env python3
"""
Single-File Zero-Dependency Coding Agent CLI with API Plugin Architecture
========================================================================
A complete, self-contained coding agent built entirely with Python Standard Library.
No pip dependencies required (zero third-party packages).

Features:
- API Plugin Architecture: Pluggable backends for Gemini, OpenAI, Groq, Anthropic, Ollama, OpenRouter, etc.
- Tool Calling System: Auto-generates schemas via reflection (`inspect`) and docstrings.
- Core Coding Tools: File read/write/edit with unified diff, regex search, directory exploration, shell execution.
- Multi-step ReAct Agent Loop: Observe -> Think -> Act -> Observe -> Finish.
- Interactive CLI / REPL: Colorized terminal UI, slash commands (/help, /model, /provider, /tools, /auto, /diff, /clear), safety confirmation.
- Fallback Resilience: Native function calling + markdown/text action parsing fallback for local/smaller models.
- Pure Standard Library: urllib.request, json, os, sys, subprocess, difflib, ssl, etc.
"""

from __future__ import annotations

import argparse
import ctypes
import difflib
import inspect
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# ==============================================================================
# 1. TERMINAL STYLING & ANSI SUPPORT (CROSS-PLATFORM)
# ==============================================================================

class Colors:
    """ANSI color codes with automatic Windows console support and fallback."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright foreground
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Backgrounds
    BG_BLUE = "\033[44m"
    BG_DARK = "\033[100m"


def enable_ansi_terminal() -> bool:
    """Enables virtual terminal processing on Windows so ANSI colors work."""
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
            mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(h_stdout, mode)
            return True
    except Exception:
        pass
    return False

ENABLE_COLORS = enable_ansi_terminal() and sys.stdout.isatty()

def c(text: str, color: str) -> str:
    """Wraps text in color if terminal supports ANSI."""
    return f"{color}{text}{Colors.RESET}" if ENABLE_COLORS else text


# ==============================================================================
# 2. ZERO-DEPENDENCY .ENV PARSER
# ==============================================================================

def load_dotenv(path: Optional[str] = None) -> Dict[str, str]:
    """
    Parses .env file directly using Python standard library.
    Looks in current directory, parent directories, and user home directory.
    """
    loaded = {}
    candidates = []
    
    if path:
        candidates.append(Path(path))
    else:
        # Search upward from CWD
        curr = Path.cwd()
        for _ in range(4):
            candidates.append(curr / ".env")
            if curr.parent == curr:
                break
            curr = curr.parent
        # Also check vectorless_rag/.env or config folder if exists
        candidates.append(Path.cwd() / "vectorless_rag" / ".env")

    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            # Strip surrounding quotes
                            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                val = val[1:-1]
                            if key not in os.environ:
                                os.environ[key] = val
                            loaded[key] = val
                break
            except Exception:
                continue
    return loaded


# ==============================================================================
# 3. HTTP NETWORKING WITH SSL FALLBACK (ZERO PIP DEPENDENCIES)
# ==============================================================================

def make_http_request(url: str, data: Optional[dict] = None, headers: Optional[dict] = None, method: str = "POST", timeout: int = 45) -> dict:
    """
    Performs standard library HTTP requests via urllib.request.
    Automatically handles SSL certificate verification and graceful fallbacks.
    """
    payload_bytes = None
    req_headers = {"User-Agent": "ZeroDep-CodingAgent/1.0", "Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    if data is not None:
        payload_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=payload_bytes, headers=req_headers, method=method)

    # Attempt with standard context, fallback to unverified context if cert verification fails
    for use_unverified in (False, True):
        try:
            ctx = ssl._create_unverified_context() if use_unverified else ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_msg)
                return {"_http_error": e.code, "_error_payload": err_json, "error": str(err_json)}
            except Exception:
                return {"_http_error": e.code, "_error_payload": err_msg, "error": err_msg}
        except (urllib.error.URLError, ssl.SSLError) as e:
            if not use_unverified and ("CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e).lower()):
                continue  # Retry with unverified context
            if use_unverified:
                return {"_network_error": str(e), "error": str(e)}
        except Exception as e:
            if not use_unverified and ("CERTIFICATE" in str(e) or "ssl" in str(e).lower()):
                continue
            return {"_network_error": str(e), "error": str(e)}
    return {"_network_error": "Connection failed", "error": "Connection failed"}


# ==============================================================================
# 4. API PLUGIN ARCHITECTURE
# ==============================================================================

@dataclass
class ToolCall:
    """Represents a function call requested by the model."""
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class LLMResponse:
    """Normalized response from any LLM plugin."""
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None
    error: Optional[str] = None


class BaseAPIPlugin:
    """
    Abstract base class for LLM API plugins.
    To add a new API provider, subclass this and implement `chat()`.
    """
    name: str = "base"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or ""
        self.model = model or ""
        self.base_url = base_url or ""

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, temperature: float = 0.2) -> LLMResponse:
        raise NotImplementedError


class OpenAICompatiblePlugin(BaseAPIPlugin):
    """
    Plugin for OpenAI, Groq, Together, DeepSeek, OpenRouter, vLLM, LMStudio, etc.
    Uses standard `/v1/chat/completions` endpoint and function calling schema.
    """
    name = "openai"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url)
        self.base_url = self.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not self.base_url.endswith("/chat/completions"):
            self.base_url = self.base_url.rstrip("/") + "/chat/completions"
        self.api_key = self.api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = self.model or os.getenv("OPENAI_MODEL", "gpt-4o")

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, temperature: float = 0.2) -> LLMResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        # Build payload
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            # Format tools for OpenAI schema
            formatted_tools = []
            for t in tools:
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"]
                    }
                })
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"

        res = make_http_request(self.base_url, data=payload, headers=headers)
        if "error" in res and ("_http_error" in res or "_network_error" in res):
            return LLMResponse(error=f"API Error ({res.get('_http_error', 'network')}): {res.get('error')}", raw=res)

        try:
            choice = res["choices"][0]["message"]
            content = choice.get("content")
            tool_calls = []

            if "tool_calls" in choice and choice["tool_calls"]:
                for idx, tc in enumerate(choice["tool_calls"]):
                    func = tc["function"]
                    args = func.get("arguments", "{}")
                    parsed_args = json.loads(args) if isinstance(args, str) else args
                    tool_calls.append(ToolCall(
                        id=tc.get("id", f"call_{idx}"),
                        name=func["name"],
                        arguments=parsed_args
                    ))

            return LLMResponse(content=content, tool_calls=tool_calls, raw=res)
        except Exception as e:
            return LLMResponse(error=f"Failed to parse API response: {e}\nRaw: {res}", raw=res)


class GroqPlugin(OpenAICompatiblePlugin):
    """Preset plugin for ultra-fast Groq API."""
    name = "groq"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        base_url = base_url or "https://api.groq.com/openai/v1"
        api_key = api_key or os.getenv("GROQ_API_KEY", "")
        model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        super().__init__(api_key, model, base_url)


class GeminiPlugin(BaseAPIPlugin):
    """
    Native Google Gemini API Plugin.
    Supports native generateContent with Gemini functionDeclarations & fallback models.
    """
    name = "gemini"

    FALLBACK_MODELS = [
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemma-4-26b-a4b-it",
        "gemini-pro-latest"
    ]

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url)
        self.api_key = self.api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = self.model or os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Converts standard chat messages into Gemini contents structure."""
        system_instruction = None
        contents = []

        for m in messages:
            role = m["role"]
            content = m.get("content", "")

            if role == "system":
                system_instruction = content
            elif role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": str(content) if content else ""}]
                })
            elif role == "assistant":
                parts = []
                if content:
                    parts.append({"text": str(content)})
                if "tool_calls" in m and m["tool_calls"]:
                    for tc in m["tool_calls"]:
                        parts.append({
                            "functionCall": {
                                "name": tc["name"],
                                "args": tc["arguments"]
                            }
                        })
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                # Gemini function response part
                tool_name = m.get("name", "tool")
                result_content = m.get("content", "")
                try:
                    resp_dict = json.loads(result_content) if isinstance(result_content, str) else result_content
                except Exception:
                    resp_dict = {"output": str(result_content)}

                contents.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": tool_name,
                            "response": resp_dict
                        }
                    }]
                })
        return system_instruction, contents

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, temperature: float = 0.2) -> LLMResponse:
        system_instr, contents = self._convert_messages(messages)

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            }
        }
        if system_instr:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instr}]
            }

        if tools:
            # Gemini functionDeclarations format
            declarations = []
            for t in tools:
                declarations.append({
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                })
            payload["tools"] = [{"functionDeclarations": declarations}]

        # Try current model, and fallback if 404 or 503
        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        last_error = None

        for model_candidate in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_candidate}:generateContent?key={self.api_key}"
            res = make_http_request(url, data=payload, method="POST", timeout=45)

            if "_http_error" in res:
                code = res["_http_error"]
                if code in (404, 503, 429):
                    last_error = f"Model {model_candidate} returned HTTP {code}: {res.get('error')}"
                    continue
                return LLMResponse(error=f"Gemini API Error ({code}): {res.get('error')}", raw=res)
            
            if "_network_error" in res:
                return LLMResponse(error=f"Network Error: {res.get('error')}", raw=res)

            # Success with this model! Update active model
            self.model = model_candidate

            try:
                candidates = res.get("candidates", [])
                if not candidates:
                    return LLMResponse(content="", raw=res)
                
                parts = candidates[0].get("content", {}).get("parts", [])
                text_chunks = []
                tool_calls = []

                for idx, part in enumerate(parts):
                    if "text" in part:
                        text_chunks.append(part["text"])
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        tool_calls.append(ToolCall(
                            id=f"gemini_call_{idx}",
                            name=fc.get("name", ""),
                            arguments=fc.get("args", {})
                        ))

                full_text = "\n".join(text_chunks) if text_chunks else None
                return LLMResponse(content=full_text, tool_calls=tool_calls, raw=res)
            except Exception as e:
                return LLMResponse(error=f"Failed parsing Gemini candidate: {e}", raw=res)

        return LLMResponse(error=f"All candidate Gemini models failed. Last error: {last_error}")


class AnthropicPlugin(BaseAPIPlugin):
    """Plugin for Anthropic Claude models via `/v1/messages`."""
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url)
        self.api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = self.model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.base_url = "https://api.anthropic.com/v1/messages"

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, temperature: float = 0.2) -> LLMResponse:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        system_text = ""
        claude_messages = []

        for m in messages:
            if m["role"] == "system":
                system_text += m.get("content", "") + "\n"
            else:
                claude_messages.append({"role": m["role"], "content": m.get("content", "")})

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": claude_messages,
            "temperature": temperature
        }
        if system_text.strip():
            payload["system"] = system_text.strip()

        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"]
                }
                for t in tools
            ]

        res = make_http_request(self.base_url, data=payload, headers=headers)
        if "_http_error" in res or "_network_error" in res:
            return LLMResponse(error=f"Anthropic API Error: {res.get('error')}", raw=res)

        try:
            content_blocks = res.get("content", [])
            text_chunks = []
            tool_calls = []

            for block in content_blocks:
                if block.get("type") == "text":
                    text_chunks.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.get("id", "call"),
                        name=block.get("name", ""),
                        arguments=block.get("input", {})
                    ))
            
            return LLMResponse(
                content="\n".join(text_chunks) if text_chunks else None,
                tool_calls=tool_calls,
                raw=res
            )
        except Exception as e:
            return LLMResponse(error=f"Failed parsing Anthropic response: {e}", raw=res)


class OllamaPlugin(OpenAICompatiblePlugin):
    """Plugin for 100% offline local LLMs running via Ollama."""
    name = "ollama"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model = model or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:latest")
        super().__init__(api_key="ollama", model=model, base_url=base_url)


# Plugin Registry
PLUGIN_REGISTRY: Dict[str, type[BaseAPIPlugin]] = {
    "gemini": GeminiPlugin,
    "openai": OpenAICompatiblePlugin,
    "groq": GroqPlugin,
    "anthropic": AnthropicPlugin,
    "ollama": OllamaPlugin,
}

def register_plugin(name: str, plugin_cls: type[BaseAPIPlugin]):
    """Allow runtime extension of new API plugins."""
    PLUGIN_REGISTRY[name.lower()] = plugin_cls


def create_plugin(provider: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None, base_url: Optional[str] = None) -> BaseAPIPlugin:
    """Factory to instantiate the appropriate API plugin with auto-detection."""
    # Auto-detection if provider not specified
    if not provider:
        if api_key and api_key.startswith("AQ.") or os.getenv("GEMINI_API_KEY"):
            provider = "gemini"
        elif os.getenv("GROQ_API_KEY"):
            provider = "groq"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = "gemini"  # default fallback

    provider = provider.lower()
    plugin_cls = PLUGIN_REGISTRY.get(provider)
    if not plugin_cls:
        raise ValueError(f"Unknown API provider: '{provider}'. Available: {list(PLUGIN_REGISTRY.keys())}")

    return plugin_cls(api_key=api_key, model=model, base_url=base_url)


# ==============================================================================
# 5. CODING AGENT TOOLS (WITH AUTOMATIC SCHEMA GENERATION VIA REFLECTION)
# ==============================================================================

TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

class ToolRegistry:
    """Stores available agent tools and exposes schema generation."""
    def __init__(self):
        self.tools: Dict[str, Callable] = {}
        self.schemas: List[Dict[str, Any]] = []

    def register(self, func: Callable) -> Callable:
        name = func.__name__
        doc = (func.__doc__ or "").strip()
        
        # Parse inspect signature
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            
            annotation = param.annotation if param.annotation != inspect._empty else str
            # Handle Optional or Union if present
            json_type = TYPE_MAP.get(annotation, "string")
            
            prop_def: Dict[str, Any] = {"type": json_type}
            
            # Simple docstring parameter extraction
            param_match = re.search(rf":param {param_name}: (.*)", doc)
            if param_match:
                prop_def["description"] = param_match.group(1).strip()
            else:
                prop_def["description"] = f"Parameter {param_name}"

            properties[param_name] = prop_def

            if param.default == inspect._empty:
                required.append(param_name)

        schema = {
            "name": name,
            "description": doc.split("\n")[0] if doc else f"Tool {name}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

        self.tools[name] = func
        self.schemas.append(schema)
        return func

    def execute(self, name: str, kwargs: Dict[str, Any]) -> str:
        if name not in self.tools:
            return f"Error: Tool '{name}' not found. Available: {list(self.tools.keys())}"
        try:
            res = self.tools[name](**kwargs)
            return str(res)
        except Exception as e:
            return f"Error executing '{name}': {e}"


# Global tool registry
REGISTRY = ToolRegistry()
tool = REGISTRY.register


# --- BUILT-IN CODING TOOLS ---

@tool
def read_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
    """
    Reads the content of a file with line numbers.
    :param path: The relative or absolute path to the file.
    :param start_line: The starting line number (1-indexed).
    :param end_line: The ending line number (optional).
    """
    target = Path(path).resolve()
    if not target.is_file():
        return f"Error: File not found: {path}"
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        total = len(lines)
        start_idx = max(1, start_line) - 1
        end_idx = min(total, end_line) if end_line else total
        
        selected = lines[start_idx:end_idx]
        output = [f"[File: {target.name} | Total Lines: {total}]"]
        for idx, line in enumerate(selected, start=start_idx + 1):
            output.append(f"{idx:4d} | {line.rstrip()}")
        return "\n".join(output)
    except Exception as e:
        return f"Error reading file '{path}': {e}"


@tool
def write_file(path: str, content: str) -> str:
    """
    Creates or completely overwrites a file with content.
    :param path: Target file path.
    :param content: Complete content to write.
    """
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    
    # Create backup if exists
    if target.is_file():
        backup_path = target.with_suffix(target.suffix + ".bak")
        try:
            shutil.copy2(target, backup_path)
        except Exception:
            pass

    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Success: Wrote {len(content)} characters to {target.name} (Backup saved to .bak if existed)."
    except Exception as e:
        return f"Error writing file '{path}': {e}"


@tool
def edit_file(path: str, target_text: str, replacement_text: str) -> str:
    """
    Performs precise search-and-replace on a file and outputs a diff preview.
    :param path: Target file path.
    :param target_text: The exact string to find and replace.
    :param replacement_text: The new replacement string.
    """
    target = Path(path).resolve()
    if not target.is_file():
        return f"Error: File not found: {path}"
    try:
        with open(target, "r", encoding="utf-8") as f:
            original = f.read()

        if target_text not in original:
            return f"Error: target_text was not found in {path}. Make sure whitespace and line breaks match exactly."

        count = original.count(target_text)
        if count > 1:
            return f"Error: target_text occurs {count} times in {path}. Provide more surrounding lines for unique match."

        modified = original.replace(target_text, replacement_text, 1)

        # Generate unified diff for visibility
        diff_lines = list(difflib.unified_diff(
            original.splitlines(),
            modified.splitlines(),
            fromfile=f"a/{target.name}",
            tofile=f"b/{target.name}",
            lineterm=""
        ))

        # Save backup
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))

        with open(target, "w", encoding="utf-8") as f:
            f.write(modified)

        diff_str = "\n".join(diff_lines)
        return f"Success: Replaced target text in {path}.\nDiff:\n{diff_str}"
    except Exception as e:
        return f"Error editing file '{path}': {e}"


@tool
def list_directory(path: str = ".", recursive: bool = False, max_depth: int = 2) -> str:
    """
    Lists directory contents including subfolders and file sizes.
    :param path: Directory path to inspect (defaults to current dir).
    :param recursive: Whether to list subdirectories recursively.
    :param max_depth: Maximum recursion depth.
    """
    target = Path(path).resolve()
    if not target.is_dir():
        return f"Error: Directory not found: {path}"

    results = []
    base_depth = len(target.parts)

    try:
        if not recursive:
            for item in sorted(target.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                size = f"{item.stat().st_size:,} B" if item.is_file() else ""
                results.append(f"{prefix} {item.name:<30} {size}")
        else:
            for root, dirs, files in os.walk(target):
                curr_depth = len(Path(root).parts) - base_depth
                if curr_depth >= max_depth:
                    dirs.clear()
                    continue
                # Skip hidden directories like .git
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                indent = "  " * curr_depth
                rel_root = Path(root).relative_to(target)
                if str(rel_root) != ".":
                    results.append(f"{indent}[DIR]  {rel_root}/")
                for f in sorted(files):
                    if not f.startswith("."):
                        results.append(f"{indent}  [FILE] {f}")
        return "\n".join(results[:100]) or "(Directory is empty)"
    except Exception as e:
        return f"Error listing directory '{path}': {e}"


@tool
def search_files(query: str, path: str = ".", case_sensitive: bool = False, is_regex: bool = False) -> str:
    """
    Searches for text or regex pattern across codebase files.
    :param query: Search string or regex pattern.
    :param path: Directory or file to search within.
    :param case_sensitive: Whether match is case sensitive.
    :param is_regex: Whether query is a regular expression.
    """
    target = Path(path).resolve()
    flags = 0 if case_sensitive else re.IGNORECASE
    matches = []

    try:
        pattern = re.compile(query if is_regex else re.escape(query), flags)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    search_files_list = []
    if target.is_file():
        search_files_list.append(target)
    else:
        for p in target.rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                search_files_list.append(p)

    for fpath in search_files_list:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, start=1):
                    if pattern.search(line):
                        rel_path = fpath.relative_to(Path.cwd()) if fpath.is_relative_to(Path.cwd()) else fpath
                        matches.append(f"{rel_path}:{line_no}: {line.strip()}")
                        if len(matches) >= 30:
                            matches.append("... [output capped at 30 matches]")
                            return "\n".join(matches)
        except Exception:
            continue

    return "\n".join(matches) if matches else f"No matches found for '{query}'"


@tool
def run_shell(command: str, timeout: int = 60) -> str:
    """
    Executes a shell command (PowerShell / Bash) and returns stdout/stderr.
    :param command: Shell command to execute.
    :param timeout: Timeout in seconds.
    """
    try:
        shell_cmd = ["powershell", "-NoProfile", "-Command", command] if os.name == "nt" else ["bash", "-c", command]
        result = subprocess.run(
            shell_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        res = []
        if out:
            res.append(out)
        if err:
            res.append(f"[stderr]\n{err}")
        res.append(f"[Exit code: {result.returncode}]")
        return "\n".join(res)
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error running command: {e}"


@tool
def file_diff(path: str) -> str:
    """
    Compares a file against its .bak backup file to display recent modifications.
    :param path: The file to inspect.
    """
    target = Path(path).resolve()
    backup = target.with_suffix(target.suffix + ".bak")
    if not target.is_file():
        return f"Error: File '{path}' does not exist."
    if not backup.is_file():
        return f"Notice: No backup (.bak) found for {path} to compare against."

    try:
        with open(backup, "r", encoding="utf-8") as f:
            old = f.read().splitlines()
        with open(target, "r", encoding="utf-8") as f:
            new = f.read().splitlines()

        diff = list(difflib.unified_diff(old, new, fromfile=f"{path}.bak", tofile=path, lineterm=""))
        return "\n".join(diff) if diff else "No changes detected between file and backup."
    except Exception as e:
        return f"Error calculating diff: {e}"


# ==============================================================================
# 6. REACT AGENT CORE & TEXT FALLBACK PARSER
# ==============================================================================

SYSTEM_PROMPT = """You are a world-class autonomous Coding Agent CLI assistant.
You solve coding problems, investigate repositories, inspect files, write clean code, and execute tests.

Your operating guidelines:
1. Always explore first: Check directory contents or search before making assumptions about filenames or architecture.
2. Edit with precision: Use `read_file` to inspect lines, then use `edit_file` with exact target text, or `write_file` for new files.
3. Test your work: When applicable, use `run_shell` to execute unit tests or syntax checks (e.g., `python -m py_compile`).
4. Keep the user informed: Explain what you plan to do before invoking tools, and provide clear summaries when finished.

You have access to tools for reading files, writing files, editing files, searching, directory listing, and shell commands.
When you want to call tools, invoke them. Once you have solved the task or have an answer, respond directly with your explanation.
"""

def extract_fallback_tool_calls(text: str) -> List[ToolCall]:
    """
    Fallback parser for models that output tool calls in markdown or text format
    (e.g., Action: tool_name \n Action Input: {...}).
    """
    tool_calls = []
    # Pattern 1: Action / Action Input
    pattern = r"Action:\s*([a-zA-Z0-9_]+)\s*\n(?:Action\s*)?Input:\s*(\{.*?\})"
    for match in re.finditer(pattern, text, re.DOTALL):
        name = match.group(1).strip()
        raw_args = match.group(2).strip()
        try:
            args = json.loads(raw_args)
            tool_calls.append(ToolCall(id=f"fallback_{len(tool_calls)}", name=name, arguments=args))
        except Exception:
            continue

    # Pattern 2: ```json { "tool": "name", "arguments": {...} } ```
    pattern_json = r"```(?:json)?\s*\{\s*\"(?:tool|action|function)\"\s*:\s*\"([^\"]+)\"\s*,\s*\"(?:arguments|params|input)\"\s*:\s*(\{.*?\})\s*\}\s*```"
    for match in re.finditer(pattern_json, text, re.DOTALL):
        name = match.group(1).strip()
        raw_args = match.group(2).strip()
        try:
            args = json.loads(raw_args)
            tool_calls.append(ToolCall(id=f"fallback_{len(tool_calls)}", name=name, arguments=args))
        except Exception:
            continue

    return tool_calls


class CodingAgent:
    """The central Autonomous Agent controller."""

    def __init__(self, plugin: BaseAPIPlugin, auto_approve: bool = False, max_steps: int = 15):
        self.plugin = plugin
        self.auto_approve = auto_approve
        self.max_steps = max_steps
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def reset(self):
        """Resets conversation history."""
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def ask_confirmation(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Asks user approval before executing sensitive operations."""
        if self.auto_approve:
            return True
        
        args_str = json.dumps(args, indent=2)
        print(f"\n{c('[CONFIRM]', Colors.BOLD + Colors.YELLOW)} Agent requests to run: {c(tool_name, Colors.CYAN)}")
        print(f"{c('Arguments:', Colors.DIM)}\n{args_str}")
        try:
            choice = input(f"{c('Approve execution? (y/n/auto): ', Colors.BOLD)}").strip().lower()
            if choice == "auto":
                self.auto_approve = True
                print(c("[Auto-approve enabled for this session]", Colors.GREEN))
                return True
            return choice in ("y", "yes", "")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted by user.")
            return False

    def run_step(self, user_prompt: str) -> None:
        """Executes the multi-turn agent loop for a user query."""
        self.messages.append({"role": "user", "content": user_prompt})

        step = 0
        while step < self.max_steps:
            step += 1
            print(f"\n{c(f'--- Step {step}/{self.max_steps} ---', Colors.DIM)}")
            print(f"{c('[THINKING]', Colors.BOLD + Colors.BLUE)} Waiting for {self.plugin.name} ({self.plugin.model})...")

            response = self.plugin.chat(self.messages, tools=REGISTRY.schemas)

            if response.error:
                print(f"{c('[ERROR]', Colors.BOLD + Colors.RED)} {response.error}")
                break

            # Check for native or fallback tool calls
            tool_calls = response.tool_calls
            if not tool_calls and response.content:
                # Attempt fallback parsing
                fallback_calls = extract_fallback_tool_calls(response.content)
                if fallback_calls:
                    tool_calls = fallback_calls

            # Print assistant thinking/content if present
            if response.content:
                print(f"\n{c('[AGENT]', Colors.BOLD + Colors.GREEN)}\n{response.content}\n")

            if not tool_calls:
                # LLM finished without calling tools
                if not response.content:
                    print(c("(Agent provided empty response)", Colors.DIM))
                break

            # Append assistant message with tool calls to context
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if response.content:
                assistant_msg["content"] = response.content
            assistant_msg["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in tool_calls
            ]
            self.messages.append(assistant_msg)

            # Execute all tool calls
            for tc in tool_calls:
                print(f"{c('[ACTION]', Colors.BOLD + Colors.CYAN)} Tool: {c(tc.name, Colors.BOLD)} | Args: {json.dumps(tc.arguments)}")
                
                # Check user confirmation
                if not self.ask_confirmation(tc.name, tc.arguments):
                    tool_output = "User rejected tool execution."
                    print(f"{c('[SKIPPED]', Colors.YELLOW)} Execution skipped by user.")
                else:
                    start_t = time.time()
                    tool_output = REGISTRY.execute(tc.name, tc.arguments)
                    elapsed = time.time() - start_t

                    # Display preview of tool output
                    preview = tool_output if len(tool_output) <= 500 else tool_output[:500] + f"\n... [truncated {len(tool_output)-500} chars]"
                    print(f"{c(f'[RESULT] ({elapsed:.2f}s)', Colors.BOLD + Colors.MAGENTA)}\n{preview}\n")

                # Append tool observation back to message history
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": tool_output
                })

        if step >= self.max_steps:
            print(f"{c('[NOTICE]', Colors.YELLOW)} Reached maximum iteration limit ({self.max_steps} steps).")


# ==============================================================================
# 7. INTERACTIVE CLI & REPL COMMANDS
# ==============================================================================

def print_banner(agent: CodingAgent):
    banner = f"""
{Colors.BOLD}{Colors.BRIGHT_CYAN}======================================================================
     ____          _ _              _                    _   
    / ___|___   __| (_)_ __   __ _ / \\   __ _  ___ _ __ | |_ 
   | |   / _ \\ / _` | | '_ \\ / _` / _ \\ / _` |/ _ \\ '_ \\| __|
   | |__| (_) | (_| | | | | | (_|/ ___ \\ (_| |  __/ | | | |_ 
    \\____\\___/ \\__,_|_|_| |_|\\__, /_/   \\_\\__, |\\___|_| |_|\\__|
                             |___/        |___/              
{Colors.RESET}
{Colors.BOLD}Zero-Dependency Autonomous Coding Agent CLI{Colors.RESET}
• Provider: {c(agent.plugin.name.upper(), Colors.GREEN)} | Model: {c(agent.plugin.model, Colors.YELLOW)}
• Working Directory: {c(os.getcwd(), Colors.DIM)}
• Type {c('/help', Colors.CYAN)} for available commands or start typing your task!
{Colors.DIM}======================================================================{Colors.RESET}
"""
    print(banner)


def handle_slash_command(cmd: str, agent: CodingAgent) -> bool:
    """Handles interactive CLI slash commands. Returns True if handled, False otherwise."""
    parts = cmd.strip().split(maxsplit=1)
    keyword = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if keyword in ("/help", "/?"):
        print(f"""
{c('Available Commands:', Colors.BOLD)}
  {c('/help', Colors.CYAN)}               Show this help menu
  {c('/tools', Colors.CYAN)}              List all registered coding tools
  {c('/model <name>', Colors.CYAN)}       Switch active LLM model
  {c('/provider <name>', Colors.CYAN)}    Switch API provider (gemini, openai, groq, anthropic, ollama)
  {c('/auto', Colors.CYAN)}               Toggle auto-approval of tool execution ({agent.auto_approve})
  {c('/clear', Colors.CYAN)}              Reset conversation context
  {c('/history', Colors.CYAN)}            View number of messages in context
  {c('/diff <path>', Colors.CYAN)}        Show changes for a modified file
  {c('/shell <cmd>', Colors.CYAN)}        Directly run a shell command
  {c('/exit, exit, quit', Colors.CYAN)}   Quit the application
""")
        return True

    elif keyword == "/tools":
        print(f"\n{c('Registered Agent Tools:', Colors.BOLD)}")
        for t in REGISTRY.schemas:
            params = list(t["parameters"]["properties"].keys())
            print(f"  • {c(t['name'], Colors.GREEN)}({', '.join(params)}) - {t['description']}")
        print()
        return True

    elif keyword == "/model":
        if not arg:
            print(f"Current model: {c(agent.plugin.model, Colors.YELLOW)}")
        else:
            agent.plugin.model = arg
            print(f"Switched model to: {c(arg, Colors.GREEN)}")
        return True

    elif keyword == "/provider":
        if not arg:
            print(f"Current provider: {c(agent.plugin.name, Colors.YELLOW)}")
        else:
            try:
                new_plugin = create_plugin(provider=arg)
                agent.plugin = new_plugin
                print(f"Switched provider to: {c(arg, Colors.GREEN)} (Model: {new_plugin.model})")
            except Exception as e:
                print(f"{c('Error switching provider:', Colors.RED)} {e}")
        return True

    elif keyword == "/auto":
        agent.auto_approve = not agent.auto_approve
        status = c("ENABLED", Colors.GREEN) if agent.auto_approve else c("DISABLED", Colors.YELLOW)
        print(f"Auto-approval is now {status}.")
        return True

    elif keyword == "/clear":
        agent.reset()
        print(c("Conversation context cleared.", Colors.GREEN))
        return True

    elif keyword == "/history":
        print(f"Conversation history contains {len(agent.messages)} messages.")
        for idx, m in enumerate(agent.messages):
            role = m["role"].upper()
            content_preview = str(m.get("content", ""))[:80].replace("\n", " ")
            print(f"  [{idx:2d}] {role:<9}: {content_preview}")
        return True

    elif keyword == "/diff":
        if not arg:
            print("Usage: /diff <filepath>")
        else:
            print(file_diff(arg))
        return True

    elif keyword == "/shell":
        if not arg:
            print("Usage: /shell <command>")
        else:
            print(run_shell(arg))
        return True

    elif keyword in ("/exit", "exit", "quit", ":q"):
        print(c("Goodbye!", Colors.CYAN))
        sys.exit(0)

    return False


def start_repl(agent: CodingAgent):
    """Starts the interactive Read-Eval-Print Loop."""
    print_banner(agent)

    while True:
        try:
            prompt_indicator = f"{c('agent', Colors.BOLD + Colors.CYAN)} {c('>', Colors.BOLD)} "
            user_input = input(prompt_indicator).strip()

            if not user_input:
                continue

            if user_input.startswith("/") or user_input in ("exit", "quit"):
                handle_slash_command(user_input, agent)
                continue

            agent.run_step(user_input)

        except KeyboardInterrupt:
            print(f"\n{c('Operation cancelled by user. Type /exit to quit.', Colors.YELLOW)}")
        except EOFError:
            print(f"\n{c('Exiting...', Colors.CYAN)}")
            break
        except Exception as e:
            print(f"\n{c('[FATAL EXCEPTION]', Colors.BOLD + Colors.RED)} {e}")


# ==============================================================================
# 8. MAIN ENTRYPOINT & CLI ARGUMENT PARSER
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Zero-Dependency Autonomous Coding Agent CLI with API Plugin Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Launch interactive CLI
  python coding_agent.py

  # Run single-shot task with auto-approval
  python coding_agent.py --auto-approve "Search for all python files and inspect main.py"

  # Use Groq or OpenAI provider
  python coding_agent.py --provider groq --model llama-3.3-70b-versatile
  python coding_agent.py --provider ollama --model qwen2.5-coder:latest
        """
    )
    parser.add_argument("prompt", nargs="?", default=None, help="Optional one-shot instruction for the agent")
    parser.add_argument("--provider", "-p", default=None, help="LLM API provider: gemini, openai, groq, anthropic, ollama")
    parser.add_argument("--model", "-m", default=None, help="LLM Model name")
    parser.add_argument("--api-key", "-k", default=None, help="API Key for the provider (or set via .env / env vars)")
    parser.add_argument("--base-url", "-u", default=None, help="Base API endpoint URL (e.g. for Ollama, vLLM, or OpenRouter)")
    parser.add_argument("--auto-approve", "-y", action="store_true", help="Auto-approve tool execution without interactive prompt")
    parser.add_argument("--max-steps", type=int, default=15, help="Maximum agent reasoning steps (default: 15)")

    args = parser.parse_args()

    # Load environment variables from .env
    load_dotenv()

    try:
        plugin = create_plugin(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url
        )
    except Exception as e:
        print(f"{c('Configuration Error:', Colors.BOLD + Colors.RED)} {e}")
        sys.exit(1)

    agent = CodingAgent(plugin=plugin, auto_approve=args.auto_approve, max_steps=args.max_steps)

    if args.prompt:
        # One-shot command execution mode
        agent.run_step(args.prompt)
    else:
        # Interactive REPL mode
        start_repl(agent)


if __name__ == "__main__":
    main()
