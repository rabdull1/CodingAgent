# ⚡ Zero-Dependency Autonomous Coding Agent CLI

> An autonomous, full-featured Coding Agent CLI contained entirely within a **single file** with **zero third-party dependencies**. Built 100% on the Python Standard Library with a pluggable API architecture and an interactive terminal REPL.

---

## 📸 Overview

![Coding Agent CLI Screenshot](Coding_Agent_CLI_Screenshot.png)
 
*The Coding Agent running in Windows Terminal with dynamic ASCII art, interactive `/help` command menu, and multi-step ReAct reasoning loop.*

---

## 🌟 Why This Agent?

Most AI coding agents require hundreds of megabytes of third-party dependencies (`langchain`, `pydantic`, `openai`, `requests`, `aiohttp`, `rich`, etc.) that frequently break environments.

This agent was built with a strict **Zero-Dependency Philosophy**:
- **Zero `pip install`**: Runs on any vanilla Python 3.8+ installation immediately.
- **Single File (`coding_agent.py`)**: Drop it into any codebase, server, container, or remote VM.
- **Pure Standard Library**: Powered by `urllib.request`, `json`, `subprocess`, `inspect`, `difflib`, `re`, `ssl`, and `ctypes`.
- **Pluggable & Extensible**: Seamlessly switch between Gemini, Groq, OpenAI, Claude, and local Ollama without installing vendor SDKs.

---

## ✨ Key Features

- **🧠 Autonomous ReAct Loop**: Continuously reasons, executes tools, inspects observations, and self-corrects until tasks are resolved.
- **🔌 Multi-Provider API Plugin System**:
  - **Google Gemini**: Native REST API with automatic model fallback (`gemini-flash-latest`, `gemini-3.8-flash`, `gemma-4-26b-a4b-it`).
  - **OpenAI & OpenAI-Compatible**: Direct support for OpenAI (`gpt-4o`), Groq (`llama-3.3-70b-versatile`), DeepSeek, OpenRouter, Together AI, and vLLM.
  - **Anthropic Claude**: Full tool-calling support via `/v1/messages` (`claude-3-5-sonnet`, `claude-3-haiku`).
  - **Local Ollama**: 100% offline, free local AI coding (`qwen2.5-coder:latest`, `llama3.1`).
- **🔍 Dynamic Tool Reflection**: Automatically extracts tool schemas, argument types, and descriptions from Python functions using `inspect.signature`.
- **🛡️ Human-in-the-Loop Safety**: Prompts for confirmation before executing file changes or shell commands (toggleable via `--auto-approve` or `/auto`).
- **🔄 Automatic Backups & Diffs**: Automatically creates `.bak` backups before modifying files and displays unified diffs.
- **🎨 Cross-Platform Terminal REPL**: Modern ANSI colored badges (`[THINKING]`, `[ACTION]`, `[RESULT]`, `[AGENT]`) with automatic Windows console support.
- **🔑 Built-in `.env` Loader**: Automatically discovers and loads secrets from `.env` files without `python-dotenv`.

---

## 🚀 Getting Started

### 1. Configure Your API Key
Create a `.env` file in your working directory (or set environment variables):

```env
# Google Gemini (Default)
GEMINI_API_KEY="your-gemini-api-key"

# OR Groq (Ultra-fast inference)
GROQ_API_KEY="gsk_..."

# OR OpenAI
OPENAI_API_KEY="sk-..."

# OR Anthropic Claude
ANTHROPIC_API_KEY="sk-ant-..."
```

### 2. Launch the Interactive REPL
Start the agent in your project root:

```bash
python coding_agent.py
```

### 3. Run in Single-Shot Mode (Non-Interactive)
Pass an instruction directly as a CLI argument:

```bash
python coding_agent.py --auto-approve "Search all python files, check for syntax errors, and run tests"
```

### 4. Switch Providers & Models via CLI

```bash
# Use Google Gemini
python coding_agent.py --provider gemini --model gemini-flash-latest

# Use Groq (Llama 3.3 70B)
python coding_agent.py --provider groq --model llama-3.3-70b-versatile

# Use OpenAI GPT-4o
python coding_agent.py --provider openai --model gpt-4o

# Use Anthropic Claude 3.5 Sonnet
python coding_agent.py --provider anthropic --model claude-3-5-sonnet-20241022

# Use Local Ollama (100% Offline & Free)
python coding_agent.py --provider ollama --model qwen2.5-coder:latest
```

---

## 🎮 Interactive Slash Commands

Inside the REPL (`agent >`), the following commands are available:

| Command | Description |
|---|---|
| `/help` | Display the interactive help menu |
| `/tools` | List all registered tools with dynamic signatures & descriptions |
| `/model <name>` | Switch the active LLM model on the fly |
| `/provider <name>` | Switch API provider (`gemini`, `openai`, `groq`, `anthropic`, `ollama`) |
| `/auto` | Toggle auto-approval mode for tool execution (`True` / `False`) |
| `/diff <path>` | Show unified diff between a modified file and its `.bak` backup |
| `/history` | Inspect conversation message turns and context length |
| `/clear` | Reset conversation memory and start fresh |
| `/shell <cmd>` | Directly execute a terminal shell command (PowerShell / Bash) |
| `/exit`, `quit` | Exit the CLI session |

---

## 🧰 Built-in Coding Tools

All tools are registered with `@tool` and generate schemas automatically:

| Tool | Parameters | Description |
|---|---|---|
| `read_file` | `path`, `start_line=1`, `end_line=None` | Reads file contents with line numbers and safe path resolution. |
| `write_file` | `path`, `content` | Writes or creates files. Automatically creates `.bak` backup for rollback safety. |
| `edit_file` | `path`, `target_text`, `replacement_text` | Precision search-and-replace that enforces unique matches and returns a unified diff. |
| `list_directory`| `path="."`, `recursive=False`, `max_depth=2` | Explores directories, subfolders, and file sizes. |
| `search_files` | `query`, `path="."`, `case_sensitive=False`, `is_regex=False` | Fast grep / regex search across all files in the project. |
| `run_shell` | `command`, `timeout=60` | Executes shell commands cross-platform (PowerShell on Windows, Bash on Unix) with timeout safety. |
| `file_diff` | `path` | Compares any modified file against its `.bak` backup. |

---

## 🔌 Adding Custom API Plugins (in < 20 Lines)

The agent uses a clean plugin interface (`BaseAPIPlugin`). You can connect any custom API, local LLM server, or enterprise gateway:

```python
from coding_agent import BaseAPIPlugin, LLMResponse, register_plugin, make_http_request

class CustomGatewayPlugin(BaseAPIPlugin):
    name = "custom"

    def chat(self, messages, tools=None, temperature=0.2):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        # Zero-dependency HTTP request with built-in SSL handling
        res = make_http_request(self.base_url or "https://api.mycompany.internal/v1/chat", data=payload, headers=headers)
        
        # Return normalized LLMResponse
        return LLMResponse(content=res.get("choices", [{}])[0].get("message", {}).get("content"))

# Register the plugin
register_plugin("custom", CustomGatewayPlugin)
```

Run with your new plugin:
```bash
python coding_agent.py --provider custom --model internal-coder-v1
```

---

## 📁 File Structure

```
Agent_from_scratch/
│
├── ⚡ coding_agent.py          # Complete, standalone Coding Agent CLI (Single File)
├── 📖 README.md                # Dedicated documentation with screenshot and guide
├── 🖼️ assets/
│   └── cli_screenshot.png      # Terminal screenshot
└── 🔑 .env                     # API keys and environment configuration
```

---

## 📜 License

MIT License. Free to use, modify, and distribute.
