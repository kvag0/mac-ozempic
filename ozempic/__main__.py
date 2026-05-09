"""
ozempic: macOS disk cleaner CLI entry point.
Stdlib only — no external dependencies.
"""

import sys
import argparse
from ozempic import cleaner, reporter


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ozempic",
        description="ozempic: A simple, safe macOS disk cleaner.",
    )
    parser.add_argument(
        "--keep-logs", action="store_true", help="Do not clean log directories"
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )
    args = parser.parse_args()

    # 1. FDA Check
    if not cleaner.check_fda():
        reporter.print_fda_error()
        sys.exit(1)

    # 2. Analyze -> Prompt -> Clean
    with reporter.Spinner("Analyzing safe-to-clean files"):
        pending_cleaned = cleaner.clean_all(keep_logs=args.keep_logs, dry_run=True)
        review_items = cleaner.get_review_items()

    if not pending_cleaned and not review_items:
        print("\nYour system is already lean! Nothing to clean.")
        sys.exit(0)

    # Show what can be cleaned
    if pending_cleaned:
        reporter.print_cleaned(pending_cleaned)
    
    if review_items:
        reporter.print_review(review_items)

    # Confirmation
    if not args.yes:
        try:
            choice = input("Proceed with cleaning the items listed above? (y/N): ").lower()
            if choice != "y":
                print("Cleaning cancelled.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nCleaning cancelled.")
            sys.exit(0)

    # Perform actual cleaning
    with reporter.Spinner("Cleaning"):
        actual_cleaned = cleaner.clean_all(keep_logs=args.keep_logs, dry_run=False)
    
    # Print final report
    if actual_cleaned:
        reporter.print_cleaned(actual_cleaned)
    else:
        print("Cleaning complete.")


if __name__ == "__main__":
    main()
