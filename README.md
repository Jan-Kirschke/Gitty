<div align="center">

<img width="1019" height="250" alt="Screenshot 2026-11-22 181857" src="https://github.com/user-attachments/assets/e1dff157-f126-4f94-b472-a7411fc778ae" />

# Gitty

**A zero-dependency, TLS-encrypted terminal messenger powered by GitHub identity.**

[![PyPI version](https://img.shields.io/pypi/v/gitty-messenger?color=22c55e&label=PyPI)](https://pypi.org/project/gitty-messenger/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.8-3776ab)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-brightgreen)](#why-gitty)
[![Transport](https://img.shields.io/badge/transport-TLS%201.2%2B-0ea5e9)](#security-model)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](https://github.com/Jan-Kirschke/Gitty/blob/main/pyproject.toml)

[Quickstart](#quickstart) • [Features](#why-gitty) • [Commands](#commands) • [Self-Hosting](#self-hosting) • [Security](#security-model)

</div>

---

## Quickstart

Install via pip and start chatting in seconds:

```bash
pip install gitty-messenger
gitty
```

On first launch, Gitty signs you in via the **GitHub OAuth Device Flow** (`https://github.com/login/device`) and caches your token locally at `~/.gitty/token` (or set `GITHUB_TOKEN`). You never have to enter a password or register a separate account.

```text
$ gitty
```
<img width="1792" height="2400" alt="Gemini_Generated_Image_ma0wj4ma0wj4ma0w" src="https://github.com/user-attachments/assets/00c22b73-08e3-405f-8507-89c2e4fbe43e" />

Connect to a custom host or port anytime:

```bash
gitty chat.jankirschke.de -p 5555
```

---

## Why Gitty?

- **Zero Runtime Dependencies:** Built 100% on Python's standard library (`ssl`, `socket`, `sqlite3`, `threading`, `urllib`, `json`). Fast install, tiny attack surface.
- **TLS Everywhere:** Strict TLS 1.2+ transport encryption with certificate verification enabled by default (`--ca-cert` supported for private CAs).
- **Verified GitHub Identity:** Clients authenticate via GitHub OAuth Device Flow; the server verifies tokens directly against `api.github.com/user` and **never persists tokens** on the server.
- **Immutable ID Permissions:** Admin rights (`GITTY_ADMIN_ID`) and saved friends (SQLite) are bound to immutable numeric GitHub IDs — never spoofing-prone display names.
- **Ephemeral Rooms & DMs:** Create rooms on the fly, check room members, or send direct messages with timestamps. Rooms and chat messages stay in memory only.
- **Terminal Safety:** Incoming messages are stripped of non-printable control sequences to prevent terminal escape injection, and packets are strictly size-bounded (`16 KiB`).
- **Matrix-Wave Startup:** Smooth in-place terminal reveal animation (`Ctrl+C` or `GITTY_NO_ANIMATION=1` to skip).

---

## Commands

### Chat & Rooms
| Command | Description |
|---|---|
| `/rooms` | List active chatrooms |
| `/create <ROOM>` | Create a new chatroom |
| `/join <ROOM>` | Join an existing chatroom |
| `/leave` | Leave the current chatroom |
| `/users` | List users in your current room |
| `/msg <USER> <TEXT>` | Send a direct message |

### Friends (Persisted in SQLite)
| Command | Description |
|---|---|
| `/friends` | Show saved friends and online status |
| `/friend add <USER>` | Resolve GitHub user and save to contacts |
| `/friend remove <USER>` | Remove a contact |

### Admin
| Command | Description |
|---|---|
| `/admin online` | List all connected users |
| `/admin kick <USER>` | Disconnect a user from the server |
| `/admin broadcast <TEXT>` | Broadcast an announcement to everyone |

### General
| Command | Description |
|---|---|
| `/help` | Show grouped command reference |
| `/exit` | Disconnect and quit |

> Inside a room, just type any message to chat. Messages and rooms are ephemeral and never written to disk.

---

## Self-Hosting

### Option 1: Docker Compose

1. Place your TLS certificate and key in `./certs/` (`fullchain.pem` and `privkey.pem`).
2. Look up your numeric GitHub user ID (`https://api.github.com/users/<username>`).
3. Start the server:

```bash
export GITTY_ADMIN_ID=12345678
docker compose up -d --build
docker compose logs -f gitty
```

### Option 2: Direct Python / CLI

```bash
pip install gitty-messenger
gitty-server --cert certs/fullchain.pem --key certs/privkey.pem --admin-id 12345678
```

### Server Configuration

| Environment Variable | CLI Flag | Default | Description |
|---|---|---|---|
| `GITTY_CERT` | `--cert` | *required* | Path to TLS certificate chain (`fullchain.pem`) |
| `GITTY_KEY` | `--key` | *required* | Path to TLS private key (`privkey.pem`) |
| `GITTY_ADMIN_ID` | `--admin-id` | *required* | Numeric GitHub user ID of the server admin |
| `GITTY_DATABASE` | `--database` | `gitty.sqlite3` | SQLite path for persisted friend lists |
| — | `--port` | `5555` | Listening TCP port |

---

## Security Model

| Aspect | Behavior |
|---|---|
| **Transport** | TLS ≥ 1.2 required; plaintext connections are rejected |
| **Authentication** | Client sends OAuth token over TLS; server verifies via `api.github.com/user` and discards it after handshake |
| **Token Storage** | Client caches own token locally in `~/.gitty/token` (`0600` on POSIX); server stores zero tokens |
| **Authorization** | Admin & friendships keyed by immutable GitHub numeric `id`, not mutable `login` |
| **Message Persistence** | None — rooms and chat messages live in RAM only |
| **Input Hardening** | 4,000-char line limit, 16 KiB frame limit, 100-peer / 100-room caps, control-char stripping on client output |

---

## Development

```bash
git clone https://github.com/Jan-Kirschke/Gitty.git
cd Gitty
python -m unittest discover -s tests -v
```

If you like Gitty, consider giving the repo a ⭐!
