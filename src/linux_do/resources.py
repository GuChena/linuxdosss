# -*- coding: utf-8 -*-
"""Platform and resource helpers for the GUI entry point."""

import os
import platform
import sys


def configure_linux_input_method(system_name=None, environ=None, exists=None):
    """Set common Linux input method variables before Tkinter is imported."""
    system_name = system_name or platform.system()
    environ = os.environ if environ is None else environ
    exists = os.path.exists if exists is None else exists

    if system_name != "Linux" or "GTK_IM_MODULE" in environ:
        return

    if exists("/usr/bin/fcitx") or exists("/usr/bin/fcitx5"):
        environ["GTK_IM_MODULE"] = "fcitx"
        environ["QT_IM_MODULE"] = "fcitx"
        environ["XMODIFIERS"] = "@im=fcitx"
    elif exists("/usr/bin/ibus"):
        environ["GTK_IM_MODULE"] = "ibus"
        environ["QT_IM_MODULE"] = "ibus"
        environ["XMODIFIERS"] = "@im=ibus"


def get_font_names(system_name=None):
    """Return the UI and monospace fonts for the current platform."""
    system_name = system_name or platform.system()
    if system_name == "Darwin":
        return "PingFang SC", "Menlo"
    if system_name == "Linux":
        return "Noto Sans CJK SC", "Monospace"
    return "Microsoft YaHei UI", "Consolas"


def get_icon_path(source_file=None, frozen=None, meipass=None):
    """Return the application icon path in source and PyInstaller modes."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        base_path = meipass if meipass is not None else sys._MEIPASS
        return os.path.join(base_path, "icon.ico")

    source_file = os.path.abspath(source_file or __file__)
    source_dir = os.path.dirname(source_file)
    if os.path.basename(source_dir) == "linux_do":
        project_root = os.path.dirname(os.path.dirname(source_dir))
    else:
        project_root = os.path.dirname(source_dir)
    return os.path.join(project_root, "assets", "icon.ico")


def get_settings_path(cwd=None):
    """Return the local settings path beside browser_data in the working directory."""
    return os.path.join(cwd or os.getcwd(), "settings.json")


def create_tray_image(color="#0f3460"):
    """Create a small tray icon image."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    padding = 4
    draw.ellipse([padding, padding, size - padding, size - padding], fill=color)

    inner_padding = 12
    draw.ellipse(
        [inner_padding, inner_padding, size - inner_padding, size - inner_padding],
        fill="#1a1a2e",
    )

    center = size // 2
    dot_size = 8
    draw.ellipse(
        [center - dot_size, center - dot_size, center + dot_size, center + dot_size],
        fill="#00d9ff",
    )

    return img
