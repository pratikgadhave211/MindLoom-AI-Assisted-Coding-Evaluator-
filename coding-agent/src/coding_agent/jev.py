import httpx


def check_with_jev(prompt, api_key):
    # Ask Jev whether the prompt describes a software development request.
    response = httpx.post(
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "jev-latest",
            "state": prompt,
            "questions": {
                "coding_request": {
                    "type": "noul",
                    "instructions": "The message is a request related to a software development task.",
                }
            },
        },
        timeout=15.0,
    )
    response.raise_for_status()
    score = response.json().get("answers", {}).get("coding_request", {}).get("noul")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise ValueError("Jev returned an invalid score.")
    return score
