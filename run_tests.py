"""
Runs tests for this webap.

Usage examples:
    (all) uv run ./run_tests.py -v
    (app) uv run ./run_tests.py -v pdf_checker_app
    (file) uv run ./run_tests.py -v tests.test_environment_checks
    (class) uv run ./run_tests.py -v tests.test_environment_checks.TestEnvironmentChecks
    (method) uv run ./run_tests.py -v tests.test_environment_checks.TestEnvironmentChecks.test_check_branch_non_main_raises
"""

import argparse
import os
import sys
import unittest
from pathlib import Path


def build_test_suite(targets: list[str], webapp_root: Path) -> unittest.TestSuite:
    """
    Builds a test suite from provided targets or via discovery.
    """
    loader = unittest.TestLoader()
    if targets:
        suite = unittest.TestSuite()
        for target in targets:
            suite.addTests(loader.loadTestsFromName(target))
    else:
        suite = loader.discover(start_dir=str(webapp_root), pattern='test*.py', top_level_dir=str(webapp_root))
    return suite


def run_test_suite(test_suite: unittest.TestSuite, verbosity: int) -> int:
    """
    Runs a test suite and returns the failure count.
    """
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(test_suite)
    return len(result.failures) + len(result.errors)


def main() -> None:
    """
    Discover and run tests for this webapp.
    - Uses standard library unittest (per AGENTS.md)
    - Uses Django's test runner so app-based tests (e.g., `pdf_checker_app/tests/`) are discovered
    - Sets top-level directory to the webapp root so `lib/` is importable
    """
    ## set up argparser ---------------------------------------------
    parser = argparse.ArgumentParser(description='Run webapp tests')
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Increase verbosity (equivalent to unittest verbosity=2)',
    )
    parser.add_argument(
        'targets',
        nargs='*',
        help=(
            'Optional dotted test targets to run, e.g. '
            '(app) `pdf_checker_app` or '
            '(module) `pdf_checker_app.tests.test_error_check` or '
            '(class/method) dotted paths under app tests'
        ),
    )
    ## parse args ---------------------------------------------------
    args = parser.parse_args()
    ## Ensure webapp root is importable (adds 'lib/', etc) ------
    webapp_root = Path(__file__).parent
    sys.path.insert(0, str(webapp_root))
    ## Change working directory to webapp root so relative discovery works
    os.chdir(webapp_root)
    verbosity = 2 if args.verbose else 1
    test_labels: list[str] = list(args.targets) if args.targets else []
    test_suite = build_test_suite(test_labels, webapp_root)
    failures = run_test_suite(test_suite, verbosity)
    sys.exit(0 if failures == 0 else 1)


if __name__ == '__main__':
    main()
