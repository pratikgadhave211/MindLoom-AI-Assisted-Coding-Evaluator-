"""Run deterministic and advisory Jev checks as NeMo input actions."""

from pathlib import Path

from nemoguardrails import LLMRails, RailsConfig

from .sanity import check_prompt

RISK_THRESHOLD = 0.55


def is_flagged(score):
    """Flag scores above the threshold; an unavailable score is unknown."""
    return score > RISK_THRESHOLD if score is not None else None


def check_input(prompt, jev_checker=None):
    """Run the input rail without calling a second text-generation model."""
    # Keep the NeMo flow in a separate folder so it can be reviewed and extended.
    config_path = Path(__file__).resolve().parents[2] / "guardrails"
    config = RailsConfig.from_path(str(config_path))
    rails = LLMRails(config)

    def check_input_rules(context=None):
        """Apply the same clear prompt requirements inside the input rail."""
        check_prompt((context or {}).get("user_message", ""))
        return "passed"

    def check_input_jev(context=None):
        """Record Jev's safety score without blocking this first version."""
        if jev_checker is None:
            return {"status": "not configured", "score": None}
        try:
            score = jev_checker((context or {}).get("user_message", ""))
            if isinstance(score, bool) or not isinstance(score, (float, int)) or not 0 <= score <= 1:
                raise ValueError("Invalid score")
            return {"status": "checked", "score": score}
        except Exception:
            return {"status": "unavailable", "score": None}

    rails.register_action(check_input_rules, name="check_input_rules")
    rails.register_action(check_input_jev, name="check_input_jev")
    result = rails.generate(messages=[{"role": "user", "content": prompt}], options={
        "rails": {"input": True, "output": False, "dialog": False},
        "output_vars": ["rule_status", "jev_result"],
    })
    values = result.output_data or {}
    jev = values.get("jev_result") or {"status": "unavailable", "score": None}
    return {"rule_status": values.get("rule_status", "unavailable"),
            "jev_status": jev["status"], "risk_score": jev["score"],
            "threshold": RISK_THRESHOLD, "flagged": is_flagged(jev["score"])}
