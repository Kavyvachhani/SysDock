"""Allow running as: python3 -m infravision_agent [command]
Running without a command argument launches the dashboard automatically.
"""
from infravision_agent.cli import main

if __name__ == "__main__":
    main()
