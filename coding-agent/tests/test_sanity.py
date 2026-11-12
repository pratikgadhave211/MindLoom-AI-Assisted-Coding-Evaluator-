import pytest


def test_prompt_is_trimmed():
    from coding_agent.sanity import check_prompt

    assert check_prompt("  Find the bug  ") == "Find the bug"


@pytest.mark.parametrize("prompt", ["", "  ", "x" * 12001])
def test_invalid_prompts_are_rejected(prompt):
    from coding_agent.sanity import check_prompt

    with pytest.raises(ValueError):
        check_prompt(prompt)
