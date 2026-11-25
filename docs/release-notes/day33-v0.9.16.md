Day 33: chat with Ollama Cloud models.

- **Chat with Ollama Cloud models.** Press **Load** on a CLOUD model in Models and your chats go to it on Ollama Cloud, using the key saved in Settings → Cloud API keys. Streaming, **Stop** and the message queue work as usual. The status pill and each reply say CLOUD, and your first cloud message asks once before it leaves your Macs. **Unload**, or loading a model on your Macs, sends chats back to the Macs.
- **Restart keeps your choice.** If chats went to a cloud model, they still do after a restart; if they went to your Macs, they still do. A missing or wrong key says so plainly instead of switching to the Macs.
- **Local network warning.** From another device on the same Wi-Fi or network, cloud chats need an explicit OK first: anyone there who can open Caravan's page can chat through your Ollama Cloud account and use up your plan, and what they type goes to Ollama's servers. Tailscale is the safer way. The key is never shown there.
- The key is never logged, shown, or saved in a chat. Plain errors for no key, a rejected key, an unknown model, usage limits, and no internet. All five languages.
- A live chat with a real key on Macs is not part of this release's testing; the tests use a local stand-in for Ollama.
- Tests: 2,359 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
