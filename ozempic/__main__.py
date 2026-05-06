"""
ozempic: macOS disk cleaner CLI entry point.
Stdlib only — no external dependencies.
"""

import sys
import argparse
from ozempic import cleaner, reporter, scanner


def parse_args():
    """Parse and return command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="ozempic",
        description="macOS disk cleaner — auto-cleans cache/logs, surfaces suspicious files."
    )
    parser.add_argument(
        "--scan",
        dest="scan_only",
        action="store_true",
        help="Scan only, no deletion"
    )
    parser.add_argument(
        "--clean",
        dest="clean_only",
        action="store_true",
        help="Clean only, skip anomaly scan"
    )
    parser.add_argument(
        "--keep-logs",
        action="store_true",
        help="Exclude logs from auto-clean"
    )
    parser.add_argument(
        "--delete-backup",
        metavar="ID",
        help="Delete iOS backup by UUID prefix"
    )
    return parser.parse_args()


def main():
    """Main CLI orchestration logic."""
    args = parse_args()

    # Standalone mode: --delete-backup
    if args.delete_backup:
        success = cleaner.delete_ios_backup(args.delete_backup)
        if success:
            print(f"Backup {args.delete_backup} deleted.")
        else:
            print(f"Backup {args.delete_backup} not found.", file=sys.stderr)
            sys.exit(1)
        return

    # FDA check (always runs unless --delete-backup)
    if not cleaner.check_fda():
        reporter.print_fda_error()
        sys.exit(1)

    cleaned = []
    review = []
    suspicious = []

    # Clean phase (unless --scan)
    if not args.scan_only:
        cleaned = cleaner.clean_all(keep_logs=args.keep_logs)
        review = cleaner.get_review_items()

    # Scan phase (unless --clean)
    if not args.clean_only:
        suspicious = scanner.scan_all()

    # Print results
    reporter.print_cleaned(cleaned)
    reporter.print_review(review)
    reporter.print_suspicious(suspicious)


if __name__ == "__main__":
    main()
