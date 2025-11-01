"""
Launch script for Surebet Accounting System Streamlit app.

This script ensures the project root is in the Python path so that
'src' module imports work correctly in all pages.
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

print(f"✅ Added to Python path: {project_root}")
print(f"✅ Current sys.path: {sys.path[:3]}...")

# Now run Streamlit
if __name__ == "__main__":
    import streamlit.web.cli as stcli

    # Run the main app
    sys.argv = [
        "streamlit",
        "run",
        str(project_root / "src" / "ui" / "app.py"),
        "--server.port=8501",
        "--server.headless=true",
    ]

    print("🚀 Starting Streamlit app...")
    sys.exit(stcli.main())
