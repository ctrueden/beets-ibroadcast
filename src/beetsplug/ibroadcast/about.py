# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

from importlib.metadata import version as _version

__author__ = "Curtis Rueden"
__email__ = "curtis@rueden.us"
__copyright__ = "Public domain"
__license__ = "License :: OSI Approved :: Unlicense"

__version__ = _version("beets-ibroadcast")
__status__ = "Functional"

__PACKAGE_TITLE__ = "iBroadcast"
__PACKAGE_NAME__ = "beets-ibroadcast"
__PACKAGE_DESCRIPTION__ = "iBroadcast plugin for Beets"
__PACKAGE_URL__ = "https://github.com/ctrueden/beets-ibroadcast"

__PLUGIN_NAME__ = "ibroadcast"
__PLUGIN_ALIAS__ = "tpl"
__PLUGIN_SHORT_DESCRIPTION__ = "the music revolution starts here"

__UPLOAD_COMMAND__ = "ib-upload"
__UPLOAD_ALIAS__ = "ibroadcast"

__PLAYLIST_COMMAND__ = "ib-playlist"
__PLAYLIST_ALIAS__ = "ib-pl"
