import sys

from .report import build_report, print_summary, write_report


def main() -> int:
    report = build_report()
    path = write_report(report)
    print_summary(report)
    print(f"\nMachine-readable report written to {path}")
    return 0 if report["release_gate_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
