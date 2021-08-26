# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import json
import logging
from math import ceil
from pathlib import Path
from time import time
from optparse import OptionParser

from ibroadcast import iBroadcast

from beets import config # for reading playlist plugin configuration
from beets.library import Library
from beets.plugins import BeetsPlugin
from beets.ui import Subcommand, decargs
from beets.util import syspath, displayable_path

from beetsplug.ibroadcast import common


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
            help=u'report which files would be uploaded, but don\'t upload them'
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

        items = []
        for item in lib.items(query):
            items.append(item)
            if opts.pretend:
                self.pretend(item, force=opts.force)
            else:
                self.upload(item, force=opts.force)

        self.sync_playlists(items, pretend=opts.pretend)

    def show_version_information(self):
        common.say("{pt}({pn}) plugin for Beets: v{ver}".format(
            pt=common.plg_ns['__PACKAGE_TITLE__'],
            pn=common.plg_ns['__PACKAGE_NAME__'],
            ver=common.plg_ns['__version__']
        ), log_only=False)

    ## -- SHARED --

    def _connect(self):
        self.plugin._log.debug('Connecting to iBroadcast')
        username = self.plugin.config['username'].get()
        password = self.plugin.config['password'].get()
        self.ib = iBroadcast(username, password, log=self.plugin._log,
            client='beets-ibroadcast', version=common.plg_ns['__version__'])

        # Reorganize the tags to be keyed on name rather than ID.
        # This helps to achieve harmony with the usertag plugin.
        self.tags = {}
        for tagid, tag in self.ib.tags.items():
            tagcopy = tag.copy()
            tagname = tagcopy.pop('name')
            tagcopy['id'] = tagid
            if tagname in self.tags:
                self.plugin._log.warning(f"Ignoring duplicate tag '{tagname}' with ID {tagid}.")
            else:
                self.tags[tagname] = tagcopy

    def _verbose(self):
        return self.plugin._log.level <= logging.DEBUG

    def _stack_trace(self, e):
        if self._verbose():
            self.plugin._log.exception(e)

    @staticmethod
    def _trackid(item):
        return int(item.ib_trackid) if hasattr(item, 'ib_trackid') else None

    @staticmethod
    def _path(path):
        if type(path) == bytes: path = path.decode()
        return Path(str(path)).resolve()

    ## -- UPLOADS --

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
            try:
                new_trackid = self.ib.upload(syspath(item.path),
                                             label=displayable_path(item.path),
                                             force=force)
            except Exception as e:
                self.plugin._log.error(f'Error uploading track: {item}')
                self._stack_trace(e)
                return
            if new_trackid:
                if trackid:
                    self.plugin._log.debug(f'Trashing previous track ID: {trackid}')
                    try:
                        self.ib.trash([trackid])
                    except Exception as e:
                        self.plugin._log.error(f'Error trashing previously uploaded iBroadcast track {trackid}.')
                        self._stack_trace(e)
                self._update_track(item, new_trackid)
                trackid = new_trackid
                self.plugin._log.debug(f'Upload complete: {item}')
            else:
                self.plugin._log.warning(f'Not uploaded: {item}')

        if trackid:
            self._sync_tags(trackid, item)

    def _needs_upload(self, item):
        utime = self._uploadtime(item)
        needs_upload = item.mtime > common.safeint(utime, -1)
        if self._verbose():
            msg = 'Needs upload' if needs_upload else 'Already uploaded'
            self.plugin._log.debug(f'{msg}: {item} [mtime={item.mtime}; utime={utime}]')
        return needs_upload

    @staticmethod
    def _uploadtime(item):
        return int(item.ib_uploadtime) if hasattr(item, 'ib_uploadtime') else -1

    @staticmethod
    def _update_track(item, trackid):
        item.ib_trackid = 0 if not trackid else trackid
        item.ib_uploadtime = ceil(time())
        item.store()

    ## -- TAGS --

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

            try:
                self.ib.tagtracks(tagid, [trackid])
                lastsync_tagids.add(tagid)
            except Exception as e:
                self.plugin._log.error(f"Error tagging iBroadcast track {trackid} with tag '{self._tagname(tagid)}' [{tagid}].")
                self._stack_trace(e)

        for tagid in locally_removed:
            self.plugin._log.debug(f"--> Removing remote tag '{self._tagname(tagid)}' [{tagid}]")
            try:
                self.ib.tagtracks(tagid, [trackid], untag=True)
                lastsync_tagids.remove(tagid)
            except Exception as e:
                self.plugin._log.error(f"Error untagging iBroadcast track {trackid} with tag '{self._tagname(tagid)}' [{tagid}].")
                self._stack_trace(e)

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
        try:
            tagid = self.ib.createtag(tagname)
            self.ib.tags[tagid] = {'name': tagname}
            self.tags[tagname] = {'id': tagid}
            return tagid
        except Exception as e:
            self.plugin._log.error(f"Error creating iBroadcast tag 'tagname'.")
            self._stack_trace(e)

    def _local_tagids(self, item):
        usertags = self._usertags(item)
        return [self._tagid(tagname) for tagname in usertags.split('|')] if usertags else []

    def _remote_tagids(self, trackid):
        return self.ib.gettags(trackid) if trackid else []

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

    ## -- PLAYLISTS --

    def sync_playlists(self, items, playlists=None, relative_to=None, pretend=False):
        """
        Sync playlist contents between beets and iBroadcast.

        :param items:       The beets track items to consider when syncing
                            playlists. Playlists with tracks outside these
                            items will be skipped.
        :param playlists:   List of playlist paths to sync with iBroadcast,
                            or None to sync all playlists stored beneath the
                            playlist plugin's playlist_dir.
        :param relative_to: Directory to which playlist tracks are relative,
                            in the case of relative paths, or None to inherit
                            the playlist plugin's relative_to setting.
        :param pretend:     If True, report how playlists would be synced,
                            but don't actually do it.
        """
        if playlists is None:
            # No playlists explicitly given; glean playlists from config.
            if 'playlist' not in config:
                self.plugin._log.debug(f"No playlists given, and no playlist directory configured; skipping playlist sync.")
                return

            plcfg = config['playlist']

            # Where to read playlist files from.
            playlist_dir = self._path(plcfg['playlist_dir'].get() if 'playlist_dir' in plcfg else '.')
            if not playlist_dir.is_dir():
                self.plugin._log.warning(f"Invalid playlist directory: '{playlist_dir}'")
                return

            playlists = [path for path in playlist_dir.rglob('*.m3u') if path.is_file()]
            playlists.sort()

        if relative_to is None:
            # Interpret paths in the playlist files relative to a base
            # directory. Instead of setting it to a fixed path, it is also
            # possible to set it to 'playlist' to use the playlist's parent
            # directory or to 'library' to use the library directory.
            relative_to = plcfg['relative_to'].get() if 'relative_to' in plcfg else 'library'
            if relative_to == 'library': relative_to = config['directory'].get()

            if relative_to != 'playlist':
                relative_to = self._path(relative_to)
                if not relative_to.is_dir():
                    self.plugin._log.warning(f"Invalid relative_to directory: '{relative_to}'")
                    return

        # Retrieve last-synced playlist linkages.
        # TODO: Make this file path configurable in the beets-ibroadcast config.
        pl_lastsync_path = Path(config['directory'].get()) / '.ibroadcast-playlists.json'
        if pl_lastsync_path.is_file():
            try:
                with open(pl_lastsync_path) as f:
                    pl_lastsync = json.load(f)
            except Exception as e:
                self.plugin._log.error(f"Error parsing last-sync metadata from '{pl_lastsync_path}'.")
                self._stack_trace(e)
                pl_lastsync = {}
        else:
            pl_lastsync = {}

        self.plugin._log.info(f"Syncing playlists")

        # Sync local playlists.
        for playlist in playlists:
            path = Path(playlist)
            if not path.is_file():
                self.plugin._log.warning(f"Skipping invalid playlist: '{path}'")
                continue
            track_prefix = self._path(path.parent.parent) if relative_to == 'playlist' else self._path(relative_to)
            self._sync_playlist(items, path, track_prefix, pl_lastsync, pretend=pretend)

        if pretend: return # Nothing more we can do here!

        # Sync remote-only playlists.
        for playlistid in self.ib.playlists:
            pid = int(playlistid)
            plname = self.ib.playlists[playlistid]['name']
            plkeys = [k for k, v in pl_lastsync.items() if v['id'] == pid]
            if len(plkeys) > 1:
                self.plugin._log.warning(f"Skipping sync of iBroadcast playlist '{plname}' with ID {playlistid}, " +
                    f"because it somehow became linked to multiple local playlists:" +
                    ''.join([f'\n- {path}' for path in plkeys]))
            elif len(plkeys) == 0:
                # TODO: Check that all trackids listed on the remote have corresponding local queried items.
                # Then, create M3U locally with matching name, populated with beets track paths.
                self.plugin._log.warning(f"iBroadcast playlist '{plname}' with ID {playlistid} " +
                    "does not exist locally, and I am not smart enough to download it for you. Pull requests welcome!")
            elif not Path(plkeys[0]).is_file():
                # TODO: Decide how to handle this scenario. Should the playlist be recreated?
                # Or assume it was deleted locally, and therefore should be deleted remotely too?
                # Probably makes sense to compare the local and remote trackids to decide.
                self.plugin._log.warning(f"iBroadcast playlist '{plname}' with ID {playlistid} " +
                    "is linked to missing local playlist '{plkeys[0]}', and I am not smart enough to fix it for you. Pull requests welcome!")

        # Persist last-synced playlist linkages for next time.
        with open(pl_lastsync_path, 'w') as f:
            json.dump(pl_lastsync, f)

    def _sync_playlist(self, items, plpath, track_prefix, pl_lastsync, pretend=False):
        # Extract track paths from playlist file.
        with open(plpath) as pl:
            lines = [line.strip() for line in pl.readlines()]
        track_paths = [self._path(track_prefix / line) for line in lines if len(line) > 0 and not line.startswith('#')]

        # Convert track paths to iBroadcast trackids.
        track_results = []
        hints_to_fix = set()
        non_matching_tracks = 0
        local_trackids = []
        number_width = len(str(len(track_paths)))
        for track_path in track_paths:
            no = len(track_results) + 1

            # Fail fast if track file does not exist.
            if not track_path.is_file():
                track_results.append(f'  {no:{number_width}}. [ INVALID FILE  ] {track_path}')
                continue

            # Match track path to beets track item.
            track_items = [item for item in items if self._path(item.path) == track_path]
            if len(track_items) == 0:
                non_matching_tracks += 1
                track_results.append(f'  {no:{number_width}}. [  NOT IN QUERY  ] {track_path}')
                hints_to_fix.add("\nPlease make sure all tracks in the playlist are imported to beets, " +
                    "and that your query is broad enough to match all tracks of this playlist.")
                continue
            elif len(track_items) > 1:
                track_results.append(f'- {no:{number_width}}. [MULTIPLE MATCHES] {track_path}')
                continue
            track_item = next(iter(track_items))

            # Match beets track item to iBroadcast trackid.
            trackid = self._trackid(track_item)
            if not trackid:
                track_results.append(f'  {no:{number_width}}. [  NOT UPLOADED  ] {track_path}')
                hints_to_fix.add("\nPlease upload all the playlist's tracks to iBroadcast before syncing it.")
                continue

            track_results.append(f'  {no:{number_width}}. [       OK       ] {track_path}')
            local_trackids.append(trackid)

        if non_matching_tracks == len(track_paths):
            # None of the tracks of the playlist matched.
            self.plugin._log.debug(f"Skipping sync of playlist '{plpath}' with no matching tracks.");
            return
        elif len(local_trackids) < len(track_paths):
            # Some of the tracks of the playlist matched, but not all of them.
            self.plugin._log.debug(f"Skipping sync of playlist '{plpath}' with track problems:\n" + '\n'.join(track_results) + ''.join(hints_to_fix))
            return

        playlistid = playlist_name = lastsync_trackids = None
        plkey = str(plpath)
        if plkey in pl_lastsync:
            playlistid = pl_lastsync[plkey]['id']
            lastsync_trackids = pl_lastsync[plkey]['tracks']

        if pretend:
            # No iBroadcast connection -- report based on local info only.
            if not playlistid:
                self.plugin._log.info(f"Would create and sync new playlist for '{plpath}'")
            elif local_trackids != lastsync_trackids:
                self.plugin._log.info(f"Would upload modified track list for playlist '{plpath}'")
            else:
                self.plugin._log.info(f"Already synced: '{plpath}'")
            return

        if self.ib is None:
            self._connect()

        if playlistid:
            # Glean up-to-date track IDs from remote playlist.
            ib_playlist = self.ib.playlist(playlistid)
            if ib_playlist is None or 'tracks' not in ib_playlist:
                self._log.warning(f"Skipping sync of playlist '{plpath}' (iBroadcast ID {playlistid}) with no remote track list.")
                return
            remote_trackids = ib_playlist['tracks']
        else:
            # Playlist does not exist on the iBroadcast side; create it.
            playlist_name = plpath.name[:-4] # without .m3u suffix
            try:
                playlistid = self.ib.createplaylist(playlist_name)
            except Exception as e:
                self.plugin._log.error(f"Error creating iBroadcast playlist '{playlist_name}'.")
                self._stack_trace(e)
                return
            remote_trackids = None

        local_changes = local_trackids != lastsync_trackids
        remote_changes = remote_trackids != lastsync_trackids

        if local_changes and remote_changes:
            self.plugin._log.warning(f"Skipping sync of playlist '{plpath}' (iBroadcast ID {playlistid}) with both local and remote changes.")
            self.plugin._log.debug(f'* remote_trackids = {remote_trackids}')
            self.plugin._log.debug(f'* local_trackids = {local_trackids}')
            self.plugin._log.debug(f'* lastsync_trackids = {lastsync_trackids}')
            return

        if remote_changes:
            self.plugin._log.warning(f"Skipping sync of playlist '{plpath}' (iBroadcast ID {playlistid}) with remote changes, " +
                "because I am not smart enough to update your local playlist to match. Pull requests welcome!")
            self.plugin._log.debug(f'* remote_trackids = {remote_trackids}')
            self.plugin._log.debug(f'* local_trackids = {local_trackids}')
            self.plugin._log.debug(f'* lastsync_trackids = {lastsync_trackids}')
            #lastsync_trackids = remote_trackids
            return

        if local_changes:
            self.plugin._log.info(f"Syncing locally changed playlist '{plpath}' (iBroadcast ID {playlistid}).")
            try:
                self.ib.settracks(playlistid, local_trackids)
                lastsync_trackids = local_trackids
            except Exception as e:
                self.plugin._log.error(f"Error updating iBroadcast playlist {playlistid}.")
                self._stack_trace(e)
                return
        else:
            self.plugin._log.debug(f"Skipping sync of unchanged playlist '{plpath}' (iBroadcast ID {playlistid}).")

        # Update last-synced playlists metadata.
        pl_lastsync[plkey] = {'id': playlistid, 'tracks': lastsync_trackids}
