import pytest
from computer_use import ComputerUseSession, is_computer_use_available


def test_availability_check_does_not_raise():
    # Should return True or False without crashing
    result = is_computer_use_available()
    assert isinstance(result, bool)


def test_session_construct_with_default_model():
    session = ComputerUseSession()
    assert session.model.startswith("claude")
    assert session.display_width > 0
    assert session.display_height > 0


def test_session_accepts_custom_display():
    session = ComputerUseSession(display_width=2560, display_height=1440)
    assert session.display_width == 2560
    assert session.display_height == 1440
