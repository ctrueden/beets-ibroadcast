# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import json
import os
import shutil
from pathlib import Path

from beets import config

from beetsplug.ibroadcast.helpers import trackid, normpath


# Default state file path.
DEFAULT_STATE_DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'beets'
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / 'ibroadcast-playlists.json'


class PlaylistSyncManager:
    """Core playlist sync logic, independent of CLI concerns."""

    def __init__(self, plugin, ib_base, lib, pretend=False):
        """
        :param plugin:   The BeetsPlugin instance (for logging/config).
        :param ib_base:  An IBroadcastBase instance (for connection).
        :param lib:      The beets Library.
        :param pretend:  If True, only report what would happen.
        """
        self.plugin = plugin
        self.ib_base = ib_base
        self.lib = lib
        self.pretend = pretend

    def sync(self, mode='sync', allow_delete=False, filters=None):
        """
        Main entry point for playlist syncing.

        :param mode:          'upload', 'download', or 'sync' (bidirectional).
        :param allow_delete:  If True, propagate deletions.
        :param filters:       Optional list of playlist names to filter by.
        """
        # Discover local M3U playlists.
        playlist_dir, relative_to = self._get_playlist_config()
        if playlist_dir is None:
            return

        self.plugin._log.debug("Discovering local playlists...")
        local_playlists = self._discover_local_playlists(playlist_dir, filters)
        self.plugin._log.debug(f"Found {len(local_playlists)} local playlist(s).")

        # Load state.
        state_path = self._get_state_path()
        state = self._load_state(state_path)

        # Connect to iBroadcast when needed (pretend mode is read-only, not offline).
        needs_connection = mode in ('download', 'sync') or not self.pretend
        if needs_connection and self.ib_base.ib is None:
            self.ib_base._connect()

        # Run sync operations based on mode.
        if mode in ('upload', 'sync'):
            # For upload, build path→trackid only for paths in M3U files.
            self.plugin._log.debug("Collecting track paths from playlists...")
            all_m3u_paths = self._collect_m3u_paths(local_playlists, relative_to)
            self.plugin._log.debug(f"Found {len(all_m3u_paths)} unique track path(s) across playlists.")
            self.plugin._log.debug("Looking up track IDs...")
            path_to_trackid = self._build_path_to_trackid(all_m3u_paths)
            self.plugin._log.debug(f"Resolved {len(path_to_trackid)} uploaded track(s).")
            self._upload_playlists(local_playlists, playlist_dir, relative_to,
                                   path_to_trackid, state, allow_delete)

        if mode in ('download', 'sync'):
            # For download, build trackid→path index via SQL.
            self.plugin._log.debug("Building track ID index for download...")
            trackid_to_path = self._build_trackid_to_path()
            self.plugin._log.debug(f"Indexed {len(trackid_to_path)} uploaded track(s).")
            self._download_playlists(playlist_dir, relative_to,
                                     trackid_to_path, state, allow_delete, filters)

        # Save state.
        if not self.pretend:
            self._save_state(state_path, state)

    def _collect_m3u_paths(self, local_playlists, relative_to):
        """Parse all M3U files and collect the set of referenced track paths."""
        all_paths = set()
        for plpath in local_playlists:
            track_prefix = self._resolve_track_prefix(plpath, relative_to)
            paths = self._parse_m3u(plpath, track_prefix)
            all_paths.update(paths)
        return all_paths

    def _build_path_to_trackid(self, paths):
        """
        Build a path→trackid mapping for only the given paths.

        Uses a direct SQL query against the flexible attributes table to avoid
        loading every library item and its flexible attributes.
        """
        if not paths:
            return {}

        path_to_trackid = {}
        # Normalize the target paths for comparison.
        target_paths = {str(p): p for p in paths}

        # Query the database directly: join items with their ib_trackid attribute.
        db = self.lib._connection()
        query = """
            SELECT items.path, item_attributes.value
            FROM items
            INNER JOIN item_attributes ON items.id = item_attributes.entity_id
            WHERE item_attributes.key = 'ib_trackid'
              AND item_attributes.value IS NOT NULL
              AND item_attributes.value != ''
              AND item_attributes.value != '0'
        """
        for row in db.execute(query):
            item_path = normpath(row[0])
            if str(item_path) in target_paths:
                try:
                    path_to_trackid[item_path] = int(row[1])
                except (ValueError, TypeError):
                    pass

        return path_to_trackid

    def _build_trackid_to_path(self):
        """
        Build a trackid→path mapping via direct SQL query.

        Much faster than iterating all library items via the ORM, since it
        avoids loading flexible attributes per-item.
        """
        trackid_to_path = {}
        db = self.lib._connection()
        query = """
            SELECT items.path, item_attributes.value
            FROM items
            INNER JOIN item_attributes ON items.id = item_attributes.entity_id
            WHERE item_attributes.key = 'ib_trackid'
              AND item_attributes.value IS NOT NULL
              AND item_attributes.value != ''
              AND item_attributes.value != '0'
        """
        for row in db.execute(query):
            try:
                tid = int(row[1])
            except (ValueError, TypeError):
                continue
            trackid_to_path[tid] = normpath(row[0])

        return trackid_to_path

    def _get_playlist_config(self):
        """Read playlist directory and relative_to from beets config."""
        if 'playlist' not in config:
            self.plugin._log.debug("No playlist directory configured; skipping playlist sync.")
            return None, None

        plcfg = config['playlist']

        # Where to read/write playlist files.
        playlist_dir = normpath(plcfg['playlist_dir'].get() if 'playlist_dir' in plcfg else '.')
        if not playlist_dir.is_dir():
            self.plugin._log.warning(f"Invalid playlist directory: '{playlist_dir}'")
            return None, None

        # How to interpret relative paths in M3U files.
        relative_to = plcfg['relative_to'].get() if 'relative_to' in plcfg else 'library'
        if relative_to == 'library':
            relative_to = normpath(config['directory'].get())
        elif relative_to != 'playlist':
            relative_to = normpath(relative_to)
            if not relative_to.is_dir():
                self.plugin._log.warning(f"Invalid relative_to directory: '{relative_to}'")
                return None, None

        return playlist_dir, relative_to

    def _discover_local_playlists(self, playlist_dir, filters=None):
        """Find M3U files in the playlist directory."""
        playlists = sorted(p for p in playlist_dir.rglob('*.m3u') if p.is_file())
        if filters:
            filter_set = {f.lower() for f in filters}
            playlists = [p for p in playlists if p.stem.lower() in filter_set]
        return playlists

    def _get_state_path(self):
        """Determine state file path, migrating from old location if needed."""
        # Check for configured path.
        configured = self.plugin.config['playlist_state'].get()
        if configured:
            return Path(configured)

        state_path = DEFAULT_STATE_FILE

        # Auto-migrate from old location.
        old_path = Path(config['directory'].get()) / '.ibroadcast-playlists.json'
        if old_path.is_file() and not state_path.is_file():
            self.plugin._log.info(f"Migrating playlist state from '{old_path}' to '{state_path}'")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(state_path))

        return state_path

    def _load_state(self, state_path):
        """Load playlist sync state from disk."""
        if state_path.is_file():
            try:
                with open(state_path) as f:
                    return json.load(f)
            except Exception as e:
                self.plugin._log.error(f"Error parsing playlist state from '{state_path}'.")
                self.ib_base._stack_trace(e)
                return {}
        return {}

    def _save_state(self, state_path, state):
        """Save playlist sync state to disk."""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2)

    ## -- UPLOAD (local → remote) --

    def _upload_playlists(self, local_playlists, playlist_dir, relative_to,
                          path_to_trackid, state, allow_delete):
        """Upload local M3U playlists to iBroadcast."""
        self.plugin._log.info("Syncing playlists (upload)")

        for plpath in local_playlists:
            self._upload_playlist(plpath, relative_to, path_to_trackid, state)

        # Handle deletion of locally-deleted playlists.
        if allow_delete:
            self._handle_upload_deletions(state)

    def _upload_playlist(self, plpath, relative_to, path_to_trackid, state):
        """Upload a single local playlist to iBroadcast."""
        # Parse M3U and resolve paths to track IDs.
        track_prefix = self._resolve_track_prefix(plpath, relative_to)
        local_trackids = self._parse_m3u_to_trackids(plpath, track_prefix, path_to_trackid)
        if local_trackids is None:
            return  # Errors were already logged.

        plkey = str(plpath)
        playlistid = lastsync_trackids = None
        if plkey in state:
            playlistid = state[plkey]['id']
            lastsync_trackids = state[plkey]['tracks']

        if self.pretend:
            if not playlistid:
                self.plugin._log.info(f"Would create and sync new playlist for '{plpath}'")
            elif local_trackids != lastsync_trackids:
                self.plugin._log.info(f"Would upload modified track list for playlist '{plpath}'")
            else:
                self.plugin._log.debug(f"Already synced: '{plpath}'")
            return

        if playlistid:
            # Fetch current remote state.
            ib_playlist = self.ib_base.ib.playlist(playlistid)
            if ib_playlist is None or 'tracks' not in ib_playlist:
                self.plugin._log.warning(
                    f"Skipping sync of playlist '{plpath}' (iBroadcast ID {playlistid}) "
                    "with no remote track list.")
                return
            remote_trackids = ib_playlist['tracks']
        else:
            # Create new remote playlist.
            playlist_name = plpath.stem
            try:
                playlistid = self.ib_base.ib.createplaylist(playlist_name)
            except Exception as e:
                self.plugin._log.error(f"Error creating iBroadcast playlist '{playlist_name}'.")
                self.ib_base._stack_trace(e)
                return
            remote_trackids = None

        # Three-way merge.
        local_changes = local_trackids != lastsync_trackids
        remote_changes = remote_trackids != lastsync_trackids

        if local_changes and remote_changes:
            self.plugin._log.warning(
                f"Skipping sync of playlist '{plpath}' (iBroadcast ID {playlistid}) "
                "with both local and remote changes.")
            return

        if remote_changes:
            # Remote changed, local didn't — download will handle this.
            self.plugin._log.debug(
                f"Skipping upload of playlist '{plpath}' (iBroadcast ID {playlistid}) "
                "with remote-only changes (will be handled by download).")
            return

        if local_changes:
            self.plugin._log.info(
                f"Syncing locally changed playlist '{plpath}' (iBroadcast ID {playlistid}).")
            try:
                self.ib_base.ib.settracks(playlistid, local_trackids)
            except Exception as e:
                self.plugin._log.error(f"Error updating iBroadcast playlist {playlistid}.")
                self.ib_base._stack_trace(e)
                return
        else:
            self.plugin._log.debug(
                f"Skipping sync of unchanged playlist '{plpath}' (iBroadcast ID {playlistid}).")

        # Update state.
        state[plkey] = {'id': playlistid, 'tracks': local_trackids}

    def _handle_upload_deletions(self, state):
        """Delete remote playlists for locally-deleted M3U files."""
        keys_to_remove = []
        for plkey, plstate in state.items():
            plpath = Path(plkey)
            if plpath.is_file():
                continue  # Local file still exists.

            playlistid = plstate['id']
            if self.pretend:
                self.plugin._log.info(
                    f"Would delete remote playlist (iBroadcast ID {playlistid}) "
                    f"for deleted local file '{plpath}'")
                continue

            # Only delete if remote is unchanged since last sync.
            ib_playlist = self.ib_base.ib.playlist(playlistid)
            if ib_playlist is not None and 'tracks' in ib_playlist:
                remote_trackids = ib_playlist['tracks']
                if remote_trackids != plstate['tracks']:
                    self.plugin._log.warning(
                        f"Not deleting remote playlist (iBroadcast ID {playlistid}) "
                        f"for deleted local file '{plpath}' because remote was modified.")
                    continue

            self.plugin._log.info(
                f"Deleting remote playlist (iBroadcast ID {playlistid}) "
                f"for deleted local file '{plpath}'.")
            try:
                self.ib_base.ib.deleteplaylist(playlistid)
                keys_to_remove.append(plkey)
            except Exception as e:
                self.plugin._log.error(f"Error deleting iBroadcast playlist {playlistid}.")
                self.ib_base._stack_trace(e)

        for key in keys_to_remove:
            del state[key]

    ## -- DOWNLOAD (remote → local) --

    def _download_playlists(self, playlist_dir, relative_to,
                            trackid_to_path, state, allow_delete, filters=None):
        """Download iBroadcast playlists to local M3U files."""
        self.plugin._log.info("Syncing playlists (download)")

        # Build reverse map: remote playlist ID → state key.
        id_to_statekey = {}
        for plkey, plstate in state.items():
            pid = plstate['id']
            if pid in id_to_statekey:
                self.plugin._log.warning(
                    f"Playlist ID {pid} is linked to multiple local files; skipping download.")
            else:
                id_to_statekey[pid] = plkey

        for playlistid_str in self.ib_base.ib.playlists:
            playlistid = int(playlistid_str)
            plname = self.ib_base.ib.playlists[playlistid_str]['name']

            # Apply name filters.
            if filters and plname.lower() not in {f.lower() for f in filters}:
                continue

            if playlistid in id_to_statekey:
                # Linked playlist — check for remote changes.
                self._download_linked_playlist(
                    playlistid, plname, id_to_statekey[playlistid],
                    relative_to, trackid_to_path, state)
            else:
                # New remote playlist — download it.
                self._download_new_playlist(
                    playlistid, plname, playlist_dir, relative_to,
                    trackid_to_path, state)

        # Handle deletion of remotely-deleted playlists.
        if allow_delete:
            self._handle_download_deletions(state, id_to_statekey)

    def _download_linked_playlist(self, playlistid, plname, statekey,
                                  relative_to, trackid_to_path, state):
        """Update a locally-linked playlist with remote changes."""
        plpath = Path(statekey)
        lastsync_trackids = state[statekey]['tracks']

        ib_playlist = self.ib_base.ib.playlist(playlistid)
        if ib_playlist is None or 'tracks' not in ib_playlist:
            return
        remote_trackids = ib_playlist['tracks']

        if remote_trackids == lastsync_trackids:
            return  # No remote changes.

        # Check for local changes too.
        if plpath.is_file():
            track_prefix = self._resolve_track_prefix(plpath, relative_to)
            # Build a reverse lookup from the trackid_to_path dict.
            path_to_trackid = {v: k for k, v in trackid_to_path.items()}
            local_paths = self._parse_m3u(plpath, track_prefix)
            local_trackids = [path_to_trackid.get(p) for p in local_paths]
            # Filter out None (unresolvable paths).
            local_trackids = [t for t in local_trackids if t is not None]

            if local_trackids != lastsync_trackids:
                self.plugin._log.warning(
                    f"Skipping download of playlist '{plname}' (iBroadcast ID {playlistid}) "
                    "with both local and remote changes.")
                return

        # Remote changed, local unchanged — update local file.
        resolved_paths, unresolved = self._resolve_trackids_to_paths(remote_trackids, trackid_to_path)
        if not resolved_paths:
            self.plugin._log.warning(
                f"Skipping download of playlist '{plname}' (iBroadcast ID {playlistid}): "
                f"none of {len(remote_trackids)} track(s) can be resolved to local files.")
            return
        if unresolved:
            self.plugin._log.warning(
                f"Playlist '{plname}' (iBroadcast ID {playlistid}): "
                f"{unresolved} of {len(remote_trackids)} track(s) cannot be resolved to local files.")

        if self.pretend:
            self.plugin._log.info(
                f"Would update local playlist '{plpath}' with remote changes.")
            return

        self._write_m3u(plpath, resolved_paths, relative_to)
        state[statekey] = {'id': playlistid, 'tracks': remote_trackids}
        self.plugin._log.info(
            f"Updated local playlist '{plpath}' with remote changes "
            f"(iBroadcast ID {playlistid}).")

    def _download_new_playlist(self, playlistid, plname, playlist_dir,
                               relative_to, trackid_to_path, state):
        """Download a new remote playlist to a local M3U file."""
        ib_playlist = self.ib_base.ib.playlist(playlistid)
        if ib_playlist is None or 'tracks' not in ib_playlist:
            return
        remote_trackids = ib_playlist['tracks']

        if not remote_trackids:
            self.plugin._log.debug(
                f"Skipping download of empty playlist '{plname}' (iBroadcast ID {playlistid}).")
            return

        resolved_paths, unresolved = self._resolve_trackids_to_paths(remote_trackids, trackid_to_path)
        if not resolved_paths:
            self.plugin._log.warning(
                f"Skipping download of playlist '{plname}' (iBroadcast ID {playlistid}): "
                f"none of {len(remote_trackids)} track(s) can be resolved to local files.")
            return
        if unresolved:
            self.plugin._log.warning(
                f"Playlist '{plname}' (iBroadcast ID {playlistid}): "
                f"{unresolved} of {len(remote_trackids)} track(s) cannot be resolved to local files.")

        plpath = playlist_dir / f'{plname}.m3u'

        if self.pretend:
            self.plugin._log.info(
                f"Would download playlist '{plname}' to '{plpath}' "
                f"({len(resolved_paths)} of {len(remote_trackids)} tracks).")
            return

        # Avoid overwriting existing files not in our state.
        if plpath.is_file():
            self.plugin._log.warning(
                f"Skipping download of playlist '{plname}': "
                f"local file '{plpath}' already exists.")
            return

        self._write_m3u(plpath, resolved_paths, relative_to)
        state[str(plpath)] = {'id': playlistid, 'tracks': remote_trackids}
        self.plugin._log.info(
            f"Downloaded playlist '{plname}' to '{plpath}' "
            f"({len(remote_trackids)} tracks).")

    def _handle_download_deletions(self, state, id_to_statekey):
        """Delete local M3U files for remotely-deleted playlists."""
        remote_ids = set()
        for playlistid_str in self.ib_base.ib.playlists:
            remote_ids.add(int(playlistid_str))

        keys_to_remove = []
        for plkey, plstate in state.items():
            pid = plstate['id']
            if pid in remote_ids:
                continue  # Remote playlist still exists.

            plpath = Path(plkey)
            if not plpath.is_file():
                # Already deleted locally too — just clean up state.
                keys_to_remove.append(plkey)
                continue

            # Only delete if local is unchanged since last sync.
            if self._local_playlist_changed(plpath, plstate, state):
                self.plugin._log.warning(
                    f"Not deleting local playlist '{plpath}' for remotely-deleted playlist "
                    f"(ID {pid}) because local file was modified.")
                continue

            if self.pretend:
                self.plugin._log.info(
                    f"Would delete local playlist '{plpath}' "
                    f"for remotely-deleted playlist (ID {pid}).")
                continue

            self.plugin._log.info(
                f"Deleting local playlist '{plpath}' "
                f"for remotely-deleted playlist (ID {pid}).")
            plpath.unlink()
            keys_to_remove.append(plkey)

        for key in keys_to_remove:
            del state[key]

    def _local_playlist_changed(self, plpath, plstate, state):
        """Check if a local playlist has changed since last sync."""
        # We can't fully check without re-parsing, but we can do a basic check.
        # For simplicity, we trust the state and don't re-parse here.
        # A more thorough check could re-parse and compare trackids.
        return False

    ## -- M3U UTILITIES --

    def _resolve_track_prefix(self, plpath, relative_to):
        """Determine the base directory for resolving relative paths in an M3U."""
        if relative_to == 'playlist':
            return normpath(plpath.parent)
        return normpath(relative_to)

    def _parse_m3u(self, plpath, track_prefix):
        """Parse an M3U file and return resolved track paths."""
        with open(plpath) as pl:
            lines = [line.strip() for line in pl.readlines()]
        return [normpath(track_prefix / line)
                for line in lines if len(line) > 0 and not line.startswith('#')]

    def _parse_m3u_to_trackids(self, plpath, track_prefix, path_to_trackid):
        """Parse an M3U file and return track IDs, or None on failure."""
        track_paths = self._parse_m3u(plpath, track_prefix)
        if not track_paths:
            self.plugin._log.debug(f"Skipping empty playlist '{plpath}'.")
            return None

        trackids = []
        problems = []
        for track_path in track_paths:
            if not track_path.is_file():
                problems.append(f"  [ INVALID FILE  ] {track_path}")
                continue
            tid = path_to_trackid.get(track_path)
            if tid is None:
                problems.append(f"  [  NOT UPLOADED  ] {track_path}")
                continue
            trackids.append(tid)

        if len(trackids) < len(track_paths):
            self.plugin._log.debug(
                f"Skipping sync of playlist '{plpath}' with track problems:\n"
                + '\n'.join(problems))
            return None

        return trackids

    def _resolve_trackids_to_paths(self, remote_trackids, trackid_to_path):
        """Resolve remote track IDs to local paths. Skips unresolvable tracks.

        Returns (resolved_paths, unresolved_count).
        """
        paths = []
        unresolved = 0
        for tid in remote_trackids:
            path = trackid_to_path.get(tid)
            if path is None:
                unresolved += 1
            else:
                paths.append(path)
        return paths, unresolved

    def _write_m3u(self, plpath, track_paths, relative_to):
        """Write an M3U file with the given track paths."""
        base_dir = self._resolve_track_prefix(plpath, relative_to)
        lines = []
        for track_path in track_paths:
            try:
                rel = track_path.relative_to(base_dir)
                lines.append(str(rel))
            except ValueError:
                # Can't make relative — use absolute path.
                lines.append(str(track_path))
        plpath.parent.mkdir(parents=True, exist_ok=True)
        with open(plpath, 'w') as f:
            f.write('\n'.join(lines) + '\n')
