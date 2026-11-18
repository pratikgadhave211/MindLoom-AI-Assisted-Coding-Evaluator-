# Jev code-comparison experiment

On 2026-11-13, six separate requests were sent to TypeSafe's Jev endpoint using `jev-latest`, which resolved to `jev-1.14.0`. Each request included the Flask challenge requirement, original and reference versions of the update/delete functions, the `get_post` helper, and one candidate version. Two Noul questions asked separately whether the candidate update and delete routes enforced ownership while still allowing the owner to act. The endpoint received these local challenge code snippets; API keys were not included in output.

| Candidate | Update | Delete |
|---|---:|---:|
| Reference fix | 0.99 | 0.98 |
| Alternative valid fix | 0.96 | 0.96 |
| Incorrect `check_author=False` | 0.01 | 0.01 |
| Original broken code | 0.01 | 0.01 |
| Only update fixed | 0.99 | 0.01 |
| Unrelated title-text change | 0.01 | 0.01 |

These are Jev's Noul values for the specific questions, not proven correctness rates or probabilities of the user completing the challenge. The classifications match the expected behavior for these six examples; the sample is too small to establish accuracy or calibration. Responses took 0.765–1.193 seconds per request in this run, including network time; this is not a production benchmark or a cost measurement.

The experiment assessed functions and a helper, not full files or multi-file repositories. It did not execute tests, validate full program behavior, modify the challenge, or integrate Jev code assessment into the application. It sent challenge code to the hosted provider, so real deployment requires appropriate handling of private challenge material and user code.
