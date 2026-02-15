# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

from importlib.metadata import version as _version

__author__ = u'Curtis Rueden'
__email__ = u'curtis@rueden.us'
__copyright__ = u'Public domain'
__license__ = u'License :: OSI Approved :: Unlicense'

__version__ = _version("beets-ibroadcast")
__status__ = u'Functional'

__PACKAGE_TITLE__ = u'iBroadcast'
__PACKAGE_NAME__ = u'beets-ibroadcast'
__PACKAGE_DESCRIPTION__ = u'iBroadcast plugin for Beets'
__PACKAGE_URL__ = u'https://github.com/ctrueden/beets-ibroadcast'

__PLUGIN_NAME__ = u'ibroadcast'
__PLUGIN_ALIAS__ = u'tpl'
__PLUGIN_SHORT_DESCRIPTION__ = u'the music revolution starts here'

__UPLOAD_COMMAND__ = u'ib-upload'
__UPLOAD_ALIAS__ = u'ibroadcast'

__PLAYLIST_COMMAND__ = u'ib-playlist'
__PLAYLIST_ALIAS__ = u'ib-pl'
