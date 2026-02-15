# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

from optparse import OptionParser

from beets.library import Library
from beets.ui import Subcommand

from beetsplug.ibroadcast import common
from beetsplug.ibroadcast.connection import IBroadcastBase
from beetsplug.ibroadcast.playlist_sync import PlaylistSyncManager


class IBPlaylistCommand(Subcommand, IBroadcastBase):

    def __init__(self, plugin):
        self.plugin = plugin

        self.parser = OptionParser(
            usage='beet ib-playlist [options] [PLAYLIST_NAME...]'
        )

        self.parser.add_option(
            '--upload',
            action='store_true', dest='upload', default=False,
            help=u'push local M3U playlists to iBroadcast only'
        )

        self.parser.add_option(
            '--download',
            action='store_true', dest='download', default=False,
            help=u'pull iBroadcast playlists to local M3U only'
        )

        self.parser.add_option(
            '--sync',
            action='store_true', dest='sync', default=False,
            help=u'bidirectional sync (default if no direction flag)'
        )

        self.parser.add_option(
            '--delete',
            action='store_true', dest='delete', default=False,
            help=u'propagate deletions'
        )

        self.parser.add_option(
            '-p', '--pretend',
            action='store_true', dest='pretend', default=False,
            help=u'report what would happen, but don\'t actually do it'
        )

        super(IBPlaylistCommand, self).__init__(
            parser=self.parser,
            name=common.plg_ns['__PLAYLIST_COMMAND__'],
            aliases=[common.plg_ns['__PLAYLIST_ALIAS__']] if
            common.plg_ns['__PLAYLIST_ALIAS__'] else [],
            help=u'sync playlists with iBroadcast'
        )

    def func(self, lib: Library, opts, args):
        # Determine sync mode.
        if opts.upload:
            mode = 'upload'
        elif opts.download:
            mode = 'download'
        else:
            mode = 'sync'

        # Playlist name filters from positional args.
        filters = list(args) if args else None

        manager = PlaylistSyncManager(
            plugin=self.plugin,
            ib_base=self,
            lib=lib,
            pretend=opts.pretend,
        )
        manager.sync(mode=mode, allow_delete=opts.delete, filters=filters)
