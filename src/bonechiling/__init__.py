"""BoneChilling — bulk orthopedic X-ray fact extraction."""


def main() -> None:
    from .cli import main as _cli_main
    raise SystemExit(_cli_main())
