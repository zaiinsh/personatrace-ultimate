"""Demo CLI: python -m personatrace.demo_run --out demo/out

Writes investigation.json, case.html and case.json exports into the
output directory and prints counts. Demo data only (fictional
demo_* usernames, method="demo"); never present it as real data.

Location note: this file lives at personatrace/demo_run.py (rather
than demo/demo_run.py) because demo/ is not a regular package and
``python -m personatrace.demo_run`` is the reliable entry point.
The fixtures themselves live in demo/fixtures.py.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

__all__ = ["main"]


def _load_fixtures():
    try:
        from demo.fixtures import demo_investigation, to_dict

        return demo_investigation, to_dict
    except ImportError:
        path = Path(__file__).resolve().parent.parent / "demo" / "fixtures.py"
        spec = importlib.util.spec_from_file_location("demo_fixtures", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.demo_investigation, module.to_dict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the PersonaTrace demo investigation.")
    parser.add_argument("--out", default="demo/out", help="Output directory")
    args = parser.parse_args(argv)
    demo_investigation, to_dict = _load_fixtures()
    from personatrace.features.export import export_case

    inv = demo_investigation()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "investigation.json").write_text(
        json.dumps(to_dict(inv), indent=2, default=str), encoding="utf-8"
    )
    html_path = export_case(inv, out, fmt="html")
    json_path = export_case(inv, out, fmt="json")
    counts = {
        "profiles": len(inv.profiles),
        "edges": len(inv.edges),
        "platforms": len({p.platform for p in inv.profiles}),
        "timeline": len(inv.timeline),
        "alerts": len(inv.alerts),
        "possible_matches": len(inv.possible_matches),
        "audit": len(inv.audit),
    }
    print(f"Demo investigation: seed={inv.seed} case={inv.case_id}")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print(f"  investigation.json: {out / 'investigation.json'}")
    print(f"  case.html: {html_path}")
    print(f"  case.json: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
