# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

from math import ceil
from optparse import OptionParser
from time import time

from beets.library import Library
from beets.ui import Subcommand
from beets.util import syspath, displayable_path

from beetsplug.ibroadcast import common
from beetsplug.ibroadcast.helpers import trackid, assert_element_type
from beetsplug.ibroadcast.connection import IBroadcastBase


class IBUploadCommand(Subcommand, IBroadcastBase):

    def __init__(self, plugin):
        self.plugin = plugin

        self.parser = OptionParser(
            usage='beet ib-upload [options] [QUERY...]'
        )

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
            help=u'report which files would be uploaded, but don\'t upload them'
        )

        if self.plugin.config['auto'].get():
            self.plugin.register_listener('album_imported', self.upload_imported_album)
            self.plugin.register_listener('item_imported', self.upload_item)

        super(IBUploadCommand, self).__init__(
            parser=self.parser,
            name=common.plg_ns['__UPLOAD_COMMAND__'],
            aliases=[common.plg_ns['__UPLOAD_ALIAS__']] if
            common.plg_ns['__UPLOAD_ALIAS__'] else [],
            help=common.plg_ns['__PLUGIN_SHORT_DESCRIPTION__']
        )

    def func(self, lib: Library, opts, args):
        query = args

        if opts.version:
            self.show_version_information()
            return

        for item in lib.items(query):
            if opts.pretend:
                self.pretend(item, force=opts.force)
            else:
                self.upload(item, force=opts.force)

    def show_version_information(self):
        common.say("{pt}({pn}) plugin for Beets: v{ver}".format(
            pt=common.plg_ns['__PACKAGE_TITLE__'],
            pn=common.plg_ns['__PACKAGE_NAME__'],
            ver=common.plg_ns['__version__']
        ), log_only=False)

    ## -- UPLOADS --

    def pretend(self, item, force=False):
        if self._needs_upload(item):
            old_trackid = trackid(item)
            if old_trackid:
                self.plugin._log.info(f'Would re-upload: {item}')
            else:
                self.plugin._log.info(f'Would upload: {item}')
        else:
            if force:
                self.plugin._log.info(f'Would force-upload: {item}')
            else:
                self.plugin._log.debug(f'Already uploaded: {item}')

    def upload(self, item, force=False):
        if self.ib is None:
            self._connect()

        tid = trackid(item)
        if force or self._needs_upload(item):
            try:
                new_trackid = self.ib.upload(syspath(item.path),
                                             label=displayable_path(item.path),
                                             force=force)
            except Exception as e:
                self.plugin._log.error(f'Error uploading track: {item}')
                self._stack_trace(e)
                return
            if new_trackid:
                if tid:
                    self.plugin._log.debug(f'Trashing previous track ID: {tid}')
                    try:
                        self.ib.trash([tid])
                    except Exception as e:
                        self.plugin._log.error(f'Error trashing previously uploaded iBroadcast track {tid}.')
                        self._stack_trace(e)
                self._update_track(item, new_trackid)
                tid = new_trackid
                self.plugin._log.debug(f'Upload complete: {item}')
            else:
                self.plugin._log.warning(f'Not uploaded: {item}')

        if tid:
            self._sync_tags(tid, item)

    def _needs_upload(self, item):
        utime = self._uploadtime(item)
        needs_upload = item.mtime > common.safeint(utime, -1)
        if self._verbose():
            msg = 'Needs upload' if needs_upload else 'Already uploaded'
            self.plugin._log.debug(f'{msg}: {item} [mtime={item.mtime}; utime={utime}]')
        return needs_upload

    def upload_imported_album(self, lib, album):
        for item in album.items():
            self.upload(syspath(item))

    def upload_item(self, lib, item):
        self.upload(syspath(item))

    @staticmethod
    def _uploadtime(item):
        return int(item.ib_uploadtime) if hasattr(item, 'ib_uploadtime') else -1

    @staticmethod
    def _update_track(item, tid):
        item.ib_trackid = 0 if not tid else tid
        item.ib_uploadtime = ceil(time())
        item.store()

    ## -- TAGS --

    def _sync_tags(self, tid, item):
        local_tagids = set(self._local_tagids(item))
        remote_tagids = set(self._remote_tagids(tid))
        lastsync_tagids = set(self._lastsync_tagids(item))

        assert_element_type(local_tagids, str)
        assert_element_type(remote_tagids, str)
        assert_element_type(lastsync_tagids, str)

        locally_added = local_tagids - lastsync_tagids
        locally_removed = lastsync_tagids - local_tagids
        remotely_added = remote_tagids - lastsync_tagids
        remotely_removed = lastsync_tagids - remote_tagids

        if locally_added or locally_removed or remotely_added or remotely_removed:
            self.plugin._log.debug(f'Syncing tags for {item}')

        for tagid in locally_added:
            self.plugin._log.debug(f"--> Adding remote tag '{self._tagname(tagid)}' [{tagid}]")

            try:
                self.ib.tagtracks(tagid, [tid])
                lastsync_tagids.add(tagid)
            except Exception as e:
                self.plugin._log.error(f"Error tagging iBroadcast track {tid} with tag '{self._tagname(tagid)}' [{tagid}].")
                self._stack_trace(e)

        for tagid in locally_removed:
            self.plugin._log.debug(f"--> Removing remote tag '{self._tagname(tagid) or '[deleted tag]'}' [{tagid}]")
            try:
                self.ib.tagtracks(tagid, [tid], untag=True)
                lastsync_tagids.remove(tagid)
            except Exception as e:
                self.plugin._log.error(f"Error untagging iBroadcast track {tid} with tag '{self._tagname(tagid)}' [{tagid}].")
                self._stack_trace(e)

        for tagid in remotely_added:
            self.plugin._log.debug(f"--> Adding local tag '{self._tagname(tagid)}' [{tagid}]")
            lastsync_tagids.add(tagid)

        for tagid in remotely_removed:
            self.plugin._log.debug(f"--> Removing local tag '{self._tagname(tagid) or '[deleted tag]'}' [{tagid}]")
            if tagid in lastsync_tagids:
                # If the tag was removed both locally AND remotely,
                # then the id was already removed from the set.
                lastsync_tagids.remove(tagid)

        self._update_tags(item, lastsync_tagids)

    def _tagname(self, tagid):
        return self.ib.tags[tagid]['name'] if tagid in self.ib.tags else None

    def _tagid(self, tagname):
        if tagname in self.tags:
            # Existing remote tag.
            return self.tags[tagname]['id']

        # New remote tag -- create it.
        self.plugin._log.debug(f"--> Creating remote tag '{tagname}'")
        try:
            tagid = str(self.ib.createtag(tagname))
            self.ib.tags[tagid] = {'name': tagname}
            self.tags[tagname] = {'id': tagid}
            return tagid
        except Exception as e:
            self.plugin._log.error(f"Error creating iBroadcast tag '{tagname}'.")
            self._stack_trace(e)

    def _local_tagids(self, item):
        usertags = self._usertags(item)
        return [self._tagid(tagname) for tagname in usertags.split('|')] if usertags else []

    def _remote_tagids(self, tid):
        return self.ib.gettags(tid) if tid else []

    @staticmethod
    def _usertags(item):
        return item.usertags if hasattr(item, 'usertags') else ''

    @staticmethod
    def _lastsync_tagids(item):
        return item.ib_tagids.split('|') if hasattr(item, 'ib_tagids') and item.ib_tagids != '' else []

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
