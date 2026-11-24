"""Run the API: ``python -m support_platform``."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "support_platform.api.app:create_app",
        factory=True,
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8080")),
        log_config=None,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
