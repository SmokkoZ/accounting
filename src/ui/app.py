"""
Surebet Accounting System - Main Streamlit Application

A web-based interface for managing surebet accounting, including bet ingestion,
verification, settlement, and ledger management.
"""

import streamlit as st
from datetime import datetime

# Configure page settings
st.set_page_config(
    page_title="Surebet Accounting System",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Main application entry point"""
    # Header
    st.title("💰 Surebet Accounting System")
    st.markdown("---")

    # Sidebar navigation
    st.sidebar.title("Navigation")

    page = st.sidebar.selectbox(
        "Select a page:",
        [
            "Dashboard",
            "Associate Operations Hub",
            "Incoming Bets",
            "Surebets",
            "Settlement",
            "Reconciliation",
            "Export",
            "Statements",
        ],
    )

    # Page content based on selection
    if page == "Dashboard":
        st.header("Dashboard")
        st.info("Dashboard page - To be implemented")

    elif page == "Associate Operations Hub":
        # Import and render the associate operations page
        try:
            import sys
            import os
            
            # Add pages directory to path
            current_dir = os.path.dirname(__file__)
            pages_dir = os.path.join(current_dir, 'pages')
            if pages_dir not in sys.path:
                sys.path.insert(0, pages_dir)
            
            # Import and run the associate operations page
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "associate_operations", 
                os.path.join(pages_dir, "8_associate_operations.py")
            )
            associate_ops = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(associate_ops)
            
            # Call the main function if it exists
            if hasattr(associate_ops, 'main'):
                associate_ops.main()
            else:
                st.error("Associate Operations Hub page structure incorrect")
                
        except ImportError as e:
            st.error(f"Associate Operations Hub page not found: {e}")
        except Exception as e:
            st.error(f"Error loading Associate Operations Hub: {e}")

    elif page == "Incoming Bets":
        st.header("Incoming Bets")
        st.info("Incoming Bets page - To be implemented")

    elif page == "Surebets":
        st.header("Surebets")
        st.info("Surebets page - To be implemented")

    elif page == "Settlement":
        st.header("Settlement")
        st.info("Settlement page - To be implemented")

    elif page == "Reconciliation":
        st.header("Reconciliation")
        st.info("Reconciliation page - To be implemented")

    elif page == "Export":
        st.header("Export")
        st.info("Export page - To be implemented")

    elif page == "Statements":
        st.header("Statements")
        st.info("Statements page - To be implemented")

    # Footer
    st.markdown("---")
    st.markdown(
        f"© 2025 Surebet Accounting System | Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


if __name__ == "__main__":
    main()
