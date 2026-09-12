# Contributing

Clone the repository and run `uv sync --frozen` from its root. The project includes
root-level schemas, configuration, and three Agent Skills; a Python wheel alone
is not a complete installation.

Use synthetic fixtures. Run `uv run python -m unittest discover -s tests_broll`
and `uv run python scripts/check_release.py`. Changes to Skills should preserve
their discovery boundaries, existing approvals, and relative links. Check the
three entry points with the host's `skill-creator/scripts/quick_validate.py` when
available.

Changes to deployment, hardware, nodes, models, or workflows also need fresh GPU
evidence before they can be advertised as supported. Offline CI does not prove
that a cloud installation or video generation succeeded. Document test scope
and remaining limitations in the pull request.

Keep changes focused. Do not commit generated outputs, credentials, weights, or
private source material. Do not silently change the default number of draws,
budget, approval gates, or recovery semantics.
