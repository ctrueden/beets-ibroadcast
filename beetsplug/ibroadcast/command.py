# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

from math import ceil
from time import time
from optparse import OptionParser

from beets.library import Library
from beets.plugins import BeetsPlugin
from beets.ui import Subcommand, decargs
from beets.util import syspath, displayable_path

from beetsplug.ibroadcast import common, ibroadcast


def _safeint(v, otherwise):
    try:
        return int(v)
    except ValueError:
        return otherwise


class IBroadcastCommand(Subcommand):
    plugin: BeetsPlugin = None
    lib: Library = None
    query = None
    parser: OptionParser = None
    ib = None

    def __init__(self, plugin):
        self.plugin = plugin

        self.parser = OptionParser(
            usage='beet {plg} [options] [QUERY...]'.format(
                plg=common.plg_ns['__PLUGIN_NAME__']
            ))

        self.parser.add_option(
            '-v', '--version',
            action='store_true', dest='version', default=False,
            help=u'show plugin version'
        )

        self.parser.add_option(
            '-p', '--pretend',
            action='store_true', dest='pretend', default=False,
            help=u'report which files would be uploaded, but don\'t upload anything'
        )

        super(IBroadcastCommand, self).__init__(
            parser=self.parser,
            name=common.plg_ns['__PLUGIN_NAME__'],
            aliases=[common.plg_ns['__PLUGIN_ALIAS__']] if
            common.plg_ns['__PLUGIN_ALIAS__'] else [],
            help=common.plg_ns['__PLUGIN_SHORT_DESCRIPTION__']
        )

    def func(self, lib: Library, opts, args):
        query = decargs(args)

        if opts.version:
            self.show_version_information()
            return

        if opts.pretend:
            for item in lib.items(query):
                self.pretend(item)
        else:
            for item in lib.items(query):
                self.upload(item)

    def pretend(self, item):
        if self._needs_upload(item):
            old_trackid = self._trackid(item)
            if old_trackid:
                self.plugin._log.info(f'Would re-upload: {item}')
            else:
                self.plugin._log.info(f'Would upload: {item}')
        else:
            self.plugin._log.info(f'Already uploaded: {item}')

    def upload(self, item):
        if self.ib is None:
            self.plugin._log.debug('Connecting to iBroadcast')
            username = self.plugin.config['username'].get()
            password = self.plugin.config['password'].get()
            self.ib = ibroadcast.iBroadcast(username, password, self.plugin._log)

        self.plugin._log.debug(f'Deciding whether to upload {item}')
        if self._needs_upload(item):
            old_trackid = self._trackid(item)
            new_trackid = self.ib.upload(syspath(item.path), displayable_path(item.path))
            if new_trackid:
                if old_trackid:
                    self.plugin._log.debug(f'Trashing previous track ID: {old_trackid}')
                    self.ib.trash([old_trackid])
                self._update(item, new_trackid)
            else:
                self.plugin._log.warn(f'Not uploaded: {item}')
        self.plugin._log.debug(f'Upload complete: {item}')

    def show_version_information(self):
        self._say("{pt}({pn}) plugin for Beets: v{ver}".format(
            pt=common.plg_ns['__PACKAGE_TITLE__'],
            pn=common.plg_ns['__PACKAGE_NAME__'],
            ver=common.plg_ns['__version__']
        ), log_only=False)

    def _needs_upload(self, item):
        utime = self._uploadtime(item)
        self.plugin._log.debug(f'{item.mtime} > {utime}? {item.mtime > utime}')
        return item.mtime > _safeint(utime, -1)

    @staticmethod
    def _say(msg, log_only=True, is_error=False):
        common.say(msg, log_only, is_error)

    @staticmethod
    def _trackid(item):
        return item.ib_trackid if hasattr(item, 'ib_trackid') else None

    @staticmethod
    def _uploadtime(item):
        return int(item.ib_uploadtime) if hasattr(item, 'ib_uploadtime') else -1

    @staticmethod
    def _update(item, trackid):
        item.ib_trackid = 0 if not trackid else trackid
        item.ib_uploadtime = ceil(time())
        item.store()
