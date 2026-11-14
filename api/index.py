"""
Vercel Python Serverless Function entrypoint.
"""

import sys
from pathlib import Path

# Ensure root project modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server_handler import HealthspanHandler


class handler(HealthspanHandler):
    serve_static = False
