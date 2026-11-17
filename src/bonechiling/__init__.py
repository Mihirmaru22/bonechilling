"""BoneChilling — bulk orthopedic X-ray fact extraction."""

# Single source of the app version. Releases are tagged v<this> (checked by
# .github/workflows/release.yml); keep pyproject.toml's version in step.
__version__ = "0.2.0"


def main() -> None:
    from .cli import main as _cli_main
    raise SystemExit(_cli_main())
