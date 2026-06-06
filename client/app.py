"""TheUltimateChat — Textual TUI client (Phase 2)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import websockets
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message as TxtMessage
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, RichLog, Static

sys.path.insert(0, str(Path(__file__).parent.parent))
from client.keypair import load_or_create_keypair
from relay.crypto import box_decrypt, box_encrypt, sign_event_id
from relay.protocol import Kind, compute_id, inbox_key, p_tag_pubkey, get_channel

# ── defaults ────────────────────────────────────────────────────────────────
DEFAULT_RELAY = "ws://127.0.0.1:8765"
DEFAULT_CHANNELS = ["#general"]
HISTORY_LINES = 500

# ── helpers ──────────────────────────────────────────────────────────────────

def ts() -> int:
    return int(time.time())


def fmt_time(unix: int) -> str:
    return datetime.fromtimestamp(unix).strftime("%H:%M")


def short(pubkey: str) -> str:
    return pubkey[:8]


def build_event(privkey: str, pubkey: str, kind: int, content: str,
                channel: str | None = None, recipient: str | None = None) -> dict:
    tags: list = []
    if channel:
        tags.append(["channel", channel])
    if recipient:
        tags.append(["p", recipient])
    ev = {"pubkey": pubkey, "created_at": ts(), "kind": kind, "tags": tags, "content": content}
    ev["id"] = compute_id(ev)
    ev["sig"] = sign_event_id(ev["id"], privkey)
    return ev


# ── Textual messages (worker → UI) ──────────────────────────────────────────

class ChatLine(TxtMessage):
    def __init__(self, view: str, sender: str, text: str, timestamp: int):
        super().__init__()
        self.view = view        # "#general" or "dm:<pubkey>"
        self.sender = sender
        self.text = text
        self.timestamp = timestamp


class StatusLine(TxtMessage):
    def __init__(self, text: str):
        super().__init__()
        self.text = text


class SidebarUpdate(TxtMessage):
    pass


# ── Sidebar widget ────────────────────────────────────────────────────────────

class Sidebar(Static):
    DEFAULT_CSS = """
    Sidebar {
        width: 22;
        height: 100%;
        border-right: solid $primary-darken-2;
        padding: 1 1;
        color: $text-muted;
    }
    """

    def __init__(self, app_ref: "ChatApp"):
        super().__init__()
        self._app = app_ref

    def refresh_view(self) -> None:
        a = self._app
        lines: list[str] = []

        lines.append(f"[bold]{short(a.pubkey)}[/bold]")
        lines.append("")
        lines.append("[bold dim]CHANNELS[/bold dim]")
        for ch in sorted(a.channels):
            unread = ch in a.unread
            active = ch == a.active_view
            dot = "[green]●[/green] " if unread else "  "
            name = f"[bold cyan]{ch}[/bold cyan]" if active else ch
            lines.append(f" {dot}{name}")

        lines.append("")
        lines.append("[bold dim]DIRECT[/bold dim]")
        for pk in sorted(a.dm_partners):
            view_key = f"dm:{pk}"
            unread = view_key in a.unread
            active = view_key == a.active_view
            dot = "[green]●[/green] " if unread else "  "
            name = f"[bold cyan]{short(pk)}[/bold cyan]" if active else short(pk)
            lines.append(f" {dot}{name}")

        self.update("\n".join(lines))


# ── Main App ──────────────────────────────────────────────────────────────────

class ChatApp(App):
    TITLE = "TheUltimateChat"
    CSS = """
    Screen {
        layout: horizontal;
    }
    #chat-col {
        width: 1fr;
        layout: vertical;
    }
    #chat-log {
        height: 1fr;
        border: none;
        padding: 0 1;
    }
    #status {
        height: 1;
        background: $primary-darken-3;
        color: $text-muted;
        padding: 0 1;
    }
    #input {
        height: 3;
        border-top: solid $primary-darken-2;
    }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit"),
    ]

    # reactive state
    channels: reactive[list[str]] = reactive(list, always_update=True)
    dm_partners: reactive[set[str]] = reactive(set, always_update=True)
    active_view: reactive[str] = reactive("#general")
    unread: reactive[set[str]] = reactive(set, always_update=True)

    def __init__(self, relay_url: str = DEFAULT_RELAY):
        super().__init__()
        self.relay_url = relay_url
        self.privkey, self.pubkey = load_or_create_keypair()
        self.channels = list(DEFAULT_CHANNELS)
        self.dm_partners: set[str] = set()
        self.active_view = DEFAULT_CHANNELS[0]
        self.unread: set[str] = set()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._sub_seq = 0
        # local message store: view_key → [(sender, text, ts)]
        self._messages: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        # track pubkeys seen (for DM lookup by prefix)
        self._known_pubkeys: set[str] = set()
        # locally stored sent DMs: partner_pubkey → [(text, ts)]
        self._sent_dms: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        yield Header(show_clock=True)
        yield Sidebar(self, id="sidebar")
        with Vertical(id="chat-col"):
            yield RichLog(id="chat-log", highlight=True, markup=True, max_lines=HISTORY_LINES)
            yield Static("", id="status")
            yield Input(placeholder="  › message  |  /join #chan  /msg <pubkey>  /help", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self._ws_worker()
        self._refresh_sidebar()
        self._set_status(f"connecting to {self.relay_url}…")

    # ── Worker: WebSocket loop ────────────────────────────────────────────────

    @work(exclusive=True, thread=False)
    async def _ws_worker(self) -> None:
        retry = 2
        while True:
            try:
                async with websockets.connect(self.relay_url) as ws:
                    self._ws = ws
                    self.post_message(StatusLine(f"connected  ·  you: {short(self.pubkey)}"))
                    # Subscribe to DM inbox + default channels
                    await self._subscribe(ws, inbox_key(self.pubkey))
                    for ch in self.channels:
                        await self._subscribe(ws, ch)
                    async for raw in ws:
                        await self._handle_relay(json.loads(raw))
            except Exception as exc:
                self._ws = None
                self.post_message(StatusLine(f"disconnected: {exc}  — retry in {retry}s"))
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)

    async def _subscribe(self, ws, channel: str) -> None:
        self._sub_seq += 1
        since = ts() - 7 * 24 * 3600
        await ws.send(json.dumps(["REQ", f"s{self._sub_seq}", {"channel": channel, "since": since}]))

    async def _handle_relay(self, msg: list) -> None:
        if msg[0] != "EVENT":
            return
        _, _sub_id, event = msg
        kind = event.get("kind")
        sender = event.get("pubkey", "")
        self._known_pubkeys.add(sender)
        content = event.get("content", "")
        when = event.get("created_at", ts())

        if kind == Kind.WHISPER:
            # DM destined to our inbox
            try:
                plaintext = box_decrypt(content, self.privkey, sender)
            except Exception:
                plaintext = f"[decryption failed]  {content[:32]}…"
            view_key = f"dm:{sender}"
            if sender not in self.dm_partners:
                self.dm_partners = self.dm_partners | {sender}
                self._refresh_sidebar()
            self.post_message(ChatLine(view_key, short(sender), plaintext, when))
        else:
            channel = get_channel(event)
            if not channel:
                return
            self.post_message(ChatLine(channel, short(sender), content, when))

    # ── UI event handlers ─────────────────────────────────────────────────────

    def on_chat_line(self, msg: ChatLine) -> None:
        self._messages[msg.view].append((msg.sender, msg.text, msg.timestamp))
        if msg.view == self.active_view:
            self._append_line(msg.sender, msg.text, msg.timestamp)
        else:
            self.unread = self.unread | {msg.view}
            self._refresh_sidebar()

    def on_status_line(self, msg: StatusLine) -> None:
        self._set_status(msg.text)

    def on_sidebar_update(self, _: SidebarUpdate) -> None:
        self._refresh_sidebar()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        self.query_one("#input", Input).value = ""
        if not raw:
            return
        if raw.startswith("/"):
            self._handle_command(raw)
        else:
            self._send_message(raw)

    # ── Commands ──────────────────────────────────────────────────────────────

    def _handle_command(self, raw: str) -> None:
        parts = raw.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/help":
            self._sys("Commands: /join #channel · /leave #channel · /msg <pubkey> · /switch #channel · /who · /quit")

        elif cmd == "/join" and len(parts) >= 2:
            ch = parts[1] if parts[1].startswith("#") else f"#{parts[1]}"
            if ch not in self.channels:
                self.channels = [*self.channels, ch]
                self._subscribe_now(ch)
                self._sys(f"joined {ch}")
            self._switch_view(ch)

        elif cmd == "/leave" and len(parts) >= 2:
            ch = parts[1] if parts[1].startswith("#") else f"#{parts[1]}"
            if ch in self.channels and ch != "#general":
                self.channels = [c for c in self.channels if c != ch]
                self._sys(f"left {ch}")
                self._switch_view("#general")
            else:
                self._sys("cannot leave #general")

        elif cmd == "/msg" and len(parts) >= 2:
            prefix = parts[1]
            match = [pk for pk in self._known_pubkeys if pk.startswith(prefix)]
            if not match:
                self._sys(f"unknown pubkey prefix '{prefix}' — they need to send a message first")
            elif len(match) > 1:
                self._sys(f"ambiguous prefix, matches: {', '.join(short(p) for p in match)}")
            else:
                pk = match[0]
                self.dm_partners = self.dm_partners | {pk}
                self._switch_view(f"dm:{pk}")
                self._refresh_sidebar()

        elif cmd == "/switch" and len(parts) >= 2:
            target = parts[1]
            if target in self.channels or target.startswith("dm:"):
                self._switch_view(target)
            else:
                self._sys(f"not subscribed to {target}")

        elif cmd == "/who":
            self._sys(f"your pubkey: {self.pubkey}")

        elif cmd in ("/quit", "/exit", "/q"):
            self.exit()

        else:
            self._sys(f"unknown command: {cmd}  — try /help")

    def _send_message(self, text: str) -> None:
        if self._ws is None:
            self._sys("not connected")
            return
        view = self.active_view
        if view.startswith("dm:"):
            partner_pubkey = view[3:]
            try:
                ciphertext = box_encrypt(text, self.privkey, partner_pubkey)
            except Exception as exc:
                self._sys(f"encryption error: {exc}")
                return
            ev = build_event(self.privkey, self.pubkey, Kind.WHISPER, ciphertext, recipient=partner_pubkey)
            # Store sent message locally (relay doesn't echo back to sender)
            self._messages[view].append((f"{short(self.pubkey)} →", text, ts()))
            self._append_line(f"[dim]{short(self.pubkey)} →[/dim]", text, ts())
        else:
            ev = build_event(self.privkey, self.pubkey, Kind.MESSAGE, text, channel=view)
        asyncio.get_event_loop().create_task(self._send_ws(ev))

    async def _send_ws(self, ev: dict) -> None:
        if self._ws:
            await self._ws.send(json.dumps(["EVENT", ev]))

    def _subscribe_now(self, channel: str) -> None:
        if self._ws:
            asyncio.get_event_loop().create_task(self._subscribe(self._ws, channel))

    # ── View management ───────────────────────────────────────────────────────

    def _switch_view(self, view: str) -> None:
        self.active_view = view
        self.unread = self.unread - {view}
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        for sender, text, when in self._messages.get(view, []):
            self._render_line(log, sender, text, when)
        self._set_status(f"{view}  ·  you: {short(self.pubkey)}")
        self._refresh_sidebar()

    def _append_line(self, sender: str, text: str, when: int) -> None:
        self._render_line(self.query_one("#chat-log", RichLog), sender, text, when)

    def _render_line(self, log: RichLog, sender: str, text: str, when: int) -> None:
        log.write(f"[dim]{fmt_time(when)}[/dim]  [bold]{sender}[/bold]  {text}")

    def _sys(self, text: str) -> None:
        self.query_one("#chat-log", RichLog).write(f"[dim]·[/dim]  [italic dim]{text}[/italic dim]")

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _refresh_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.refresh_view()
