"""
micrOS Application exposed functions

For more coding details visit:
    https://github.com/BxNxM/micrOS/blob/master/micrOS/MODULE_GUIDE.md
"""

from package import shared


def load():
    return "Load app module"


def do():
    return f"Test app execution... with {shared()}"


def help():
    return "load", "do"
