"""
Manual bet upload component for Streamlit UI.

This module provides a Streamlit component for uploading bet screenshots manually,
with associate/bookmaker selection, file validation, and OCR processing.
"""

import sqlite3
from typing import Optional, Any

import streamlit as st
import structlog

from src.core.database import get_db_connection
from src.core.config import Config
from src.services.bet_ingestion import BetIngestionService
from src.utils.file_storage import save_screenshot, validate_file_size, validate_file_type
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger()


def render_manual_upload_panel() -> None:
    """
    Render the manual bet upload panel in Streamlit.

    Provides:
    - File uploader (PNG, JPG, JPEG)
    - Associate selection dropdown
    - Bookmaker selection dropdown (filtered by associate)
    - Optional note field
    - Submit button with validation
    """
    st.subheader("Upload Manual Bet")
    st.caption("For screenshots from WhatsApp, camera photos, or other sources")

    # Database connection
    db = get_db_connection()
    st.caption(f"DB path: `{Config.DB_PATH}`")

    # Associate selection (outside the form so it refreshes instantly)
    associates = db.execute(
        """
        SELECT id, display_alias
        FROM associates
        ORDER BY display_alias
        """
    ).fetchall()

    if not associates:
        st.error("No associates found. Please add associates to the database first.")
        return

    associate_options = {row["display_alias"]: row["id"] for row in associates}
    selected_associate_name = st.selectbox(
        "Associate",
        options=list(associate_options.keys()),
        help="Who placed this bet?",
        key="manual_upload_associate",
    )
    selected_associate_id = associate_options[selected_associate_name]
    st.caption(f"Associate: {selected_associate_name} (id={selected_associate_id})")

    # Bookmaker selection filtered by selected associate
    bookmakers = db.execute(
        """
        SELECT id, bookmaker_name
        FROM bookmakers
        WHERE associate_id = ?
        AND is_active = 1
        ORDER BY bookmaker_name
        """,
        (selected_associate_id,),
    ).fetchall()

    bookmaker_options = {row["bookmaker_name"]: row["id"] for row in bookmakers} if bookmakers else {}
    names = ", ".join(sorted(bookmaker_options.keys())) if bookmaker_options else "(none)"
    st.caption(f"Bookmakers for {selected_associate_name}: {names}")

    selected_bookmaker_name = st.selectbox(
        "Bookmaker",
        options=(list(bookmaker_options.keys()) if bookmaker_options else ["(None available)"]),
        help="Which bookmaker account?",
        key=f"manual_upload_bookmaker_{selected_associate_id}",
    )
    selected_bookmaker_id = bookmaker_options.get(selected_bookmaker_name)

    # Submission form for file + note
    with st.form("manual_upload_form"):
        uploaded_files = st.file_uploader(
            "Choose screenshot file",
            type=["png", "jpg", "jpeg"],
            help="Max file size: 10MB. Supported formats: PNG, JPG, JPEG",
            accept_multiple_files=True,
        )

        note = st.text_area(
            "Note (optional)",
            placeholder="e.g., 'From WhatsApp group', 'Sent via email'",
            max_chars=500,
            help="Add any context about this bet upload",
        )

        submitted = st.form_submit_button("Import & OCR", type="primary")

        if submitted:
            if not uploaded_files:
                st.error("Please upload at least one screenshot.")
                return

            # Streamlit returns a list when multiple files are accepted; coerce for safety.
            files_to_process = (
                list(uploaded_files)
                if isinstance(uploaded_files, (list, tuple))
                else [uploaded_files]
            )

            successful_uploads = 0

            for file_obj in files_to_process:
                st.markdown(f"**Processing:** `{file_obj.name}`")
                if _process_manual_upload(
                    uploaded_file=file_obj,
                    associate_id=selected_associate_id,
                    associate_name=selected_associate_name,
                    bookmaker_id=selected_bookmaker_id,
                    bookmaker_name=selected_bookmaker_name,
                    note=note,
                    db=db,
                    filename=file_obj.name,
                ):
                    successful_uploads += 1

            if successful_uploads and successful_uploads == len(files_to_process):
                st.success(f"Processed {successful_uploads} screenshot(s) successfully.")
            elif successful_uploads:
                st.warning(
                    f"Processed {successful_uploads} out of {len(files_to_process)} screenshot(s). "
                    "Review any errors above."
                )


