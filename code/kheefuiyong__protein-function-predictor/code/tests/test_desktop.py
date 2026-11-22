import socket
from unittest.mock import Mock

from protein_function_predictor import desktop


def test_find_free_port_returns_bindable_port():
    port = desktop.find_free_port()

    assert 1 <= port <= 65535

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind(
            (
                desktop.HOST,
                port,
            )
        )


def test_open_browser_when_ready(
    monkeypatch,
):
    wait_for_health = Mock()
    browser_open = Mock()

    monkeypatch.setattr(
        desktop,
        "wait_for_health",
        wait_for_health,
    )

    health_url = (
        "http://127.0.0.1:8765/health"
    )

    app_url = (
        "http://127.0.0.1:8765/"
    )

    desktop.open_browser_when_ready(
        health_url=health_url,
        app_url=app_url,
        browser_open=browser_open,
    )

    wait_for_health.assert_called_once_with(
        health_url
    )

    browser_open.assert_called_once_with(
        app_url
    )


def test_open_browser_not_called_after_timeout(
    monkeypatch,
):
    browser_open = Mock()

    def raise_timeout(
        health_url: str,
    ) -> None:
        raise TimeoutError(
            "Server did not start."
        )

    monkeypatch.setattr(
        desktop,
        "wait_for_health",
        raise_timeout,
    )

    desktop.open_browser_when_ready(
        health_url=(
            "http://127.0.0.1:8765/health"
        ),
        app_url=(
            "http://127.0.0.1:8765/"
        ),
        browser_open=browser_open,
    )

    browser_open.assert_not_called()

def test_main_handles_keyboard_interrupt(
    monkeypatch,
):
    def raise_keyboard_interrupt() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        desktop,
        "run_desktop",
        raise_keyboard_interrupt,
    )

    desktop.main()