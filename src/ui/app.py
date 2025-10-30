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
