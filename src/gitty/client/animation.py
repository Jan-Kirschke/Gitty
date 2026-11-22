"""Matrix-wave terminal reveal; never delays redirected output."""
import os
import random
import re
import sys
import time

ANSI_RE = re.compile(r"\033\[[0-9;]*m")
GLYPHS = "01@#%&*+:.~"


def print_banner(banner: str) -> None:
    animated = sys.stdout.isatty() and not os.environ.get("GITTY_NO_ANIMATION")
    if not animated:
        print(banner)
        return
    plain_lines = [ANSI_RE.sub("", line) for line in banner.splitlines()]
    height = len(plain_lines) + 1
    width = max((len(line) for line in plain_lines), default=0)
    print("Gitty startet … (Strg+C überspringt)")
    drawn = False
    try:
        sys.stdout.write("\033[?25l")
        frames = 14
        for frame in range(frames):
            if drawn:
                sys.stdout.write(f"\033[{height}A")
            reveal = int((frame + 1) * width / frames)
            out_lines = []
            for row, line in enumerate(plain_lines):
                buf = []
                for col, ch in enumerate(line):
                    if ch == " ":
                        buf.append(" ")
                    elif col < reveal:
                        buf.append(f"\033[92m{ch}")
                    elif col == reveal:
                        buf.append(f"\033[97m{random.choice(GLYPHS)}")
                    else:
                        buf.append(f"\033[32m{random.choice(GLYPHS)}")
                out_lines.append("".join(buf) + "\033[0m")
            pulse = "".join(
                "\033[96m~" if (c + frame) % 6 == 0 else "\033[32m·"
                for c in range(max(width, 24))
            )
            out_lines.append(pulse + "\033[0m")
            sys.stdout.write("\n".join(out_lines) + "\n")
            sys.stdout.flush()
            drawn = True
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        if drawn:
            sys.stdout.write(f"\033[{height}A")
            for _ in range(height):
                sys.stdout.write("\033[2K\n")
            sys.stdout.write(f"\033[{height}A")
        print(banner)
        sys.stdout.write("\033[?25h\033[0m")
        sys.stdout.flush()
