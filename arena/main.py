"""
The Arena
Application entry point
"""

import os

from arena.paths import ARENA_ROOT


def main():
    """Main entry point for the application."""
    # The engine reads data/ and assets/ relative to cwd; anchor to the package root
    # so launching from anywhere (a shortcut, a different folder) still works.
    os.chdir(ARENA_ROOT)
    from arena.gui.app import App
    app = App()
    app.run()


if __name__ == "__main__":
    main()
