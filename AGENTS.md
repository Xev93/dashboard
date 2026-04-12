# Dashboard Project Rules

## Delegation Mandate (CRITICAL - Claude token budget)

**Claude Opus usage is rate-limited on this project.** Sisyphus (the Opus primary) is an **ORCHESTRATOR ONLY**. ALL implementation work MUST be delegated to GPT-backed categories via the `task()` tool.

This is not a preference - it is a hard requirement for this project.

### Required delegation routing

| Work type | Exact call | Resolves to |
|---|---|---|
| Implementation, features, refactors, bug fixes | `task(category="deep", load_skills=[...], description="...", prompt="...")` | `openai/gpt-5.4 medium` |
| Hard logic, algorithms, architecture implementation | `task(category="ultrabrain", load_skills=[...], description="...", prompt="...")` | `openai/gpt-5.4 xhigh` |
| Trivial single-file changes, typo fixes, rename | `task(category="quick", load_skills=[...], description="...", prompt="...")` | `openai/gpt-5.4-mini` |
| Codebase exploration / pattern search | `task(subagent_type="explore", load_skills=[], run_in_background=true, ...)` | `claude-haiku-4-5` (cheap) |
| External docs / library research | `task(subagent_type="librarian", load_skills=[], run_in_background=true, ...)` | provider fallback |
| Architecture / debugging consultation | `task(subagent_type="oracle", load_skills=[], ...)` | `openai/gpt-5.4 high` |
| Plan review / QA | `task(subagent_type="Momus", load_skills=[], ...)` | `openai/gpt-5.4 xhigh` |
| Multi-step planning (interview mode) | `task(subagent_type="Prometheus", load_skills=[], ...)` | `claude-opus-4-6 max` (use sparingly) |

### Forbidden patterns

- ❌ **Implementing code directly in the primary (Opus) session for anything >5 lines.** Write operations should originate from a delegated subagent.
- ❌ **`omc ask codex`** - that is a CLI advisor subprocess from oh-my-claudecode, NOT OpenCode's delegation pipeline. It produces text artifacts, not file edits, and burns a separate Codex session without shared context.
- ❌ **`task(subagent_type="hephaestus", ...)`** - hephaestus is a README personification of the `deep` category, NOT a registered subagent. Use `task(category="deep", ...)` instead.
- ❌ **`task(subagent_type="atlas", ...)`** - same issue. Not registered as a subagent.
- ❌ **`task(subagent_type="Sisyphus-Junior", ...)` WITHOUT a category** - defaults to `claude-sonnet-4-6`, which defeats the token-saving goal. Always pair Sisyphus-Junior with a GPT-backed category.
- ❌ **`task(subagent_type="oh-my-claudecode:executor", ...)`** - runs on Claude via the Claude Code plugin. Defeats the purpose.
- ❌ **`task(subagent_type="build", ...)`** - default OpenCode agent, runs on Claude.
- ❌ **Long multi-step work in the primary session** - if you find yourself reading more than 2-3 files or making more than a handful of edits directly, STOP and delegate the remaining work via `task(category="deep", ...)`.

### What Opus stays for

Opus orchestration is expensive but high-quality. Use it ONLY for:

- Task decomposition and todo list creation
- Routing decisions (picking the right `category` / `subagent_type`)
- Reviewing delegated results before accepting and merging them
- Coordinating parallel delegations (firing multiple `task()` calls simultaneously)
- Answering user questions directly (no implementation work)
- Clarification dialogues with the user

### Default bias

**DELEGATE.** Work directly in the primary session ONLY for:
- Genuine one-liners (e.g. changing a single config value)
- Trivial inspection/diagnosis (reading a file, running `git status`)
- Answering a user question that needs no file changes

If there is ANY doubt about whether to delegate, **delegate**. The token-saving goal outweighs small inefficiencies from over-delegation.

### Delegation prompt structure (enforced)

Every `task(category="...", ...)` call MUST include a prompt with all six sections:

```
[CONTEXT]: What I'm working on, which files/modules are involved, what approach I'm taking
[GOAL]: The specific outcome needed, with success criteria
[REQUIRED TOOLS]: Explicit tool whitelist (Read, Edit, Write, Bash, etc.)
[MUST DO]: Exhaustive requirements - leave nothing implicit
[MUST NOT DO]: Forbidden actions to block rogue behavior
[CONTEXT FILES]: Specific file paths the subagent should read first
```

Vague prompts to delegated subagents produce worse output than doing the work yourself, so this structure is mandatory.

### Parallel delegation

When the work decomposes into independent subtasks, fire multiple `task(category="deep", run_in_background=true, ...)` calls **in parallel in a single message**. Do not wait for one to finish before starting the next if they are independent.

After firing, END your response and wait for the `<system-reminder>` notifications that tasks have completed. Never poll `background_output` on running tasks.

---

## Verification

After completing any delegated work, run `bunx oh-my-opencode doctor --verbose` to confirm the delegation pipeline resolved to GPT for those tasks.

If a delegation accidentally resolves to Claude (visible as `anthropic/claude-*` in the worker's model string), that is a bug in the category routing and should be reported.
