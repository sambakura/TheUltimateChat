# TheUltimateChat

> Ein dezentraler Terminal-Chat mit Web-Zugang — Discord-Feeling, Hacker-Ästhetik, kollaboratives Coding mit KI.

---

## Vision

TheUltimateChat ist kein weiterer Webchat. Es ist ein **Terminal-first Gruppenraum** für Leute die zusammen bauen, hacken oder einfach quatschen wollen — mit dem Feeling von Minecraft-Chat-Commands, der Struktur von Discord und dem Tiefgang eines kollaborativen Coding-Tools.

Der Chat ist gleichzeitig eine **lebendige Code-Bibliothek**: jeder Code-Block den jemand sendet, wird automatisch als Snippet gespeichert, ist durchsuchbar, kombinierbar und direkt als KI-Kontext nutzbar. Wer `/open parser.py` tippt, öffnet einen gemeinsamen Live-Editor. Wer `/ask claude --with parser.py "optimiere das"` tippt, bekommt eine Antwort die selbst wieder zum Snippet wird.

Alles im Terminal. Alles mit Slash-Commands. Nichts auf dem Server gespeichert was da nicht hingehört.

---

## Kernprinzipien

| Prinzip | Bedeutung |
|---|---|
| **Dezentral** | Jeder User ist ein Node. Snippets und History liegen lokal, nicht auf dem Relay. |
| **Relay routet nur** | Der Server speichert keine Nachrichten dauerhaft — nur kurzzeitig als Buffer für Offline-User (TTL 7 Tage). |
| **Identität = Keypair** | Kein Account auf dem Server. Dein Ed25519-Keypair ist deine Identität. |
| **Chat ist async** | Niemand sieht was du tippst bis du Enter drückst. Kein "tippt gerade...". |
| **Editor ist live** | Wer `/open` tippt, landet in einem CRDT-Editor der für alle live synchronisiert. |
| **AI gehört dir** | Claude Code und Gemini CLI sind vorinstalliert — jeder bringt seinen eigenen API-Key mit. |

---

## Architektur

```
  BROWSER                    SSH
  chat.deinserver.de    ssh chat@server
         |                    |
         v                    v
  +----------------------------------+
  |    xterm.js / textual-web        |
  |    FRONTEND                      |
  +----------------+-----------------+
                   | WebSocket / WSS
                   v
  +----------------------------------+
  |    RELAY  (Proxmox / VPS)        |
  |    routes . buffers . OG-fetch   |
  +----------+---------------+-------+
             |               |
             v               v
          NODE A           NODE B
        keypair +         keypair +
        snippets/         snippets/
        messages/         messages/
        .claude/          .claude/
        .gemini/          .gemini/
```

### Lokales Dateisystem (pro User)

```
~/.shellchat/
  ├── identity.key        # Ed25519 Keypair (Nostr-style)
  ├── sessions.json       # Kanal-Abonnements
  ├── messages/           # Chat-History pro Kanal
  │   ├── general.log
  │   ├── dev.log
  │   └── projekt-sdr.log
  ├── snippets/           # Snippet-Bibliothek
  │   ├── index.json      # Metadaten (author, time, lang, tags)
  │   └── files/          # Snippet-Inhalte
  ├── .claude/            # Anthropic Credentials (nur der User)
  └── .gemini/            # Google Credentials (nur der User)
```

---

## Zugang

### Browser (primär)

```
chat.deinserver.de
```

- xterm.js im Browser — sieht identisch aus wie ein echtes Terminal
- Cloudflare HTTPS davor, kein offener SSH-Port nötig
- Funktioniert auf Mobile ohne Extra-App
- HTML-Embeds und iframe-Preview für HTML-Snippets nativ möglich
- Kein Client-Install nötig

### SSH (Power User)

```bash
ssh chat@deinserver.de
```

- Echtes Terminal, Sixel für Bild-Embeds
- Selber Relay, selbe App

### Ein Codebase — beide Wege

Das gesamte Frontend ist in **Textual** (Python TUI-Framework) geschrieben.
- Im Terminal: läuft direkt
- Im Browser: `textual-web` deployt es automatisch als xterm.js-App

Kein separater Web-Frontend-Code nötig.

### First Login

