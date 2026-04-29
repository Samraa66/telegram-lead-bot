"""
Tests for VIP-name promotion: the pure matcher and the side-effecting promotion helper.
Run from backend/:  python -m scripts.test_vip_name_promotion
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("APP_ENV", "development")

from app.services.pipeline import name_matches_vip_marker

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_word_boundary_matches():
    print("\n=== Test 1: word-boundary matching ===")
    markers = ["vip", "premium"]
    cases = [
        # (first, last, expected_match_or_None)
        ("Mike",       "VIP",       "vip"),
        ("VIP Mike",   None,        "vip"),
        ("Sarah",      "(VIP)",     "vip"),
        ("[VIP] Test", None,        "vip"),
        ("PREMIUM",    "Member",    "premium"),
        ("Vipul",      None,        None),
        ("vipassana",  None,        None),
        ("Mike",       "Premiummax",None),
        ("",           "",          None),
        (None,         None,        None),
    ]
    all_ok = True
    for first, last, expected in cases:
        got = name_matches_vip_marker(first, last, markers)
        all_ok &= check(
            f"({first!r}, {last!r}) -> {expected!r} (got {got!r})",
            got == expected,
        )
    return all_ok


def test_empty_markers_returns_none():
    print("\n=== Test 2: empty marker list returns None ===")
    return check(
        "empty markers -> None",
        name_matches_vip_marker("Mike VIP", None, []) is None,
    )


def test_marker_with_regex_special_chars():
    print("\n=== Test 3: markers containing regex metacharacters are escaped ===")
    markers = ["v.i.p", "$$$"]
    ok1 = check(
        "literal 'v.i.p' matches 'Mike v.i.p'",
        name_matches_vip_marker("Mike", "v.i.p", markers) == "v.i.p",
    )
    ok2 = check(
        "'v.i.p' does NOT match 'vxixp' (no regex injection)",
        name_matches_vip_marker("Mike", "vxixp", markers) is None,
    )
    return ok1 and ok2


def main():
    results = [
        test_word_boundary_matches(),
        test_empty_markers_returns_none(),
        test_marker_with_regex_special_chars(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
