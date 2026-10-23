"""终端里的小工具：上色，和上下键选择。不是终端（比如管道、测试）时退回普通输入、不上色。"""

import os
import sys

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
STYLES = {"want": "1;33", "good": "32", "bad": "31", "dim": "2", "road": "36", "fate": "35", "day": "1"}


def paint(text, style) -> str:
    return f"\033[{STYLES[style]}m{text}\033[0m" if COLOR else str(text)


def menu(title: str, options: list[str], start: int = 0) -> int:
    """上下键（或 j/k）移动，回车选定，返回选中的下标。选完只留一行「title › 选项」。"""
    if not sys.stdin.isatty() or os.name == "nt":            # Windows 没有 termios，退回打字
        return _typed(title, options, start)
    import termios
    import tty

    fd, out, i = sys.stdin.fileno(), sys.stdout, start
    old = termios.tcgetattr(fd)

    def draw(first=False):
        if not first:
            out.write(f"\033[{len(options) + 1}F")
        out.write(f"\033[2K{paint(title, 'day')}\n")
        for k, o in enumerate(options):
            out.write("\033[2K" + (paint("›", "want") if k == i else " ") + f" {o}\n")
        out.flush()

    try:
        tty.setcbreak(fd)
        out.write("\033[?25l")
        draw(first=True)
        while True:
            key = sys.stdin.read(1)
            if key == "\033":
                key += sys.stdin.read(2)
            if key in ("\033[A", "k"):
                i = (i - 1) % len(options)
            elif key in ("\033[B", "j"):
                i = (i + 1) % len(options)
            elif key in ("\r", "\n"):
                break
            elif key in ("\x04", "q"):
                raise EOFError
            draw()
    finally:
        out.write(f"\033[{len(options) + 1}F\033[J\033[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    out.write(f"{paint(title, 'dim')} › {options[i]}\n")
    return i


def _typed(title, options, start):
    """不是终端时：输选项的开头几个字（比如名字），直接回车 = 默认那项。"""
    while True:
        answer = input(f"{title}> ").strip()
        if not answer:
            return start
        hits = [k for k, o in enumerate(options) if o.startswith(answer)]
        if hits:
            return hits[0]
        print("没有这个选项，再说一遍。")
