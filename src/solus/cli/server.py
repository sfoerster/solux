from __future__ import annotations

import argparse
import sys
from importlib.util import find_spec

from ..config import ConfigError, load_config
from ..serve import run_serve


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if getattr(getattr(config, "security", None), "oidc_require_auth", False):
        if find_spec("jwt") is None:
            print(
                "ERROR: oidc_require_auth is enabled but the 'solus[oidc]' extra is not installed.\n"
                "       Run: pip install 'solus[oidc]'",
                file=sys.stderr,
            )
            return 1

    return run_serve(
        cache_dir=config.paths.cache_dir,
        host=args.host,
        port=args.port,
        yt_dlp_binary=config.yt_dlp.binary,
        config=config,
        workflows_dir=config.workflows_dir,
    )
