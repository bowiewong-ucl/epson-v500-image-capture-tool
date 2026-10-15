"""PyInstaller entry script (the package's __main__ can't be used directly: it uses relative imports)."""

from v500capture.__main__ import main

if __name__ == "__main__":
    main()
