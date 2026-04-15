# Skill: Remote-Control Fallback

## When To Use

When the Claude Code iOS / desktop app is stuck on "Remote Control connecting…" and won't load a session. The watchdog's `reactivate-remote.sh` auto-handles most of these within a minute — use this skill when you need to reach a session *before* the watchdog does, or when the watchdog's reactivation itself fails.

## Why It Happens

`/remote-control` session URLs depend on Anthropic's relay service. The chat itself is healthy in tmux; only the relay binding is broken. Common causes:
- Anthropic relay momentarily unreachable.
- Network blip between your phone and the relay.
- The CLI's `/remote-control` slash command hit a transient error.

## The Fallback Path

Open https://code.casinv.dev on any device — this is the droplet's `ttyd` web terminal. Then:

```
tmux attach -t claude
```

Joins the main tmux session. To go to a specific project window:

```
tmux attach -t claude \; select-window -t <project>
```

Detach with **Ctrl-B** then **D**.

## Sending Input From The Terminal

The ttyd terminal lets you type directly into the Claude Code CLI. iPhone keyboards on a terminal aren't ideal (punctuation is buried, autocorrect interferes), but this path doesn't depend on relays working.

## Manual Reactivation

If you have terminal access and want a clean remote-control URL:

```bash
/usr/local/bin/reactivate-remote.sh <project>
```

This:
1. Escapes any stuck slash-command menu.
2. Re-issues `/remote-control` in the target tmux window.
3. Captures the new URL.
4. Updates the bookmark at `/var/www/landing/remote/<project>.html`.

Tap the bookmark from your phone to reach the new URL.

## When Everything Fails

If ttyd itself is unreachable:
- SSH directly: `ssh root@159.223.127.125` (from a laptop — no iPhone SSH).
- `tmux attach -t claude` from the SSH session.
- If tmux session itself is gone, `systemctl restart claude-tmux` rebuilds it and `claude-respawn-boot.service` will fire to respawn project chats.

## Integration

- `SKILLS/session-resilience.md` — the automatic recovery path this is a fallback for.
- `SKILLS/multi-project-windows.md` — the overall architecture.
