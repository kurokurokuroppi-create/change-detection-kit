"""watchkit/__main__.py — CLI entry point.

Usage::

    python -m watchkit run       --app <name>  [--apps-dir <dir>] [--log-level <level>]
    python -m watchkit serve     --app <name>  [--apps-dir <dir>] [--log-level <level>]
    python -m watchkit dashboard --app <name>  [--apps-dir <dir>] [--output <file>]

``--app`` is the base name of the JSON config file (without ``.json``) in
``--apps-dir`` (default: ``apps/``).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )


def _resolve_app_config(app_name: str, apps_dir: str) -> Path:
    """Resolve the config path; raises SystemExit with a helpful message."""
    path = Path(apps_dir) / f"{app_name}.json"
    if not path.exists():
        # Try current directory as fallback
        fallback = Path(f"{app_name}.json")
        if fallback.exists():
            return fallback
        print(f"Error: app config not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def cmd_run(args: argparse.Namespace) -> None:
    """Poll all sources once and exit."""
    from watchkit.config import load_config
    from watchkit.runner import poll_app_once

    cfg = load_config(_resolve_app_config(args.app, args.apps_dir))
    n = poll_app_once(cfg)
    print(f"Run complete for '{cfg.app}': {n} event(s) detected.")


def cmd_serve(args: argparse.Namespace) -> None:
    """Run the scheduler loop (blocks until Ctrl-C)."""
    from watchkit.config import load_config
    from watchkit.runner import serve_app

    cfg = load_config(_resolve_app_config(args.app, args.apps_dir))
    serve_app(cfg)


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Generate a static HTML status board."""
    from watchkit.config import load_config
    from watchkit.dashboard import generate_dashboard

    cfg = load_config(_resolve_app_config(args.app, args.apps_dir))
    output = getattr(args, "output", None)
    generate_dashboard(cfg, output_path=output)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="watchkit",
        description="Change Detection Kit — watch sources, detect changes, notify in Japanese.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    p_run = subparsers.add_parser("run", help="Poll all sources once and exit.")
    p_run.add_argument("--app", required=True, help="App name (config base name).")
    p_run.add_argument("--apps-dir", default="apps", help="Directory containing app JSON files.")
    p_run.set_defaults(func=cmd_run)

    # --- serve ---
    p_serve = subparsers.add_parser("serve", help="Run scheduler loop (blocks).")
    p_serve.add_argument("--app", required=True, help="App name (config base name).")
    p_serve.add_argument("--apps-dir", default="apps", help="Directory containing app JSON files.")
    p_serve.set_defaults(func=cmd_serve)

    # --- dashboard ---
    p_dash = subparsers.add_parser("dashboard", help="Generate static HTML status board.")
    p_dash.add_argument("--app", required=True, help="App name (config base name).")
    p_dash.add_argument("--apps-dir", default="apps", help="Directory containing app JSON files.")
    p_dash.add_argument("--output", default=None,
                        help="Output HTML file path (default: state/<app>.html).")
    p_dash.set_defaults(func=cmd_dash)

    args = parser.parse_args()
    _setup_logging(args.log_level)

    # Dispatch
    args.func(args)


# Fix: cmd_dash was referenced before being assigned (aliasing after definition)
def cmd_dash(args: argparse.Namespace) -> None:
    cmd_dashboard(args)


if __name__ == "__main__":
    main()
