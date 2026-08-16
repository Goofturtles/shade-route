"""Start the Shade Route server.

    python run.py                 # http://127.0.0.1:8000
    python run.py --port 8080     # somewhere else
    python run.py --reload        # auto-reload while developing
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Work from any current directory: `python /wherever/shade-route/run.py` should
# behave identically to running it from inside the repo.
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

import uvicorn  # noqa: E402  (imported after sys.path is fixed, deliberately)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Shade Route server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on file changes")
    args = parser.parse_args()

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"Shade Route -> http://{shown_host}:{args.port}")

    # Without reload_dirs, watchfiles walks the whole working directory —
    # including .venv and its thousands of files — and every edit costs seconds.
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(REPO_ROOT / "app"), str(REPO_ROOT / "web")] if args.reload else None,
    )


if __name__ == "__main__":
    main()
