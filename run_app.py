"""
Launch script for Surebet Accounting System Streamlit app.

This script ensures the project root is in the Python path so that
'src' module imports work correctly in all pages.
"""

import sys
import socket
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

print(f"✅ Added to Python path: {project_root}")
print(f"✅ Current sys.path: {sys.path[:3]}...")

def find_available_port(start_port=8501, max_tries=10):
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available ports found in range {start_port}-{start_port + max_tries}")

# Now run Streamlit
if __name__ == "__main__":
    import streamlit.web.cli as stcli

    # Find an available port
    try:
        port = find_available_port()
        print(f"🔍 Using port {port}")
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Run the main app
    sys.argv = [
        "streamlit",
        "run",
        str(project_root / "src" / "ui" / "app.py"),
        f"--server.port={port}",
        "--server.headless=true",
    ]

    print(f"🚀 Starting Streamlit app on port {port}...")
    print(f"🌐 App will be available at: http://localhost:{port}")
    sys.exit(stcli.main())
