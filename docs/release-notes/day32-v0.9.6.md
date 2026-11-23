Day 32 part B, a mid-day release (Day 32 continues with localization).

- **Stop a reply.** While a reply is written, **Stop** sits under Send. It really stops the model: Caravan closes its request, the Macs (including the split helper) stop writing, even while still reading a long prompt, and are ready for your next message. The words so far stay, marked "(stopped)", and the reply is never re-run after a restart.
- **Keep typing while it answers.** Send reads **Queue**. Queued messages wait as chips above the box (× to cancel) and send in order when the reply ends, also after an error or Stop.
- **Tidier header.** The model and its status sit just above the chat, **Update available** sits next to the theme switch, and nothing wraps, even on a phone. Long model names end in "…"; hover for the full name.
- **Ollama Cloud key.** Settings → **Cloud API keys** saves your Ollama Cloud key on this Mac (only the last 4 characters are ever shown). Picking a cloud model asks for the key right there, and cloud models say **Load** instead of Download. Chatting with cloud models comes in a later update.
- **This update reloads the model once** (the chat worker changed to make Stop work).
- 2,120 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#part-b-header-layout-v096).