def _process_manual_upload(
    uploaded_file: Any,
    associate_id: int,
    associate_name: str,
    bookmaker_id: Optional[int],
    bookmaker_name: str,
    note: str,
    db: sqlite3.Connection,
    filename: Optional[str] = None,
) -> bool:
    """
    Process manual file upload with validation and OCR extraction.
    """
    display_name = filename or (uploaded_file.name if uploaded_file else "uploaded file")

    # Validation: File selected
    if not uploaded_file:
        st.error("Please select a file to upload")
        return False

    # Validation: Bookmaker selected
    if not bookmaker_id:
        st.error(f"Please select a valid bookmaker before importing `{display_name}`.")
        return False

    # Read file bytes
    file_bytes = uploaded_file.read()

    # Validation: File size
    if not validate_file_size(file_bytes, max_size_mb=10):
        st.error(f"File `{display_name}` exceeds the 10MB limit. Please upload a smaller image.")
        return False

    # Validation: File type
    if not validate_file_type(uploaded_file.name):
        st.error(f"File `{display_name}` is not PNG, JPG, or JPEG.")
        return False

    # Process upload
    try:
        with st.spinner("Saving screenshot..."):
            # Save screenshot to disk
            abs_path, rel_path = save_screenshot(
                file_bytes, associate_name, bookmaker_name, source="manual_upload"
            )

            logger.info(
                "screenshot_saved",
                path=rel_path,
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
            )

        with st.spinner("Creating bet record..."):
            # Create bet record in database
            # Determine associate's home currency to set on bet
            assoc_cur_row = db.execute(
                "SELECT home_currency FROM associates WHERE id = ?",
                (associate_id,),
            ).fetchone()
            assoc_currency = assoc_cur_row[0] if assoc_cur_row and assoc_cur_row[0] else "EUR"

            cursor = db.execute(
                """
                INSERT INTO bets (
                    associate_id,
                    bookmaker_id,
                    status,
                    stake_eur,
                    odds,
                    currency,
                    screenshot_path,
                    ingestion_source,
                    created_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    associate_id,
                    bookmaker_id,
                    "incoming",
                    "0.0",  # Will be updated by OCR
                    "0.0",  # Will be updated by OCR
                    assoc_currency,  # Inherit associate currency
                    rel_path,
                    "manual_upload",
                    utc_now_iso(),
                    utc_now_iso(),
                ),
            )
            db.commit()
            bet_id = cursor.lastrowid

            if bet_id is None:
                st.error("Failed to create bet record")
                logger.error("bet_creation_failed", error="lastrowid is None")
                return

            # Add operator note if provided
            if note and note.strip():
                db.execute(
                    """
                    INSERT INTO verification_audit (
                        bet_id,
                        actor,
                        action,
                        notes,
                        created_at_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (bet_id, "operator", "CREATED", note.strip(), utc_now_iso()),
                )
                db.commit()

            logger.info(
                "bet_created",
                bet_id=bet_id,
                ingestion_source="manual_upload",
                has_note=bool(note and note.strip()),
            )

        with st.spinner("Running OCR extraction..."):
            # Run OCR extraction
            ingestion_service = BetIngestionService(db)
            extraction_success = ingestion_service.process_bet_extraction(bet_id)

            if extraction_success:
                # Fetch updated confidence score
                cursor = db.execute(
                    """
                    SELECT normalization_confidence, is_multi
                    FROM bets
                    WHERE id = ?
                    """,
                    (bet_id,),
                )
                bet_data = cursor.fetchone()
                confidence = bet_data["normalization_confidence"] if bet_data else None
                is_multi = bet_data["is_multi"] if bet_data else False

                # Display success message
                st.success(f"Bet #{bet_id} added to review queue!")

                # Display confidence
                if confidence:
                    confidence_float = float(confidence)
                    if confidence_float >= 0.8:
                        st.info(f"High confidence: {confidence_float:.0%}")
                    elif confidence_float >= 0.5:
                        st.warning(f"Medium confidence: {confidence_float:.0%}")
                    else:
                        st.error(f"Low confidence: {confidence_float:.0%}")

                # Display multi-leg warning
                if is_multi:
                    st.error("Accumulator detected — not supported by system")

            else:
                st.warning(
                    f"Bet #{bet_id} created but OCR extraction failed. "
                    "Please review and enter data manually."
                )
            return True

    except Exception as e:
        logger.error("manual_upload_failed", error=str(e), exc_info=True)
        st.error(f"Error processing upload: {str(e)}")
        st.exception(e)
        return False
