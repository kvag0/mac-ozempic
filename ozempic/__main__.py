"""
ozempic: macOS disk cleaner CLI entry point.
Stdlib only — no external dependencies.
"""

import argparse
import sys

from ozempic import cleaner, history, reporter, trash, uninstaller
from ozempic.checklist import run_checklist


def run_clean(keep_logs: bool, yes: bool) -> int:
    # 1. FDA Check
    reporter.print_logo()
    if not cleaner.check_fda():
        reporter.print_fda_error()
        return 1

    # 2. Analyze -> Prompt -> Clean
    analyze_spinner = reporter.Spinner("Analyzing safe-to-clean files")
    with analyze_spinner:
        pending_cleaned = cleaner.clean_all(
            keep_logs=keep_logs,
            dry_run=True,
            on_progress=analyze_spinner.update_message,
        )
        review_items = cleaner.get_review_items()

    if not pending_cleaned and not review_items:
        print("\nYour system is already lean! Nothing to clean.")
        return 0

    # Show what can be cleaned
    if pending_cleaned:
        reporter.print_cleaned(pending_cleaned)

    if review_items:
        reporter.print_review(review_items)

    # Confirmation
    if not yes:
        try:
            choice = input("Proceed with cleaning the items listed above? (y/N): ").lower()
            if choice != "y":
                print("Cleaning cancelled.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nCleaning cancelled.")
            return 0

    # Perform actual cleaning
    clean_spinner = reporter.Spinner("Cleaning system files")
    with clean_spinner:
        actual_cleaned = cleaner.clean_all(
            keep_logs=keep_logs,
            dry_run=False,
            on_progress=clean_spinner.update_message,
        )
    history.append({"subcommand": "clean", "results": actual_cleaned})

    # Print final report
    if actual_cleaned:
        reporter.print_cleaned(actual_cleaned)
    else:
        print("Cleaning complete.")
    return 0


def _fail(message: str) -> int:
    print(f"\n  {reporter.RED}{message}{reporter.RESET}\n")
    return 1


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


def _pick_app(query: str, roots: uninstaller.Roots):
    apps = uninstaller.find_apps(query, roots)
    if len(apps) <= 1:
        return apps[0] if apps else None
    print(f"\n  Several apps match '{query}':")
    for i, app in enumerate(apps, 1):
        print(f"    {i}) {app}")
    choice = _ask("  Which one? (number): ")
    if choice.isdigit() and 1 <= int(choice) <= len(apps):
        return apps[int(choice) - 1]
    return None


def run_uninstall(query: str, dry_run: bool, roots: uninstaller.Roots | None = None) -> int:
    roots = roots or uninstaller.Roots.default()
    reporter.print_logo()
    if not cleaner.check_fda():
        reporter.print_fda_error()
        return 1

    app = _pick_app(query, roots)
    if app is None:
        return _fail(f"No app found matching '{query}'.")

    try:
        with reporter.Spinner("Finding leftovers"):
            info = uninstaller.read_app_info(app, roots)
            others = uninstaller.other_apps(roots, exclude=app)
            items = uninstaller.find_candidates(info, others, roots)
    except uninstaller.UninstallError as e:
        return _fail(str(e))

    if dry_run:
        reporter.print_candidates(info, items)
        return 0

    if trash.hosts_terminal(info):
        return _fail(f"ozempic is running inside {app.stem}. Run it from another terminal.")
    if not trash.finder_available():
        return _fail("ozempic can't control Finder. Allow it in System Settings → "
                     "Privacy & Security → Automation → your terminal → Finder.")
    selected = run_checklist(info, items)
    if not selected:
        print("\n  Nothing removed.\n")
        return 0

    # Quit only after the user confirmed, so cancelling never closes the app.
    if trash.is_running(info):
        if _ask(f"  {app.stem} is running. Quit it? (y/N): ").lower() != "y":
            return _fail("Uninstall cancelled; the app is still running.")
        if not trash.quit_app(info):
            return _fail(f"{app.stem} did not quit. Close it and try again.")

    paths = [c.path for c in selected]
    agents = [p for p in paths if p.parent.name in ("LaunchAgents", "LaunchDaemons")]
    if agents:
        trash.unload_launchd(agents)
    failed = trash.move_to_trash(paths)
    failed_paths = {p for p, _ in failed}
    removed = [c for c in selected if c.path not in failed_paths]
    if any(c.path.suffix == ".plist" and c.path.parent.name in ("Preferences", "ByHost")
           for c in removed):
        trash.flush_prefs()

    history.append({
        "subcommand": "uninstall",
        "app": str(info.path),
        "bundle_id": info.bundle_id,
        "removed": [{"path": str(c.path), "size": c.size} for c in removed],
        "failed": [{"path": str(p), "reason": r} for p, r in failed],
    })
    reporter.print_uninstalled(removed, failed)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Bare `ozempic` and old-style `ozempic --keep-logs` keep meaning `clean`.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["clean", *argv]

    parser = argparse.ArgumentParser(
        prog="ozempic",
        description="ozempic: A simple, safe macOS disk cleaner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    clean = sub.add_parser("clean", help="Clean known-safe caches and logs (default)")
    clean.add_argument("--keep-logs", action="store_true", help="Do not clean log directories")
    clean.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    uninstall = sub.add_parser("uninstall", help="Remove an app and everything it left behind")
    uninstall.add_argument("app", help="App name, bundle ID, or path to the .app")
    uninstall.add_argument("--dry-run", action="store_true",
                           help="List what would be removed without touching anything")

    args = parser.parse_args(argv)
    if args.command == "clean":
        return run_clean(keep_logs=args.keep_logs, yes=args.yes)
    return run_uninstall(args.app, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