```
[1/4]  Alias wählen         → niklas_
[2/4]  Keypair generieren   → ~/.shellchat/identity.key  (lokal, niemals den Server)
[3/4]  Claude Auth          → claude auth login  (Browser-OAuth)
[4/4]  Gemini Auth          → gemini auth login  (optional, Browser-OAuth)

✓ Willkommen. Verbinde mit #general...
```

Schritte 3 und 4 sind optional. ShellChat funktioniert ohne AI.

---

## Kanäle

Wie Discord — keine Sessions, keine Projekte. Kanäle.

```
SERVER (dein Relay)
│
├── #general          ← alle, offen, kein Invite nötig
├── #dev              ← Code + Snippets + Editor
├── #random
│
├── #projekt-sdr      ← invite-only (Public Key Whitelist)
├── #projekt-raspi    ← invite-only
│
└── [+] /channel new #name
```

### Was jeder Kanal hat

- **Chat** — async, Nachrichten erscheinen erst nach Enter, kein Typing-Indicator
- **Snippet-Bibliothek** — alle Code-Blöcke die je in dem Kanal gesendet wurden
- **Online-Liste** — Heartbeat-basiert, wer ist gerade aktiv
- **Editor** — wird per `/open <snippet>` geöffnet, live CRDT für alle die reingehen
- **Tickets** — optional, pro Kanal, WorkFlowShell-DNA

### Invite-only

```bash
/invite @alice #projekt-sdr   # Alice bekommt Invite-Link im Chat
/join #projekt-sdr            # mit Invite-Link oder Key
```

Wer keinen Invite hat, sieht den Kanal nicht mal in `/channels`.

---

## Snippets ✦

Das Herzstück. Code-Blöcke im Chat werden automatisch zu durchsuchbaren, kombinierbaren, KI-fähigen Snippets — ohne extra Aufwand.

### Entstehung

Du sendest einen Code-Block im Chat:

```
╔═ python ══════════════════════════════╗
║ def parse_cb(data):                   ║
║   freq = data.get('freq')             ║
║   return {'freq': freq}               ║
╚══════════════ /open sdr-parser.py ════╝
```

Im Hintergrund passiert automatisch:
- Datei gespeichert unter `~/.shellchat/snippets/files/sdr-parser.py`
- Metadaten in `index.json`: `name · author · timestamp · language · ai-tags`
- AI-Tags werden automatisch per Claude/Gemini gesetzt (z.B. `parser · sdr · dict`)
- Relay speichert Metadaten für Kanal-Suche

### Finden & Referenzieren

```bash
/pull @alice 09:34           # Alices Snippet von 09:34
/pull --find "freq ="        # Volltextsuche im Snippet-Inhalt
/pull --lang python          # alle Python-Snippets heute
/pull --tag sdr              # nach AI-Tag filtern
/snippets                    # komplette Bibliothek des Kanals
```

### Kombinieren

```bash
/merge parser.py utils.py    # kombinierter Block erscheint im Chat → wird selbst Snippet
/include parser.py           # zieht Snippet in deinen aktuellen Code-Block beim Tippen
/diff parser.py parser-v2.py # zeigt Unterschiede
```

### Als AI-Kontext

```bash
/ask claude --with parser.py "optimiere die Fehlerbehandlung"
/ask gemini --with parser.py utils.py "was fehlt noch?"
/ask claude --with parser.py --private "check ob das sicher ist"
# --private: nur du siehst die Antwort
# AI-Antwort wird automatisch selbst zum Snippet
```

### Als Live-Editor öffnen

```bash
/open parser.py
```

```
╔═══════════════════════════════════════╗
║ def parse_cb(data):                   ║
║   freq = data.get('freq')|niklas      ║  ← Cursor sichtbar
║   ret|alice                           ║  ← Cursor sichtbar
║   return {'freq': freq}               ║
╚═══════════════════════════════════════╝
```

- CRDT-Sync (Automerge/Yjs) über den Relay
- Cursor-Positionen aller Beteiligten live sichtbar (farbig, mit Name)
- Auto-save alle 30s → neues Snippet im Kanal

---

## AI Layer

### Prinzip: Jeder bringt seinen eigenen Key

Der Relay sieht nie einen API-Key. Jeder User authentifiziert sich beim First Login mit seinen eigenen Accounts. Billing läuft auf den jeweiligen User-Account.

```
~/.shellchat/.claude/credentials    # chmod 600, nur du
~/.shellchat/.gemini/credentials    # chmod 600, nur du
```

### Sichtbarkeit im Kanal

