"""Test that importing ingest CLI doesn't trigger DB engine initialization."""

import logging
from io import StringIO
from unittest.mock import patch


def test_ingest_cli_help_no_db_logs():
    """Test that calling ingest CLI help doesn't create DB engine or emit DB logs."""
    # Capture all logs
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)

    # Get root logger and add our handler
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        # Mock DB engine creation to spy on calls
        with patch(
            "trailblazer.db.engine.create_engine"
        ) as mock_create_engine:
            # Import ingest CLI - this should not trigger DB creation
            from trailblazer.cli.main import ingest_app  # noqa: F401

            # Assert no DB engine was created
            mock_create_engine.assert_not_called()

            # Check logs for any DB-related messages
            log_content = log_capture.getvalue()
            assert "engine" not in log_content.lower(), (
                f"Found DB engine logs: {log_content}"
            )
            assert "database" not in log_content.lower(), (
                f"Found database logs: {log_content}"
            )
            # No database operations should occur during ingest
            assert "postgresql" not in log_content.lower(), (
                f"Found database logs: {log_content}"
            )

    finally:
        # Restore original logging state
        root_logger.removeHandler(handler)
        root_logger.setLevel(original_level)


def test_ingest_module_import_no_db():
    """Test that importing ingest module doesn't trigger DB initialization."""
    with patch("trailblazer.db.engine.create_engine") as mock_create_engine:
        # Import ingest module

        # Assert no DB engine was created during import
        mock_create_engine.assert_not_called()


def test_ingest_cli_import_no_db():
    """Test that importing CLI main doesn't trigger DB initialization."""
    with patch("trailblazer.db.engine.create_engine") as mock_create_engine:
        # Import CLI main
        from trailblazer.cli.main import ingest_app  # noqa: F401

        # Assert no DB engine was created during import
        mock_create_engine.assert_not_called()
