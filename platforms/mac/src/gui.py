import os
import sys
import threading
import time
from datetime import datetime
from rich.console import Console
from rich.layout import Layout
from bottle import Bottle, run, template, static_file
import webview

# Import collectors
from sysdock.collectors import (
    system as _sys, disk as _disk, processes as _proc,
    network as _net, docker_collector as _docker, security as _sec,
)
from sysdock.display import dashboard

app = Bottle()
console = Console(width=120, height=40, force_terminal=True, record=True)

# Shared state
class GlobalState:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()
        self.running = True

state = GlobalState()

def update_data():
    while state.running:
        try:
            new_data = {
                "system":    _sys.collect_all(),
                "disk":      _disk.collect_all(),
                "processes": _proc.collect_all(),
                "network":   _net.collect_all(),
                "docker":    _docker.collect_all(),
                "security":  _sec.collect_all(),
            }
            with state.lock:
                state.data = new_data
        except Exception as e:
            print(f"Error in data collection: {e}")
        time.sleep(3)

@app.route('/')
def index():
    with state.lock:
        if not state.data:
            return "<html><body style='background:#121212;color:white;font-family:monospace;'>Initialising SysDock...</body></html>"
        
        # Create a mock state object that dashboard._render expects
        class MockState:
            def snapshot(self):
                return state.data
        
        # Use dashboard's internal render logic
        layout = dashboard._render(MockState())
        
        console.clear()
        console.print(layout)
        html = console.export_html(inline_styles=True)
        # Add auto-refresh meta tag
        return f"<html><head><meta http-equiv='refresh' content='3'></head><body style='background:#0c0c0c; margin:0; overflow:hidden;'>{html}</body></html>"

def run_server():
    run(app, host='localhost', port=8443, quiet=True)

def start_gui():
    # Start background data collection
    threading.Thread(target=update_data, daemon=True).start()
    # Start local web server
    threading.Thread(target=run_server, daemon=True).start()
    
    # Create window
    window = webview.create_window(
        'SysDock Monitoring',
        'http://localhost:8443',
        width=1100,
        height=900,
        background_color='#0c0c0c'
    )
    
    webview.start()
    state.running = False

if __name__ == '__main__':
    start_gui()
