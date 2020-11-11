# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import logging
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
    tags = None

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
            '-f', '--force',
            action='store_true', dest='force', default=False,
            help=u'uploads all matched files, even if they were already uploaded'
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
                self.pretend(item, force=opts.force)
        else:
            for item in lib.items(query):
                self.upload(item, force=opts.force)

    def pretend(self, item, force=False):
        if self._needs_upload(item):
            old_trackid = self._trackid(item)
            if old_trackid:
                self.plugin._log.info(f'Would re-upload: {item}')
            else:
                self.plugin._log.info(f'Would upload: {item}')
        else:
            if force:
                self.plugin._log.info(f'Would force-upload: {item}')
            else:
                self.plugin._log.info(f'Already uploaded: {item}')

    def upload(self, item, force=False):
        if self.ib is None:
            self._connect()

        trackid = self._trackid(item)
        if force or self._needs_upload(item):
            new_trackid = self.ib.upload(syspath(item.path),
                                         label=displayable_path(item.path),
                                         force=force)
            if new_trackid:
                if trackid:
                    self.plugin._log.debug(f'Trashing previous track ID: {trackid}')
                    self.ib.trash([trackid])
                self._update_track(item, new_trackid)
                trackid = new_trackid
                self.plugin._log.debug(f'Upload complete: {item}')
            else:
                self.plugin._log.warn(f'Not uploaded: {item}')

        if trackid:
            self._sync_tags(trackid, item)

    def show_version_information(self):
        self._say("{pt}({pn}) plugin for Beets: v{ver}".format(
            pt=common.plg_ns['__PACKAGE_TITLE__'],
            pn=common.plg_ns['__PACKAGE_NAME__'],
            ver=common.plg_ns['__version__']
        ), log_only=False)

    def _needs_upload(self, item):
        utime = self._uploadtime(item)
        needs_upload = item.mtime > _safeint(utime, -1)
        if self.plugin._log.isEnabledFor(logging.DEBUG):
            msg = 'Needs upload' if needs_upload else 'Already uploaded'
            self.plugin._log.debug(f'{msg}: {item} [mtime={item.mtime}; utime={utime}]')
        return needs_upload

    def _connect(self):
        self.plugin._log.debug('Connecting to iBroadcast')
        username = self.plugin.config['username'].get()
        password = self.plugin.config['password'].get()
        self.ib = ibroadcast.iBroadcast(username, password, self.plugin._log)

        # Reorganize the tags to be keyed on name rather than ID.
        # This helps to achieve harmony with the usertags plugin.
        self.tags = {}
        for tagid, tag in self.ib.tags.items():
            tagcopy = tag.copy()
            tagname = tagcopy.pop('name')
            tagcopy['id'] = tagid
            if tagname in self.tags:
                self.plugin._log.warn(f"Ignoring duplicate tag '{tagname}' with ID {tagid}")
            self.tags[tagname] = tagcopy

    def _sync_tags(self, trackid, item):
        local_tagids = set(self._local_tagids(item))
        remote_tagids = set(self._remote_tagids(trackid))
        lastsync_tagids = set(self._lastsync_tagids(item))

        locally_added = local_tagids - lastsync_tagids
        locally_removed = lastsync_tagids - local_tagids
        remotely_added = remote_tagids - lastsync_tagids
        remotely_removed = lastsync_tagids - remote_tagids

        if locally_added or locally_removed or remotely_added or remotely_removed:
            self.plugin._log.debug(f'Syncing tags for {item}')

        for tagid in locally_added:
            self.plugin._log.debug(f"--> Adding remote tag '{self._tagname(tagid)}' [{tagid}]")
            self.ib.tagtracks(tagid, [trackid])
            lastsync_tagids.add(tagid)

        for tagid in locally_removed:
            self.plugin._log.debug(f"--> Removing remote tag '{self._tagname(tagid)}' [{tagid}]")
            self.ib.tagtracks(tagid, [trackid], untag=True)
            lastsync_tagids.remove(tagid)

        for tagid in remotely_added:
            self.plugin._log.debug(f"--> Adding local tag '{self._tagname(tagid)}' [{tagid}]")
            lastsync_tagids.add(tagid)

        for tagid in remotely_removed:
            self.plugin._log.debug(f"--> Removing local tag '{self._tagname(tagid)}' [{tagid}]")
            lastsync_tagids.remove(tagid)

        self._update_tags(item, lastsync_tagids)

    def _tagname(self, tagid):
        return self.ib.tags[tagid]['name']

    def _tagid(self, tagname):
        if tagname in self.tags:
            # Existing remote tag.
            return self.tags[tagname]['id']

        # New remote tag -- create it.
        self.plugin._log.debug(f"--> Creating remote tag '{tagname}'")
        tagid = self.ib.createtag(tagname)
        self.ib.tags[tagid] = {'name': tagname}
        self.tags[tagname] = {'id': tagid}
        return tagid

    def _local_tagids(self, item):
        usertags = self._usertags(item)
        return [self._tagid(tagname) for tagname in usertags.split('|')] if usertags else []

    def _remote_tagids(self, trackid):
        return self.ib.gettags(trackid) if trackid else []

    @staticmethod
    def _say(msg, log_only=True, is_error=False):
        common.say(msg, log_only, is_error)

    @staticmethod
    def _usertags(item):
        return item.usertags if hasattr(item, 'usertags') else ''

    @staticmethod
    def _trackid(item):
        return item.ib_trackid if hasattr(item, 'ib_trackid') else None

    @staticmethod
    def _uploadtime(item):
        return int(item.ib_uploadtime) if hasattr(item, 'ib_uploadtime') else -1

    @staticmethod
    def _lastsync_tagids(item):
        return item.ib_tagids.split('|') if hasattr(item, 'ib_tagids') and item.ib_tagids != '' else []

    @staticmethod
    def _update_track(item, trackid):
        item.ib_trackid = 0 if not trackid else trackid
        item.ib_uploadtime = ceil(time())
        item.store()

    def _update_tags(self, item, tagids):
        changed = False

        if tagids != self._lastsync_tagids(item):
            item.ib_tagids = '|'.join(tagids)
            changed = True

        usertags = '|'.join(sorted(self._tagname(tagid) for tagid in tagids))
        if usertags != self._usertags(item):
            item.usertags = usertags
            changed = True

        if changed:
            item.store()
