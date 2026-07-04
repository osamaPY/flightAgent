"""Provider health test — verifies all 4 active providers."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core.provider_factory import build_providers


def test_all():
    providers = build_providers()
    print(f"\n=== PROVIDER HEALTH ({len(providers)} providers) ===")
    working, broken = [], []

    for p in providers:
        print(f"  Testing {p.name()}...", end=" ", flush=True)
        try:
            if p.is_healthy():
                print("[OK]")
                working.append(p.name())
            else:
                reason = p.get_health_reason()
                print(f"[FAIL] {reason}")
                broken.append((p.name(), reason))
        except Exception as e:
            print(f"[ERR] {e}")
            broken.append((p.name(), str(e)))

    print(f"\nResults: {len(working)} OK, {len(broken)} broken")
    if broken:
        for name, reason in broken:
            print(f"  - {name}: {reason}")
    return len(broken) == 0


if __name__ == "__main__":
    ok = test_all()
    exit(0 if ok else 1)
