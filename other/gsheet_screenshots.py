#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "playwright~=1.58.0",
# ]
# ///

"""
Script to capture a series of screenshots of a Google Sheet.
Purpose: to show client reporting over time.

Usage, via cron...
```
uv run ./other/capture_google_sheet.py \
  --url 'https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=123456789' \
  --output-dir '../../sheet_screenshots' \
  --one-shot
```

Written by `ChatGPT-5.4-Low-Thinking`
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments.
    Called by: main()
    """
    parser = argparse.ArgumentParser(
        description=(
            'Captures screenshots of a Google Sheet on a repeating interval. '
            'Use --headed on the first run if you need to sign into Google.'
        )
    )
    parser.add_argument('--url', required=True, help='Google Sheets URL.')
    parser.add_argument(
        '--output-dir',
        default='./sheet_screenshots',
        help='Directory for PNG files.',
    )
    parser.add_argument(
        '--profile-dir',
        default='./playwright_google_profile',
        help='Persistent Playwright profile directory.',
    )
    parser.add_argument(
        '--every-minutes',
        type=float,
        default=5.0,
        help='Minutes between screenshots.',
    )
    parser.add_argument(
        '--width',
        type=int,
        default=1600,
        help='Browser viewport width in pixels.',
    )
    parser.add_argument(
        '--height',
        type=int,
        default=1000,
        help='Browser viewport height in pixels.',
    )
    parser.add_argument(
        '--scroll-x',
        type=int,
        default=0,
        help='Horizontal wheel-scroll delta applied after load.',
    )
    parser.add_argument(
        '--scroll-y',
        type=int,
        default=0,
        help='Vertical wheel-scroll delta applied after load.',
    )
    parser.add_argument(
        '--clip-x',
        type=int,
        default=None,
        help='Left edge of screenshot clip rectangle.',
    )
    parser.add_argument(
        '--clip-y',
        type=int,
        default=None,
        help='Top edge of screenshot clip rectangle.',
    )
    parser.add_argument(
        '--clip-width',
        type=int,
        default=None,
        help='Width of screenshot clip rectangle.',
    )
    parser.add_argument(
        '--clip-height',
        type=int,
        default=None,
        help='Height of screenshot clip rectangle.',
    )
    parser.add_argument(
        '--settle-seconds',
        type=float,
        default=4.0,
        help='Extra seconds to wait after page load.',
    )
    parser.add_argument(
        '--page-timeout-seconds',
        type=float,
        default=60.0,
        help='Navigation timeout in seconds.',
    )
    parser.add_argument(
        '--prefix',
        default='sheet',
        help='Output filename prefix.',
    )
    parser.add_argument(
        '--headed',
        action='store_true',
        help='Show the browser window instead of running headless.',
    )
    parser.add_argument(
        '--one-shot',
        action='store_true',
        help='Capture one screenshot and exit.',
    )
    args: argparse.Namespace = parser.parse_args()
    return args


def validate_args(args: argparse.Namespace) -> None:
    """
    Validates command-line arguments.
    Called by: main()
    """
    clip_values: list[int | None] = [
        args.clip_x,
        args.clip_y,
        args.clip_width,
        args.clip_height,
    ]
    provided_count: int = sum(value is not None for value in clip_values)
    if provided_count not in (0, 4):
        raise SystemExit('If you use clip arguments, provide all four: --clip-x --clip-y --clip-width --clip-height')
    if args.every_minutes <= 0:
        raise SystemExit('--every-minutes must be greater than 0')


def ensure_directory(path: Path) -> None:
    """
    Ensures a directory exists.
    Called by: run_loop()
    """
    path.mkdir(parents=True, exist_ok=True)


def launch_context(
    playwright: Playwright,
    profile_dir: Path,
    width: int,
    height: int,
    headed: bool,
) -> BrowserContext:
    """
    Launches a persistent Chromium context.
    Called by: run_loop()
    """
    context: BrowserContext = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=not headed,
        viewport={'width': width, 'height': height},
    )
    return context


def get_page(context: BrowserContext) -> Page:
    """
    Returns the first page in the context, creating one if needed.
    Called by: run_loop()
    """
    page: Page
    if context.pages:
        page = context.pages[0]
    else:
        page = context.new_page()
    return page


