#!/usr/bin/env python3
"""Entry point: python chat.py [relay_url]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client.app import ChatApp, DEFAULT_RELAY

relay = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RELAY
ChatApp(relay_url=relay).run()
