import pytest


def test_jev_receives_prompt_and_returns_score(monkeypatch):
    from coding_agent.jev import check_with_jev

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"model": "jev-test", "answers": {"coding_request": {"noul": 0.96}}}

    def fake_post(url, headers, json, timeout):
        assert url == "https://api.typesafe.ai/v1/systemone"
        assert headers["Authorization"] == "Bearer fake-key"
        assert json["state"] == "Find the bug"
        assert json["questions"]["coding_request"]["type"] == "noul"
        return Response()

    monkeypatch.setattr("coding_agent.jev.httpx.post", fake_post)
    assert check_with_jev("Find the bug", "fake-key") == 0.96


@pytest.mark.parametrize("score", [None, -1, 2, "bad", True])
def test_jev_rejects_invalid_score(monkeypatch, score):
    from coding_agent.jev import check_with_jev

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": {"coding_request": {"noul": score}}}

    monkeypatch.setattr("coding_agent.jev.httpx.post", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError):
        check_with_jev("hello", "fake-key")
