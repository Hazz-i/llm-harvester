# Design Specification: Claude Code & Luna Hybrid Coding Agent

**Date:** 2026-10-06  
**Status:** Approved  
**Author:** Pair programming (Antigravity & User)

---

## 1. Overview & Problem Statement

### 1.1 Context
- ZeroTwo models (specifically `zerotwo/gpt-6-luna`) are reverse-engineered from consumer web chat sessions and lack native OpenAI/Anthropic tool-calling schemas (`tools` / `tool_calls`).
- Running Claude Code natively with `zerotwo/gpt-6-luna` fails for autonomous file editing and command execution because the model cannot emit `tool_use` events.
- However, Luna possesses a large context window (1.05M tokens) and strong reasoning / code generation capabilities.
- Claude Sonnet (`ag/claude-sonnet-4-6` via 9Router) excels at autonomous tool use (reading files, executing bash, running tests, editing files), but users want to leverage Luna's reasoning engine to handle complex synthesis and save credits.

### 1.2 Objective
Build a **hybrid coding agent architecture** in Claude Code (`nine`):
- **Orchestrator:** Claude Sonnet handles user interaction, repository exploration, file read/write, and test execution.
- **Reasoning Engine:** GPT-6 Luna is exposed to Sonnet as a custom MCP (Model Context Protocol) tool named `consult_luna`.
- When encountering complex tasks (architectural decisions, algorithms, refactorings, or bug diagnoses), Sonnet gathers repo context and delegates the reasoning to Luna, then executes the solution.

---

## 2. Architecture & Data Flow

```
                      User Prompt
                           │
                           ▼
             ┌───────────────────────────┐
             │   Claude Code CLI (nine)  │
             │ Orchestrator: Claude Sonnet│
             └─────────────┬─────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        ▼                                     ▼
[Native Agent Tools]                   [MCP: consult_luna]
 • Bash / Glob / Grep                  (JSON-RPC stdio)
 • FileRead / FileEdit                        │
        │                                     ▼
        │                              ┌───────────────┐
        │                              │ luna_server.py│
        │                              └──────┬────────┘
        │                                     │ (HTTP POST)
        │                                     ▼
        │                       ┌─────────────────────────────┐
        │                       │ Primary: http://127.0.0.1:8787│
        │                       │ Fallback: nine.hazz.biz.id  │
        │                       └─────────────┬───────────────┘
        │                                     │
        │                                     ▼
        │                       ┌─────────────────────────────┐
        │                       │     ZeroTwo GPT-6 Luna      │
        │                       │   (Reasoning / Generation)  │
        │                       └─────────────┬───────────────┘
        │                                     │
        └────────◄── (Generated Solution) ────┘
        │
        ▼ (Applies Edits & Runs Verification)
Target Project Codebase
```

---

## 3. Component Details

### 3.1 MCP Server: `~/.claude/mcp/luna_server.py`
- **Protocol:** Standard Model Context Protocol (MCP) JSON-RPC 2.0 over `stdio`.
- **Runtime:** Python 3 standard library (`urllib.request`, `json`, `sys`, `os`) to avoid external dependencies and ensure fast startup.
- **Tool Definition:**
  - **Name:** `consult_luna`
  - **Description:** `"Consult GPT-6 Luna for deep reasoning, architectural designs, complex bug diagnosis, or algorithm generation. Provide the task description and relevant code context."`
  - **Input Schema:**
    ```json
    {
      "type": "object",
      "properties": {
        "task": {
          "type": "string",
          "description": "The specific question, architectural problem, or code to design/solve."
        },
        "context": {
          "type": "string",
          "description": "Relevant code snippets, error traces, or project context gathered by the orchestrator."
        },
        "reasoning_effort": {
          "type": "string",
          "enum": ["low", "medium", "high"],
          "default": "medium",
          "description": "Reasoning depth requested from Luna."
        }
      },
      "required": ["task"]
    }
    ```
- **Connection Routing:**
  1. **Primary Target:** `http://127.0.0.1:8787/v1/chat/completions` (local `zt-harvester` shim). It automatically pulls active session access tokens from `harvest/sessions.jsonl`.
  2. **Fallback Target:** `https://nine.hazz.biz.id/v1/chat/completions` using the API key loaded from `~/.secrets`.
- **Response Sanitization:** Strips internal ZeroTwo entity tags (`<ent>`, `</ent>`) and formats output cleanly.

### 3.2 Orchestrator Configuration (`~/.secrets`)
- Restore default models to Sonnet:
  ```bash
  export NINEROUTER_SONNET="ag/claude-sonnet-4-6"
  export NINEROUTER_OPUS="ag/claude-sonnet-4-6"
  export NINEROUTER_HAIKU="ag/claude-sonnet-4-6"
  ```
- Retain existing `NINEROUTER_URL` and `NINEROUTER_KEY`.

### 3.3 Claude Code MCP Registration
- Register `luna` in Claude Code's global configuration (`~/.claude.json` or `~/.claude/settings.json`):
  ```json
  "mcpServers": {
    "luna": {
      "command": "python3",
      "args": ["/home/kki-laptop-025/.claude/mcp/luna_server.py"]
    }
  }
  ```

### 3.4 Orchestrator System Guidance (`~/.claude/CLAUDE.md`)
- Add system instructions to inform Sonnet of its hybrid role:
  - *"You have access to the `consult_luna` MCP tool powered by GPT-6 Luna (large context & reasoning engine). When dealing with complex logic, refactoring plans, or tough bugs, first inspect relevant files, then invoke `consult_luna` with the gathered context to get an architectural or algorithmic plan. Finally, implement and test the solution using FileEdit and Bash."*

---

## 4. Error Handling & Edge Cases

1. **Shim / Luna Unreachable:**
   If both local shim and 9Router fail to respond within timeout (60 seconds), `consult_luna` returns an explicit error message (`"Luna consultation failed: <reason>"`). Sonnet falls back to solving the problem using its own reasoning.
2. **Context Size Limit:**
   If the context passed to `consult_luna` exceeds 25,000 characters, `luna_server.py` truncates or summarizes to avoid triggering ZeroTwo web payload limits.
3. **Session Expiry:**
   Local shim automatically proactively refreshes tokens via Supabase endpoint when approaching expiry.

---

## 5. Verification Plan

1. **Unit Verification:**
   Test `luna_server.py` directly by feeding a standard MCP JSON-RPC `tools/call` payload over stdin and validating that stdout emits a valid JSON-RPC result.
2. **MCP Registration Verification:**
   Run `claude mcp list` or inspect `nine` startup to ensure `luna` server and `consult_luna` tool are recognized.
3. **End-to-End Test:**
   Execute:
   ```bash
   nine -p "Use the consult_luna tool to ask for an implementation design for an LRU cache in Python. Print what Luna suggested."
   ```
   Confirm Sonnet calls `consult_luna`, receives the response, and outputs the result.
