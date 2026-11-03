"""Enumerate ideal periodic sample freshness; no network model is executed."""

from fractions import Fraction


def enumerated_fraction(q: int, deadline: int) -> Fraction:
    if q < 1 or deadline < 1:
        raise ValueError("q and deadline must be positive integers")
    # Sample at cycle offset 0. End-of-round age is offset + 1.
    return Fraction(sum(offset + 1 <= deadline for offset in range(q)), q)


def formula(q: int, deadline: int) -> Fraction:
    return min(Fraction(1), Fraction(deadline, q))


def main() -> None:
    for q in range(1, 97):
        for deadline in range(1, 97):
            assert enumerated_fraction(q, deadline) == formula(q, deadline)
    print("PASS: exact one-cycle enumeration agrees for 9,216 integer (q, D) pairs.")
    for q in (1, 2, 4, 8):
        fraction = enumerated_fraction(q, 4)
        print(f"D=4, q={q}: ideal fraction {fraction} ({float(100*fraction):.0f}%).")
    print("Assumes every scheduled sample succeeds and is delivered in its sampling round.")
    print("Changing cadence, missing samples, delay, and boundary transients are outside this check.")


if __name__ == "__main__":
    main()
