"""Install, verify and launch the dashboard from the existing project Python."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", default="artifacts/models/hgb_v2_20261002T104801_398392Z")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    model_path = Path(args.model_path).expanduser()
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    if not (model_path / "metadata.json").is_file():
        raise SystemExit("metadata.json was not found. Pass --model-path with the saved model directory.")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535.")
    env = os.environ.copy()
    env["SENTINEL_MODEL_PATH"] = str(model_path)
    env["SENTINEL_API_URL"] = args.api_url

    def checked(command, message):
        result = subprocess.run(command, cwd=ROOT, env=env)
        if result.returncode != 0:
            raise SystemExit(message)

    if not args.skip_install:
        checked([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements-dashboard.txt")],
                "Dependency installation failed. Dashboard startup was stopped.")
    checked([sys.executable, str(ROOT / "scripts/smoke_test_dashboard.py")],
            "Dashboard checks failed. Keep the API running and review the error above before retrying.")
    command = [sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard/app.py"),
               "--server.address", "127.0.0.1", "--server.port", str(args.port),
               "--server.headless", str(args.headless).lower(), "--browser.gatherUsageStats", "false",
               "--theme.base", "light", "--theme.primaryColor", "#087f8c"]
    print(f"Opening DataFlow Sentinel at http://127.0.0.1:{args.port}", flush=True)
    try:
        return subprocess.run(command, cwd=ROOT, env=env).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
