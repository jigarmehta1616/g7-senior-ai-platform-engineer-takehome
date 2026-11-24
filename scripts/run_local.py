"""Start mock upstreams (:8081) and the API (:8080) together. Cross-platform stand-in for
``make run`` (Windows has no make by default). Ctrl+C stops both."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def wait_for(url: str, timeout_s: float = 20) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:  # noqa: S310 - fixed localhost URL
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


def build_console() -> None:
    """Build the React console once (frontend/dist) if it isn't there yet."""
    frontend = ROOT / "frontend"
    if (frontend / "dist" / "index.html").exists():
        return
    npm = shutil.which("npm")
    if not npm:
        print("npm not found: API will run without the console (install Node 20+ to build it)", file=sys.stderr)
        return
    if not (frontend / "node_modules").exists():
        install = "ci" if (frontend / "package-lock.json").exists() else "install"
        subprocess.run([npm, install], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)


def main() -> int:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "mcp")])}
    (ROOT / "var").mkdir(exist_ok=True)
    build_console()
    procs = [subprocess.Popen([sys.executable, "-m", "mock_upstreams"], cwd=ROOT, env=env)]
    if not wait_for("http://127.0.0.1:8081/healthz"):
        print("mock upstreams failed to start", file=sys.stderr)
        procs[0].terminate()
        return 1
    procs.append(subprocess.Popen([sys.executable, "-m", "support_platform"], cwd=ROOT, env=env))
    if not wait_for("http://127.0.0.1:8080/readyz"):
        print("API failed to start", file=sys.stderr)
        for p in procs:
            p.terminate()
        return 1
    print("\n  API        http://localhost:8080   (Swagger UI: /docs, contract: /openapi.yaml)"
          "\n  Console    http://localhost:8080/console/"
          "\n  Upstreams  http://localhost:8081   (fault injection: POST /_admin/faults)\n"
          "\n  Ctrl+C to stop.\n", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            p.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