```
<niklas> /ask claude --with parser.py "optimiere das"

┌─ Claude [niklas] ──────────────────────────────┐
│ Zeile 3 könnte effizienter sein:               │
│ ╔═ python ══════════════════════════════════╗  │
│ ║ freq = data.get('freq', 0)               ║  │
│ ╚═══════════════════════════════════════════╝  │
└────────────────────────────────────────────────┘
→ sichtbar für alle im Kanal
→ wird automatisch zum Snippet

<niklas> /ask claude --private "..."
→ nur du siehst die Antwort (wie Flüstern)
```

### Code-Input + AI

Beim Tippen eines Code-Blocks im Chat:

| Taste | Aktion |
|---|---|
| `Tab` | Claude-Suggestion übernehmen |
| `Shift+Tab` | Gemini-Suggestion stattdessen |
| `Enter` | sendet — erst dann sehen's andere |

Suggestions erscheinen als Ghost-Text (lokal, Fish-style, niemals geleakt).

---

## Embeds

### URL-Embeds

Wenn eine URL in einer Nachricht erkannt wird:
1. Relay fetcht OG-Metadaten (title, description, image, site)
2. Browser → echtes HTML-Embed (OG-Karte)
3. SSH-Terminal → ANSI-Box mit Rahmen

### Bild-Embeds

- Browser (xterm.js) → `<img>` direkt im Terminal
- SSH mit Sixel-Support → Thumbnail wird gerendert
- SSH ohne Sixel → ANSI-Art-Fallback via `chafa`

### HTML-Snippet-Preview

Wenn ein HTML-Snippet per `/open` betrachtet wird:
- Browser → iframe-Preview direkt im Chat-Fenster
- SSH → ANSI-Render

---

## Tech Stack

| Schicht | Technologie | Begründung |
|---|---|---|
| TUI Framework | **Textual** (Python) | läuft im Terminal UND Browser via textual-web |
| Web Terminal | **xterm.js** | VS Code's Terminal, goldstandard |
| Smart Input | **prompt_toolkit** | Fish-style Suggestions, History |
| Live Syntax HL | **tree-sitter** | 500+ Sprachen, Echtzeit |
| Code-Rendering | **Pygments** | bat-style ANSI Output |
| CRDT (Editor) | **Automerge** / **Yjs** | konfliktfreie kollaborative Edits |
| Identität | **Ed25519** Keypairs | Nostr-style, dezentral |
| Relay Transport | **WebSockets** (asyncio) | simpel, bewährt |
| Bild-Embed SSH | **chafa** + Sixel | Bilder im Terminal |
| AI CLI | **Claude Code CLI** + **Gemini CLI** | per-user, eigene Credentials |
| Reverse Proxy | **Cloudflare** | HTTPS, kein Port-Forwarding |

---

## Geplante Projektstruktur

```
TheUltimateChat/
├── relay/                    # Server
│   ├── server.py             # WebSocket Relay (asyncio)
│   ├── channels.py           # Channel-Management
│   ├── snippets.py           # Snippet-Metadaten (index)
│   ├── embed.py              # OG-Fetch & Embed-Rendering
│   └── buffer.py             # Offline-Message-Buffer (TTL)
│
├── client/                   # Terminal/Web Client (Textual)
│   ├── app.py                # Haupt-TUI-App
│   ├── chat.py               # Chat-View (Message-Stream)
│   ├── editor.py             # CRDT Live-Editor
│   ├── snippets.py           # Snippet-Bibliothek UI
│   ├── input.py              # prompt_toolkit Input-Engine
│   └── auth.py               # First-Run Wizard
│
├── shared/                   # Gemeinsamer Code
│   ├── protocol.py           # Event-Format (Message, Snippet, Edit, ...)
│   ├── crypto.py             # Keypair-Generierung & Signierung
│   └── crdt.py               # CRDT-Wrapper (Automerge/Yjs)
│
├── docs/
│   └── shellchat-architektur.jsx    # Interaktive Architektur (Claude Chat)
│
├── install.sh                # One-Line-Installer
│   # ssh install@server.de | bash
│   # → client + claude + gemini + first-run wizard
│
├── requirements.txt
└── README.md
```

---

## Slash Commands Referenz

