"""cli.py — run BoneChilling from the terminal (doctors use the app; this is
for developers, CI, and headless batch runs).

    bonechilling ingest <folder...>  --provider ollama
    bonechilling ingest <folder...>  --provider openrouter --model google/gemini-2.0-flash-001
    bonechilling list
    bonechilling eval eval/labels.json --provider ollama
    bonechilling engine-test --provider openai

API keys come from --api-key or the provider's env var (never hardcoded).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from .engines.base import VisionEngine
from .engines.registry import PRESETS, build_engine, config_from_preset, list_models

ENV_KEYS = {
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
}


def _resolve_key(provider: str, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    for var in ENV_KEYS.get(provider, []):
        if os.environ.get(var):
            return os.environ[var]
    return None


def _make_engine(provider: str, model: Optional[str], api_key: Optional[str]) -> VisionEngine:
    preset = PRESETS.get(provider)
    if preset is None:
        sys.exit(f"unknown provider '{provider}'. Choices: {', '.join(PRESETS)}")
    key = _resolve_key(provider, api_key)
    if preset.needs_key and not key:
        envs = " or ".join(ENV_KEYS.get(provider, []))
        sys.exit(f"provider '{provider}' needs an API key: pass --api-key or set {envs}")
    return build_engine(config_from_preset(provider, model=model, api_key=key))


def _add_engine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", default="ollama", choices=list(PRESETS))
    p.add_argument("--model", default=None, help="override the preset's default model")
    p.add_argument("--api-key", default=None, help="API key (else read from env)")
    p.add_argument("--escalate-provider", default=None, choices=list(PRESETS),
                   help="fall back to this cloud provider on conflicts/validation failures")
    p.add_argument("--escalate-model", default=None)
    p.add_argument("--escalate-key", default=None)
    p.add_argument("--ocr-backend", default="tesseract", choices=["tesseract", "rapidocr"])
    p.add_argument("--db", default=None, help="SQLite path (default: ~/.bonechilling/...)")


def _escalation(args) -> Optional[VisionEngine]:
    if not getattr(args, "escalate_provider", None):
        return None
    return _make_engine(args.escalate_provider, args.escalate_model, args.escalate_key)


# --------------------------------------------------------------------------- #
def cmd_ingest(args) -> int:
    from .data import db as db_mod
    from .pipeline import runner

    engine = _make_engine(args.provider, args.model, args.api_key)

    def on_progress(ev: runner.ProgressEvent):
        tag = {"folder_start": "📁", "image_done": "  ✓", "image_skipped": "  ·",
               "folder_done": "✅", "batch_done": "🏁"}.get(ev.kind, "  ")
        line = ev.file or ev.folder or ""
        print(f"{tag} {line} — {ev.message}")

    result = runner.process_batch(
        args.paths, engine, db_path=Path(args.db) if args.db else None,
        escalation_engine=_escalation(args), ocr_backend=args.ocr_backend, progress=on_progress,
    )
    print(f"\nDone: {result['folders']} folders, {result['saved']} new films.")
    return 0


def cmd_list(args) -> int:
    from .data import db as db_mod

    conn = db_mod.connect(Path(args.db) if args.db else None)
    patients = db_mod.list_patients(conn)
    if not patients:
        print("No patients ingested yet.")
        return 0
    print(f"{'id':>3}  {'name':28s} {'films':>5}  folder")
    for p in patients:
        print(f"{p['id']:>3}  {(p['display_name'] or p['name'] or '—')[:28]:28s} "
              f"{p['image_count']:>5}  {p['folder_path']}")
    conn.close()
    return 0


def cmd_eval(args) -> int:
    from .eval import harness

    engine = _make_engine(args.provider, args.model, args.api_key)
    labels = harness.load_labels(args.labels)

    def on_progress(i, total, name):
        print(f"  [{i}/{total}] {name}")

    report = harness.evaluate(
        engine, labels, images_root=Path(args.images_root),
        ocr_backend=args.ocr_backend, escalation_engine=_escalation(args), progress=on_progress,
    )
    harness.print_report(report)
    if args.out:
        Path(args.out).write_text(json.dumps(report.to_dict(), indent=2))
        print(f"\nwrote {args.out}")
    return 0


def cmd_engine_test(args) -> int:
    engine = _make_engine(args.provider, args.model, args.api_key)
    ok, detail = engine.health_check()
    print(f"{args.provider}: {'OK' if ok else 'FAIL'} — {detail}")
    if ok:
        models = list_models(engine.config)
        if models:
            print(f"models ({len(models)}): " + ", ".join(models[:15]) + (" ..." if len(models) > 15 else ""))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bonechilling", description="Bulk X-ray fact extraction.")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("ingest", help="analyze patient folder(s) into the DB")
    pi.add_argument("paths", nargs="+")
    _add_engine_args(pi)
    pi.set_defaults(func=cmd_ingest)

    pl = sub.add_parser("list", help="list ingested patients")
    pl.add_argument("--db", default=None)
    pl.set_defaults(func=cmd_list)

    pe = sub.add_parser("eval", help="score accuracy against a labels file")
    pe.add_argument("labels")
    pe.add_argument("--images-root", default=".")
    pe.add_argument("--out", default=None, help="write the report JSON here")
    _add_engine_args(pe)
    pe.set_defaults(func=cmd_eval)

    pt = sub.add_parser("engine-test", help="validate a provider key/endpoint")
    _add_engine_args(pt)
    pt.set_defaults(func=cmd_engine_test)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
