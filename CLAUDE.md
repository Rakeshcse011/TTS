# Claude Code — project context

<!-- cloude-code-toolbox:mcp-skills-awareness-begin -->

### MCP & Skills awareness (Claude Code ToolBox)

_Last synced: 2026-11-10T03:47:36.357Z._

- **Full report:** `.claude/cloude-code-toolbox-mcp-skills-awareness.md` in this workspace (auto-overwritten on each scan). Use it as ground truth for configured servers and skill folders.
- **MCP:** For **live tools** in Claude Code, enable the matching server via `/mcp`. Servers are configured in `~/.claude.json` (user) and `.mcp.json` (project).
- **When the user’s task matches a server** (e.g. Confluence work and a **Confluence** / **Atlassian** MCP is listed), **prefer that server id** and plan on tool use—not only file search.
- **Skills:** Folders below contain `SKILL.md`; attach or cite paths in chat when relevant.

#### Workspace MCP

- `c:\Users\pc\TTS\.mcp.json` _(workspace: TTS)_ — _file missing_

_No active workspace servers in mcp.json._

#### User MCP

- `C:\Users\pc\.claude.json` — _no servers defined_

_No active user-scoped servers in mcp.json._

#### Project skills

_None found (or no workspace open)._

#### User skills

- **find-skills** — `C:\Users\pc\.agents\skills\find-skills` — Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. This skill should be used w

- **kie-chat-agents** — `C:\Users\pc\.agents\skills\kie-chat-agents` — 当用户想让本地 coding agent 跑在 KIE 的 chat 模型(api.kie.ai)上、询问某个 agent 能用哪些 KIE 模型,或询问如何为其配置 base URL、API key、provider 表或模型名时使用。目前覆盖 Codex CLI、Claude Code 和 Grok Build。模型的 wire 协议与 agent 不一致、需要本地翻译代理时也使用本 skill。

- **kie-models** — `C:\Users\pc\.agents\skills\kie-models` — 在 KIE 平台(api.kie.ai)上发现、查价并调用 AI 模型。当用户提到 KIE 或 kie.ai,问"X 用哪个 KIE 模型"、"列出 KIE 模型"、"在 KIE 上跑模型",或需要某个模型的 schema、价格、成功率时使用。

<!-- cloude-code-toolbox:mcp-skills-awareness-end -->