### Navigation
```
/channels                     # alle sichtbaren Kanäle
/join #name                   # Kanal betreten
/leave                        # Kanal verlassen
/invite @user #channel        # User einladen (invite-only Kanal)
/online                       # wer ist wo aktiv
/theme                        # Terminal-Farbthema wechseln
```

### Chat
```
/me <aktion>                  # Emote — /me schaut die Logs
/w <user> nachricht           # flüstern (nur Sender + Empfänger)
/edit                         # letzte eigene Nachricht ändern
/del                          # letzte Nachricht löschen
/embed off                    # Embeds für dich deaktivieren
/name <alias>                 # Anzeigename ändern
```

### Snippets
```
/snippets                     # Snippet-Bibliothek des Kanals
/pull @user HH:MM             # Snippet von User + Uhrzeit
/pull --find "suchtext"       # Volltextsuche
/pull --lang python           # nach Sprache filtern
/pull --tag <tag>             # nach AI-Tag filtern
/open <snippet>               # kollaborativen Live-Editor öffnen
/merge file1 file2            # Snippets kombinieren
/diff file1 file2             # Unterschiede anzeigen
/include <snippet>            # in aktuellen Block ziehen
```

### AI
```
/ask claude --with <f> "..."  # Claude mit Snippet als Kontext
/ask gemini --with <f> "..."  # Gemini mit Snippet als Kontext
/ask claude --private "..."   # nur du siehst die Antwort
/ai compare "..."             # beide KIs antworten parallel
```

### Tickets
```
/ticket new                   # neues Ticket
/ticket list                  # alle Tickets des Kanals
/ticket take 3                # Ticket übernehmen
/ticket close 3               # Ticket schließen
/ticket reopen 3              # wieder öffnen
```

> Es gibt noch weitere Commands. Wer `/help --all` tippt, findet sie.

---

## Roadmap

### Phase 1 — Fundament
- [ ] Relay Server (WebSocket, asyncio, Channel-Routing)
- [ ] Event-Protokoll definieren (Message, Join, Leave, Snippet, Edit)
- [ ] Ed25519 Keypair-Generierung & Event-Signierung
- [ ] Offline-Buffer mit TTL

### Phase 2 — Client
- [ ] Textual TUI-Grundstruktur (Channel-Tabs, Message-Stream, Input)
- [ ] prompt_toolkit Input mit Fish-Suggestions
- [ ] tree-sitter Live-Highlighting im Input
- [ ] textual-web / xterm.js Deployment

### Phase 3 — Snippets
- [ ] Code-Block-Erkennung beim Senden
- [ ] Auto-Save als lokales Snippet + Metadaten-Index
- [ ] `/snippets`, `/pull`, `/open` Commands
- [ ] CRDT-Editor (Automerge) via `/open`

### Phase 4 — Embeds & AI
- [ ] OG-Fetch im Relay (URL-Embeds)
- [ ] Sixel/chafa Bild-Rendering (SSH)
- [ ] HTML iframe Preview (Browser)
- [ ] First-Run Wizard (Alias + Keypair + Claude Auth + Gemini Auth)
- [ ] `/ask` mit `--with` Snippet-Kontext
- [ ] AI Ghost-Text im Code-Input (Tab/Shift+Tab)

### Phase 5 — Deployment
- [ ] `install.sh` (One-Line-Installer)
- [ ] Cloudflare HTTPS Setup
- [ ] systemd Service für Relay
- [ ] `/invite` + Invite-only Channels

---

## Inspiration

- [WorkFlowShell](https://github.com/sambakura/WorkFlowShell) — Terminal-Chat auf shared tmux/zsh, die DNA dieses Projekts
- [ssh-chat](https://github.com/shazow/ssh-chat) — SSH-basierter Chat, Beweis dass das geht
- [Nostr](https://nostr.com) — dezentrales Event-Protokoll, Keypair-Identität
- [Zed](https://zed.dev) — kollaborativer Editor mit Chat, Inspiration für CRDT-Integration
- [Obsidian](https://obsidian.md) — Snippets als lebendige Markdown-Files, alles lokal
- [Textual](https://textual.textualize.io) — TUI-Framework das Terminal und Browser kann

---

## Status

> **Konzept & Architektur — Phase 1 startet**

Dieses Repository enthält aktuell die Architektur-Dokumentation.
Der Aufbau beginnt mit dem Relay-Server (`relay/server.py`).

---

*TheUltimateChat — weil WhatsApp-Gruppen keine Slash-Commands haben.*
