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
        env_clear = {}
        for key in ["VIRTUAL_ENV", "POETRY_ACTIVE", "CONDA_DEFAULT_ENV"]:
            if key in os.environ:
                env_clear[key] = None

        with (
            patch.dict(os.environ, {}, clear=False),  # Don't change env vars
            patch.object(sys, "prefix", "/usr/bin/python"),
            patch.object(sys, "base_prefix", "/usr/bin/python"),
        ):
            # Temporarily remove environment variables that indicate venv
            original_env = {}
            for key in ["VIRTUAL_ENV", "POETRY_ACTIVE", "CONDA_DEFAULT_ENV"]:
                if key in os.environ:
                    original_env[key] = os.environ.pop(key)

            try:
                # Also ensure no real_prefix attribute
                real_prefix_existed = hasattr(sys, "real_prefix")
                if real_prefix_existed:
                    original_real_prefix = sys.real_prefix
                    delattr(sys, "real_prefix")

                try:
                    assert _is_in_virtualenv() is False
                finally:
                    # Restore real_prefix if it existed
                    if real_prefix_existed:
                        sys.real_prefix = original_real_prefix
            finally:
                # Restore environment variables
                for key, value in original_env.items():
                    os.environ[key] = value


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
        ):
            # Temporarily clear VIRTUAL_ENV and set Poetry env vars
            original_virtual_env = os.environ.get("VIRTUAL_ENV")
            if "VIRTUAL_ENV" in os.environ:
                del os.environ["VIRTUAL_ENV"]

            os.environ["POETRY_ACTIVE"] = "1"
            os.environ["POETRY_VENV_PATH"] = "/poetry/venv"

            try:
                info = get_venv_info()
                assert info == "poetry: /poetry/venv"
            finally:
                # Restore environment
                if original_virtual_env is not None:
                    os.environ["VIRTUAL_ENV"] = original_virtual_env
                os.environ.pop("POETRY_ACTIVE", None)
                os.environ.pop("POETRY_VENV_PATH", None)

    def test_get_venv_info_conda(self):
        """Test venv info with Conda."""
        with (
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
        ):
            # Temporarily clear VIRTUAL_ENV and POETRY_ACTIVE, set Conda env vars
            original_env = {}
            for key in ["VIRTUAL_ENV", "POETRY_ACTIVE"]:
                if key in os.environ:
                    original_env[key] = os.environ.pop(key)

            os.environ["CONDA_DEFAULT_ENV"] = "myenv"

            try:
                info = get_venv_info()
                assert info == "conda: myenv"
            finally:
                # Restore environment
                for key, value in original_env.items():
                    os.environ[key] = value
                os.environ.pop("CONDA_DEFAULT_ENV", None)

    def test_get_venv_info_base_prefix(self):
        """Test venv info with base_prefix detection."""
        with (
            patch(
                "trailblazer.env_checks._is_in_virtualenv", return_value=True
            ),
            patch.object(sys, "prefix", "/venv/path"),
            patch.object(sys, "base_prefix", "/system/python"),
        ):
            # Temporarily remove environment variables that would take precedence
            original_env = {}
            for key in ["VIRTUAL_ENV", "POETRY_ACTIVE", "CONDA_DEFAULT_ENV"]:
                if key in os.environ:
                    original_env[key] = os.environ.pop(key)

            try:
                info = get_venv_info()
                assert info == "virtualenv: /venv/path"
            finally:
                # Restore environment variables
                for key, value in original_env.items():
                    os.environ[key] = value
