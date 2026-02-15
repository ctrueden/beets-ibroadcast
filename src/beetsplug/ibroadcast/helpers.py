# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import os
from pathlib import Path


def trackid(item):
    """Return the iBroadcast track ID for a beets item, or None."""
    return int(item.ib_trackid) if hasattr(item, 'ib_trackid') else None


def normpath(path):
    """
    Normalize a bytes or str path to a Path object.

    Uses os.path.normpath (pure string manipulation) rather than
    Path.resolve() to avoid filesystem syscalls, which are expensive
    over NFS or other network filesystems.
    """
    if type(path) == bytes:
        path = path.decode()
    return Path(os.path.normpath(str(path)))


def assert_type(obj, expected_type):
    assert type(obj) == expected_type


def assert_element_type(items, expected_type):
    for item in items:
        assert type(item) == expected_type
