#!/usr/bin/env python3
"""Generate dashboard to the PREVIEW directory. Does not touch live."""
import subprocess
import sys
import os
import shutil

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site")
PREVIEW_DIR = os.path.join(STATIC_DIR, "preview")
LIVE_DIR = os.path.join(STATIC_DIR, "live")

os.makedirs(PREVIEW_DIR, exist_ok=True)
os.makedirs(LIVE_DIR, exist_ok=True)


def generate_preview():
    """Run the dashboard generator, then copy output to preview/."""
    # Generate to the default location
    from generate_dashboard import main
    main()

    # Copy to preview
    src = os.path.join(STATIC_DIR, "index.html")
    dst = os.path.join(PREVIEW_DIR, "index.html")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"Preview updated: /preview/")
    else:
        print("ERROR: index.html not generated")


def promote_to_live():
    """Copy the current preview to live (approve the change)."""
    src = os.path.join(PREVIEW_DIR, "index.html")
    dst = os.path.join(LIVE_DIR, "index.html")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print("Promoted preview to live!")
    else:
        print("ERROR: No preview to promote")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "promote":
        promote_to_live()
    else:
        generate_preview()