def build_output_path(output_dir: Path, prefix: str) -> Path:
    """
    Builds a timestamped output path.
    Called by: capture_once()
    """
    timestamp: str = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path: Path = output_dir / f'{prefix}_{timestamp}.png'
    return output_path


def focus_sheet_area(page: Page, width: int, height: int) -> None:
    """
    Clicks near the middle of the viewport so wheel-scrolling affects the sheet.
    Called by: apply_scroll()
    """
    click_x: int = max(100, width // 2)
    click_y: int = max(100, height // 2)
    page.mouse.click(click_x, click_y)


def apply_scroll(page: Page, width: int, height: int, scroll_x: int, scroll_y: int) -> None:
    """
    Applies mouse-wheel scrolling after focusing the sheet area.
    Called by: capture_once()
    """
    if scroll_x != 0 or scroll_y != 0:
        focus_sheet_area(page, width, height)
        page.mouse.wheel(scroll_x, scroll_y)
        page.wait_for_timeout(1000)


def screenshot_page(
    page: Page,
    output_path: Path,
    clip_x: int | None,
    clip_y: int | None,
    clip_width: int | None,
    clip_height: int | None,
) -> None:
    """
    Saves a screenshot to disk.
    Called by: capture_once()
    """
    if clip_x is None:
        page.screenshot(path=str(output_path))
    else:
        page.screenshot(
            path=str(output_path),
            clip={
                'x': clip_x,
                'y': clip_y,
                'width': clip_width,
                'height': clip_height,
            },
        )


def capture_once(
    page: Page,
    url: str,
    output_dir: Path,
    prefix: str,
    width: int,
    height: int,
    scroll_x: int,
    scroll_y: int,
    clip_x: int | None,
    clip_y: int | None,
    clip_width: int | None,
    clip_height: int | None,
    settle_seconds: float,
    page_timeout_seconds: float,
) -> Path:
    """
    Loads the sheet and captures one screenshot.
    Called by: run_loop()
    """
    timeout_ms: int = int(page_timeout_seconds * 1000)
    settle_ms: int = int(settle_seconds * 1000)

    page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
    page.wait_for_timeout(settle_ms)
    apply_scroll(page, width, height, scroll_x, scroll_y)

    output_path: Path = build_output_path(output_dir, prefix)
    screenshot_page(
        page=page,
        output_path=output_path,
        clip_x=clip_x,
        clip_y=clip_y,
        clip_width=clip_width,
        clip_height=clip_height,
    )
    return output_path


def run_loop(args: argparse.Namespace) -> None:
    """
    Runs the screenshot capture loop.
    Called by: main()
    """
    output_dir: Path = Path(args.output_dir).expanduser().resolve()
    profile_dir: Path = Path(args.profile_dir).expanduser().resolve()
    interval_seconds: float = args.every_minutes * 60.0

    ensure_directory(output_dir)
    ensure_directory(profile_dir)

    with sync_playwright() as playwright:
        context: BrowserContext = launch_context(
            playwright=playwright,
            profile_dir=profile_dir,
            width=args.width,
            height=args.height,
            headed=args.headed,
        )
        try:
            page: Page = get_page(context)
            next_run_time: float = time.monotonic()

            while True:
                try:
                    output_path: Path = capture_once(
                        page=page,
                        url=args.url,
                        output_dir=output_dir,
                        prefix=args.prefix,
                        width=args.width,
                        height=args.height,
                        scroll_x=args.scroll_x,
                        scroll_y=args.scroll_y,
                        clip_x=args.clip_x,
                        clip_y=args.clip_y,
                        clip_width=args.clip_width,
                        clip_height=args.clip_height,
                        settle_seconds=args.settle_seconds,
                        page_timeout_seconds=args.page_timeout_seconds,
                    )
                    print(f'[{datetime.now().isoformat(timespec="seconds")}] saved {output_path}')
                except Exception as exc:
                    print(
                        f'[{datetime.now().isoformat(timespec="seconds")}] capture failed: {exc}',
                        file=sys.stderr,
                    )

                if args.one_shot:
                    break

                next_run_time += interval_seconds
                sleep_seconds: float = max(0.0, next_run_time - time.monotonic())
                time.sleep(sleep_seconds)
        finally:
            context.close()


def main() -> None:
    """
    Orchestrates argument parsing and execution.
    Called by: __main__
    """
    args: argparse.Namespace = parse_args()
    validate_args(args)
    run_loop(args)


if __name__ == '__main__':
    main()
