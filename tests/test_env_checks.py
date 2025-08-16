"""Tests for environment checks."""

import os
import sys
from unittest.mock import patch

from trailblazer.env_checks import (
    assert_virtualenv_on_macos,
    _is_in_virtualenv,
    get_venv_info,
)


class TestVirtualenvDetection:
    """Test virtual environment detection logic."""

    def test_is_in_virtualenv_with_virtual_env(self):
        """Test detection with VIRTUAL_ENV environment variable."""
        with patch.dict(os.environ, {"VIRTUAL_ENV": "/path/to/venv"}):
            assert _is_in_virtualenv() is True

    def test_is_in_virtualenv_with_poetry(self):
        """Test detection with Poetry environment."""
        with patch.dict(os.environ, {"POETRY_ACTIVE": "1"}):
            assert _is_in_virtualenv() is True

    def test_is_in_virtualenv_with_conda(self):
        """Test detection with Conda environment."""
        with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "myenv"}):
            assert _is_in_virtualenv() is True

    def test_is_in_virtualenv_with_base_prefix(self):
        """Test detection with sys.prefix != sys.base_prefix."""
        with (
            patch.object(sys, "prefix", "/venv/path"),
            patch.object(sys, "base_prefix", "/system/python"),
        ):
            assert _is_in_virtualenv() is True

    def test_is_in_virtualenv_with_real_prefix(self):
        """Test detection with sys.real_prefix (older virtualenv)."""
        with patch.object(sys, "real_prefix", "/system/python", create=True):
            assert _is_in_virtualenv() is True

    def test_is_in_virtualenv_system_python(self):
        """Test detection returns False for system Python."""
        # Clear all environment variables that would indicate venv
        env_clear = {
            "VIRTUAL_ENV": None,
            "POETRY_ACTIVE": None,
            "CONDA_DEFAULT_ENV": None,
        }

        with (
            patch.dict(os.environ, env_clear, clear=False),
            patch.object(sys, "prefix", "/usr/bin/python"),
            patch.object(sys, "base_prefix", "/usr/bin/python"),
            patch.object(sys, "real_prefix", None, create=True),
        ):
            # Remove real_prefix if it exists
            if hasattr(sys, "real_prefix"):
                delattr(sys, "real_prefix")
            assert _is_in_virtualenv() is False


class TestMacOSVenvEnforcement:
    """Test macOS virtual environment enforcement."""

    def test_assert_virtualenv_bypass_with_env_var(self):
        """Test bypass with TB_ALLOW_SYSTEM_PYTHON=1."""
        with (
            patch.dict(os.environ, {"TB_ALLOW_SYSTEM_PYTHON": "1"}),
            patch("platform.system", return_value="Darwin"),
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=False
            ),
        ):
            # Should not raise
            assert_virtualenv_on_macos()

    def test_assert_virtualenv_non_macos(self):
        """Test no enforcement on non-macOS systems."""
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=False
            ),
        ):
            # Should not raise
            assert_virtualenv_on_macos()

    def test_assert_virtualenv_macos_with_venv(self):
        """Test success on macOS with virtual environment."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
        ):
            # Should not raise
            assert_virtualenv_on_macos()

    def test_assert_virtualenv_macos_system_python_fails(self):
        """Test failure on macOS with system Python."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=False
            ),
            patch("sys.exit") as mock_exit,
        ):
            assert_virtualenv_on_macos()
            mock_exit.assert_called_once_with(1)


class TestVenvInfo:
    """Test virtual environment information gathering."""

    def test_get_venv_info_no_venv(self):
        """Test venv info when not in virtual environment."""
        with patch(
            "trailblazer.env_checks._is_in_virtualenv", return_value=False
        ):
            assert get_venv_info() is None

    def test_get_venv_info_virtual_env(self):
        """Test venv info with VIRTUAL_ENV."""
        with (
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
            patch.dict(os.environ, {"VIRTUAL_ENV": "/path/to/venv"}),
        ):
            info = get_venv_info()
            assert info == "venv: /path/to/venv"

    def test_get_venv_info_poetry(self):
        """Test venv info with Poetry."""
        with (
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
            patch.dict(
                os.environ,
                {"POETRY_ACTIVE": "1", "POETRY_VENV_PATH": "/poetry/venv"},
            ),
        ):
            info = get_venv_info()
            assert info == "poetry: /poetry/venv"

    def test_get_venv_info_conda(self):
        """Test venv info with Conda."""
        with (
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
            patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "myenv"}),
        ):
            info = get_venv_info()
            assert info == "conda: myenv"

    def test_get_venv_info_base_prefix(self):
        """Test venv info with base_prefix detection."""
        env_clear = {
            "VIRTUAL_ENV": None,
            "POETRY_ACTIVE": None,
            "CONDA_DEFAULT_ENV": None,
        }

        with (
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
            patch.dict(os.environ, env_clear, clear=False),
            patch.object(sys, "prefix", "/venv/path"),
            patch.object(sys, "base_prefix", "/system/python"),
        ):
            info = get_venv_info()
            assert info == "virtualenv: /venv/path"
