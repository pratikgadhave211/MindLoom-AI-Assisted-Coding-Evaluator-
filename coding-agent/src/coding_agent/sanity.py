def check_prompt(text, max_chars=12000):
    # Reject invalid prompts before contacting the model.
    prompt = text.strip()
    if not prompt:
        raise ValueError("Please enter a prompt.")
    if len(prompt) > max_chars:
        raise ValueError(f"Prompt must be {max_chars} characters or fewer.")
    return prompt
