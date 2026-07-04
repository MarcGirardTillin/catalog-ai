# Docstrings Convention

This backend template uses docstrings as reading aids, not as noise.

## Where to Write Them

Priority:

- public backend modules
- service classes, models, and FastAPI dependencies
- public functions used as template extension points
- route handlers when their role is not immediately obvious

In general, avoid:

- comments that merely paraphrase the code
- docstrings on trivial or purely local helpers
- docstrings on tests, unless the case is genuinely non-obvious

## Recommended Style

Prefer short docstrings in English, with:

1. a one-sentence summary
2. optionally `Args`, `Returns`, `Raises` sections if the function is not trivial

Simple example:

```python
def ping_database() -> bool:
    """Return whether the configured PostgreSQL database is reachable."""
```

More detailed example:

```python
def read_example(...) -> ExampleResponse:
    """Return a tiny example payload without touching the database.

    Args:
        sample_id: Example query parameter kept for validation demos.

    Returns:
        A small example payload for the template starter.
    """
```

## Useful Tools for Generating Them

The template does not impose a single generator. Recommended options are:

- PyCharm: generate a docstring stub from a function signature
- IDE snippets/docstring generators
- an AI assistant in the IDE or terminal to propose a first draft

Good practice:

- generate an initial stub automatically
- then rewrite it to describe the real business intent
- keep the docstring consistent with the types and behavior

## Review and Maintenance

When you add or modify a docstring:

- keep it aligned with the type annotations
- remove it if it provides no useful information
- read it as if you were onboarding to the template for the first time

The usual backend quality commands remain the baseline:

```bash
make format
make lint
make mypy
make pytest
```
