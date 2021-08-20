# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import logging
import os

# Get values as: plg_ns['__PLUGIN_NAME__']
plg_ns = {}
about_path = os.path.join(os.path.dirname(__file__), u'about.py')
with open(about_path) as about_file:
    exec(about_file.read(), plg_ns)

__logger__ = logging.getLogger('beets.{plg}'.format(
    plg=plg_ns['__PLUGIN_NAME__']))


def say(msg, log_only=True, is_error=False):
    _level = logging.DEBUG
    _level = _level if log_only else logging.INFO
    _level = _level if not is_error else logging.ERROR
    __logger__.log(level=_level, msg=msg)


def safeint(v, otherwise):
    try:
        return int(v)
    except ValueError:
        return otherwise
