"""Entry point: the GUI by default, or command-line mode with --scan / --list-devices."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    from . import cli

    if cli.is_cli(argv):
        sys.exit(cli.main(argv))
    from .gui.app import run_gui

    sys.exit(run_gui())


if __name__ == "__main__":
    main()
