"""Create or resume an attempt and open its Theia workspace."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from dotenv import dotenv_values


def launch(post, attempt_id=None):
    if attempt_id:
        attempt_id = str(UUID(attempt_id))
        post(f"/attempts/{attempt_id}/resume")
    else:
        attempt_id = post("/attempts")["attempt_id"]

    try:
        result = post(f"/attempts/{attempt_id}/ide")
    except Exception as error:
        raise RuntimeError(f"Theia could not start. Attempt ID: {attempt_id}. {error}") from error
    return {"attempt_id": attempt_id, "url": result["url"]}


def main():
    parser = argparse.ArgumentParser(description="Start the local Theia workspace.")
    parser.add_argument("--attempt-id", help="Resume a saved attempt")
    args = parser.parse_args()

    env_file = Path(__file__).resolve().parents[2] / ".env"
    values = dotenv_values(env_file, interpolate=False)
    token = os.environ.get("AGENT_API_TOKEN", values.get("AGENT_API_TOKEN", ""))
    if not token:
        raise SystemExit("Set AGENT_API_TOKEN in .env first.")

    def post(path):
        request = Request("http://127.0.0.1:8000" + path, data=b"", method="POST")
        request.add_header("Authorization", "Bearer " + token)
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            detail = json.load(error).get("detail", "Request failed.")
            raise RuntimeError(str(detail)) from None
        except URLError:
            raise RuntimeError("Cannot reach the local agent API on port 8000.") from None

    try:
        result = launch(post, args.attempt_id)
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
    print("Attempt ID:", result["attempt_id"])
    print("Theia URL:", result["url"])
    print("Enter AGENT_API_TOKEN from coding-agent/.env when the Agentic chat asks for it.")


if __name__ == "__main__":
    main()
