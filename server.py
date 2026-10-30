#!/usr/bin/env python3
"""Etsy POD Forge - Root Server Launcher
Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
100% Python Standard Library — Zero External Dependencies.
"""
import sys
from pathlib import Path
import argparse

src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from etsy_pod_forge.server import ForgeServer

def main():
    parser = argparse.ArgumentParser(description="Etsy POD Forge Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8107, help="Port to bind to")
    args = parser.parse_args()

    public_dir = str(Path(__file__).resolve().parent / "public")
    server = ForgeServer(host=args.host, port=args.port, public_dir=public_dir)
    server.start(block=True)

if __name__ == "__main__":
    main()
