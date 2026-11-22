import socket
import threading
import time
import webbrowser
from collections.abc import Callable
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from protein_function_predictor.api import app

HOST = "127.0.0.1"
DEFAULT_STARTUP_TIMEOUT = 180.0
HEALTH_POLL_INTERVAL = 0.5


def find_free_port(host: str = HOST) -> int:
    """Find an available TCP port on the local machine."""

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def wait_for_health(
    health_url: str,
    timeout: float = DEFAULT_STARTUP_TIMEOUT,
    poll_interval: float = HEALTH_POLL_INTERVAL,
) -> None:
    """Wait until the local FastAPI server reports healthy."""

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            with urlopen(
                health_url,
                timeout=2,
            ) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            pass

        time.sleep(poll_interval)

    raise TimeoutError(
        "Protein Function Predictor did not "
        f"become ready within {timeout:.0f} seconds."
    )


def open_browser_when_ready(
    health_url: str,
    app_url: str,
    browser_open: Callable[[str], object] = webbrowser.open,
) -> None:
    """Wait for the backend and then open the web interface."""

    try:
        wait_for_health(health_url)

        browser_open(app_url)
    except TimeoutError as error:
        print(f"Startup error: {error}")


def run_desktop(
    host: str = HOST,
    port: int | None = None,
) -> None:
    """Run the application as a local desktop-style web app."""

    if port is None:
        port = find_free_port(host)

    app_url = f"http://{host}:{port}/"
    health_url = f"http://{host}:{port}/health"

    print("Protein Function Predictor")
    print("Loading model...")
    print(f"Local application: {app_url}")
    print("Press Ctrl+C to quit.")

    browser_thread = threading.Thread(
        target=open_browser_when_ready,
        args=(
            health_url,
            app_url,
        ),
        daemon=True,
    )

    browser_thread.start()

    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
    )

    server = uvicorn.Server(config)

    server.run()


def main() -> None:
    """Desktop launcher entry point."""

    try:
        run_desktop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()