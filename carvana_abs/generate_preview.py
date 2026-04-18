#!/usr/bin/env python3
"""Generate dashboard to the PREVIEW directory, then rsync PREVIEW → LIVE on promote.

The dashboard is now a tree of pages (index.html + economics/ + methodology/ +
deals/<slug>/ + assets/) rather than a single HTML file. generate_dashboard.py
writes the tree directly to static_site/preview/, so the preview step is a
pure regen. The promote step mirrors the full tree to static_site/live/.
"""
import subprocess
import sys
import os

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site")
PREVIEW_DIR = os.path.join(STATIC_DIR, "preview")
LIVE_DIR = os.path.join(STATIC_DIR, "live")

os.makedirs(PREVIEW_DIR, exist_ok=True)
os.makedirs(LIVE_DIR, exist_ok=True)


def generate_preview():
    """Run the dashboard generator — it writes directly to PREVIEW_DIR."""
    from generate_dashboard import main
    main()
    if os.path.exists(os.path.join(PREVIEW_DIR, "index.html")):
        print(f"Preview updated: {PREVIEW_DIR}/")
    else:
        print("ERROR: preview/index.html not generated")


def promote_to_live():
    """Mirror the full preview tree to live/ (approves the change).

    Uses rsync --delete so files removed from preview (e.g. retired deals)
    are also removed from live. Trailing slashes on both src and dst matter:
    they mean "copy the contents of preview/ into live/" rather than
    nesting preview/ under live/.
    """
    if not os.path.exists(os.path.join(PREVIEW_DIR, "index.html")):
        print("ERROR: No preview to promote")
        return
    # rsync -a  — archive mode (recursive, preserves perms/times).
    # --delete  — purge files in live/ that no longer exist in preview/.
    src = PREVIEW_DIR.rstrip("/") + "/"
    dst = LIVE_DIR.rstrip("/") + "/"
    subprocess.run(["rsync", "-a", "--delete", src, dst], check=True)
    print(f"Promoted preview tree → live: {dst}")

    # Purge Cloudflare cache so end-users see the new build immediately.
    purge = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "deploy", "cf_purge.sh")
    if os.path.exists(purge):
        subprocess.run(["bash", purge], check=False)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "promote":
        promote_to_live()
    else:
        generate_preview()
