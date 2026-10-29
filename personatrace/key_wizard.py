"""PersonaTrace key setup wizard — v7.0.0.

Run: python -m personatrace.key_wizard
  python -m personatrace.key_wizard --verify   # verify each entered key against its provider (one cheap call each)
  python -m personatrace.key_wizard --save     # save entered keys to the local vault (.personatrace_keys.json, 0600, git-ignored)
  python -m personatrace.key_wizard --login-consent  # record the Instagram login opt-in consent (typed confirmation only)

It asks for each key (input hidden), checks the format, and tells you
exactly what each key unlocks. It never prints a key back, never sends
a key anywhere except to the provider's own verification endpoint when
you choose --verify, and stores keys only in the local vault if you
choose --save. Without saving, keys are used for one run only.
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from personatrace.features.v7 import providers_v7 as _prov7
from personatrace.features.v6 import verify_key, save_key, ensure_gitignore, estimate_cost, LOGIN_CONSENT_TEXT, record_login_consent


def main(argv=None):
    argv = list(argv or [])
    verify = "--verify" in argv
    save = "--save" in argv
    print("PersonaTrace key setup wizard — v7.0.0")
    print("Press Enter to skip a key. Keys are never printed back.")
    if "--login-consent" in argv:
        print()
        print("LOGIN OPT-IN (Instagram, throwaway account only, read-only):")
        print("  - This uses Instagram's private/web API against its Terms.")
        print("  - Use a THROWAWAY/research account only, never a primary account.")
        print("  - Read-only: PersonaTrace will not follow, like, comment, DM or post.")
        print("  - The account may be challenged or banned; sessions may be invalidated.")
        print("  - No password is stored here — only this consent record. Provide a")
        print("    session file afterwards (see USER_GUIDE.md).")
        confirm = input(f"  Type exactly: {LOGIN_CONSENT_TEXT!r}  (or Enter to cancel): ")
        result = record_login_consent("instagram", confirm.strip())
        print(" ", result["note"])
        return 0
    print()
    keys = {}
    for name, info in _prov7().items():
        print(f"{name} ({info['label']}): unlocks {info['unlocks']}")
        print(f"  Cost preview: {info['cost_preview']}")
        value = getpass.getpass(f"  {name} (hidden, Enter to skip): ")
        if value.strip():
            keys[name] = value.strip()
        print()
    print("Summary (names only, never values):")
    for name, info in _prov7().items():
        if name in keys:
            if verify:
                from personatrace.features.v6 import PROVIDERS as _V6P
                if name not in _V6P:
                    print(f"  PRESENT (unverified — no cheap verification endpoint for this provider in v7; it will be tried on first use and disabled on 401/403) {name}: {info['unlocks']}")
                    if save:
                        save_key(name, keys[name])
                    continue
                row = verify_key(name, keys[name])
                print(f"  {'VERIFIED' if row.get('verified') else 'NOT VERIFIED'} {name}: {row['next_step']}")
            else:
                print(f"  PRESENT (unverified — run with --verify to check) {name}: {info['unlocks']}")
            if save:
                save_key(name, keys[name])
        else:
            print(f"  --- {name}: not supplied. Next step: add it to unlock {info['unlocks']}")
    if save and keys:
        ensure_gitignore()
        print("Saved to local vault .personatrace_keys.json (0600, git-ignored). Values were never printed.")
    if keys:
        plan = [{"provider": k, "requests": 10, "price_per_1000_usd": None} for k in keys]
        print("Cost preview for a 10-request dossier per key (provider prices vary — see above):", estimate_cost(plan, cap=None))
    print()
    print("To use these keys in a run, set them as environment variables")
    print("or add them in the GUI under Settings > API Keys, or re-run with --save.")
    print("To enable the Instagram login opt-in separately, run with --login-consent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
