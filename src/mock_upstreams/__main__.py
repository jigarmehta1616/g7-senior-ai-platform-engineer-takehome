"""Run the mock upstreams: ``python -m mock_upstreams``."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "mock_upstreams.app:create_mock_app",
        factory=True,
        host=os.getenv("MOCK_HOST", "127.0.0.1"),
        port=int(os.getenv("MOCK_PORT", "8081")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
