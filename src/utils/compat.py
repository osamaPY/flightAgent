"""
Compatibility shims for removed/moved stdlib modules.

- imghdr.what: removed in Python 3.13; provides a minimal fallback for
  libraries (e.g. undetected-chromedriver) that still import it.
"""


def what(file, h=None):
    """Minimal imghdr.what polyfill — always returns 'jpeg'."""
    return "jpeg"


# Monkey-patch imghdr into sys.modules so that ``import imghdr``
# works transparently for third-party code.
import sys as _sys

if "imghdr" not in _sys.modules:
    _sys.modules["imghdr"] = _sys.modules[__name__]
