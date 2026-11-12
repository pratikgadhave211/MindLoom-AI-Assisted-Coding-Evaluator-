# Phase 2: Workspace and read-only tools

> Planning update: The detailed Phase 2 plan also includes a bounded model/tool
> loop after the read-only foundation. Where this initial design differs, the
> detailed plan is the newer proposal, pending user approval.

## Goal

Give the agent a separate copy of the challenge and allow it to list, search,
and read files in that copy. Keep the original challenge unchanged. The model
continues to use LangChain and LangGraph.

## Approaches

1. Read directly from the original challenge. This is simple, but it does not
   provide a separate workspace for each attempt.
2. Make a separate local copy for each attempt and limit read tools to that
   directory. This is the smallest useful next step and allows local testing.
3. Run each attempt inside a separate Docker container. This is necessary to
   begin isolating commands, but is more than the read-only milestone needs.

Recommended: start with approach 2. Add Docker isolation before implementing
commands, running tests, or allowing untrusted users to use the system.

## Proposed flow

1. Create a fresh local workspace copy from the challenge template for an
   attempt. Never edit the template.
2. Accept a prompt, perform the current checks, and ask the model.
3. Validate each requested tool and execute list, search, or read against the
   selected copy. Return results or clear errors with their tool call IDs.
4. Show the results in the terminal. Editing, commands, and test execution
   remain placeholders.

## Boundaries

- Reject paths outside the chosen workspace, including paths that resolve
  outside it through symbolic links. Limit returned content to manageable size.
- Local path checks are a development convenience, not a security sandbox
  against a malicious user or concurrent filesystem changes.
- Avoid copying agent configuration or API keys into the challenge workspace.
- Do not automatically run commands on the host. Container isolation and
  resource limits belong to the command-execution milestone.
- Test that two copies are independent, the original is unchanged, normal
  reads work, and attempts to access files outside the workspace are rejected.

## Subsequent steps

After the read tools work, add the bounded model/tool loop, then isolated file
editing and command execution, with a separate container for each attempt.
