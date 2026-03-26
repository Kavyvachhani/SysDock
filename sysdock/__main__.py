"""Allow running as: python3 -m sysdock [command]
Running without a command argument launches the dashboard automatically.
"""
from sysdock.cli import main

if __name__ == "__main__":
    main()
