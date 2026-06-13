"""SysDock core: the shared, hardened foundation every surface builds on.

This package holds the audited subprocess helper, capability detection,
structured logging, and the error taxonomy. Everything platform-specific must
go through here so the TUI, web server, and native wrapper share one core.
"""
