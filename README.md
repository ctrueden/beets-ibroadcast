# beets iBroadcast Plugin

This plugin lets you sync your [beets](https://beets.io) library
to the [iBroadcast](https://www.ibroadcast.com/) streaming service.
Supported operations include:

* ib-upload - upload tracks from beets to iBroadcast
* ib-playlist - sync playlists bidirectionally

## Setup

1. Install the plugin into your local environment with:
   ```
   pip install beets-ibroadcast
   ```

2. Enable the plugin by adding `ibroadcast` to your `plugins:` section
   in your beets config file.

3. The first time you run the plugin, it will prompt you to authorize via a
   device code. Visit the URL shown and enter the code to grant access.
   Tokens are saved to `~/.config/beets/ibroadcast-tokens.json` and reused
   automatically on subsequent runs.

   Optionally, if you'd like to upload newly imported items from your library,
   set `auto` to true:

   ```yaml
   ibroadcast:
     auto: true
   ```

## Commands

### `beet ib-upload [query]`

Upload tracks matching the query to iBroadcast and sync tags.

**Alias:** `beet ibroadcast` (for backwards compatibility)

**Flags:**
- `-v, --version` — show plugin version
- `-f, --force` — upload all matched files, even if already uploaded
- `-p, --pretend` — report which files would be uploaded without uploading

**Examples:**
```
beet ib-upload                         # upload entire library
beet ib-upload artist:Offspring        # upload matching tracks
beet ibroadcast -p album:Americana     # pretend (backward-compat alias)
```

### `beet ib-playlist [playlist_name...]`

Sync playlists between local M3U files and iBroadcast.

**Alias:** `beet ib-pl`

**Flags:**
- `--upload` — push local M3U playlists to iBroadcast only
- `--download` — pull iBroadcast playlists to local M3U only
- `--sync` — bidirectional sync (default if no direction flag)
- `--delete` — propagate deletions (opt-in)
- `-p, --pretend` — report what would happen without doing it

**Examples:**
```
beet ib-playlist -p                     # preview bidirectional sync
beet ib-playlist --upload               # push all local playlists
beet ib-playlist --download             # pull all remote playlists
beet ib-playlist --upload Favorites     # push only "Favorites" playlist
beet ib-playlist --sync --delete        # full sync with deletion
```

**Positional arguments** filter by playlist name (case-insensitive).

## FAQ

### How do I know this plugin won't destroy my iBroadcast collection?

You don't. But it tries to be careful and guards against many edge cases.
If you want to see what the plugin will do without actually doing it, you can
pass the `-p` (for "pretend") flag:

```
beet ib-upload -p
beet ib-playlist -p
```

I recommend starting with a small query, to get a feel for how it works. E.g.:

```
beet ib-upload -p artist:Offspring album:Americana
```

If you like what you see, do it again without `-p` and see how it goes.
Once you have some confidence in the tool, you can go nuts with larger queries.

### How does beets-ibroadcast avoid redundant uploads?

When a track is uploaded, the plugin attaches `ib_uploadtime` and `ib_trackid`
flexible attributes to the track. The next time that track is considered for
upload, these attributes are examined: if the track's `mtime` is older than its
`ib_uploadtime`, the track is assumed to be up to date, and the upload is
skipped.

For tracks where `mtime` is newer, the track is uploaded again, and the
previous track ID is trashed. As such, obsolete previous versions of tracks
will appear in your iBroadcast trash until it is emptied.

Regardless: before uploading, the track's MD5 checksum is computed, and if the
server already has a track with that checksum, the upload is skipped. As such,
if you upload tracks with a different uploader than beets-ibroadcast, they will
still be skipped (although as of this writing, beets-ibroadcast will read such
files to compute their checksums every time they match a query, which will
impact performance).

You can use the `-f` flag to skip these checks and force reupload of tracks.

### How are tags synced?

This plugin syncs tags on the iBroadcast side with the `usertags` flexible
attribute, in a way compatible with the [usertag plugin][1].

If you modify a track's tags locally (e.g. via `beet addtag`), those changes
will be synced to iBroadcast. If you modify a track's tags remotely (e.g. via
the iBroadcast website), those changes will be synced to the beets database.

In order to know whether a track's tags were changed locally, remotely, or
both since the last sync, the current state of the tags is stored in an
`ib_tagids` flexible attribute upon each successful sync. This strategy makes
it clear whether, for example, a tag that exists remotely but not locally was
deleted locally versus added remotely; as such, there cannot be tag conflicts.

See the [usertag plugin documentation][1] for details on working with tags in
your beets database.

### How are playlists synced?

The `ib-playlist` command syncs playlists between local M3U files and
iBroadcast. It supports three modes:

- **Upload** (`--upload`): Push local M3U playlists to iBroadcast.
- **Download** (`--download`): Pull iBroadcast playlists to local M3U files.
- **Sync** (default): Bidirectional — upload local changes and download
  remote changes.

Playlist tracks are matched by their `ib_trackid` attribute, so tracks must
be uploaded to iBroadcast (via `ib-upload`) before they can be synced as
part of a playlist.

**Three-way merge:** The plugin uses a state file to detect whether changes
occurred locally, remotely, or both. If only one side changed, those changes
are applied. If both sides changed, the plugin attempts a three-way merge:

- **Non-conflicting changes** (e.g., local adds tracks at one position, remote
  adds different tracks at another) are merged automatically. The merged result
  is written to the local M3U and pushed to iBroadcast.
- **Conflicting changes** (e.g., both sides modify the same region differently)
  produce an M3U file with git-style conflict markers:
  ```
  #<<<<<<< local
  path/to/local_track.mp3
  #=======
  path/to/remote_track.mp3
  #>>>>>>> remote
  ```
  The markers are `#`-prefixed so the file remains a valid M3U (players treat
  `#` lines as comments). Edit the file to resolve the conflicts, then run
  `ib-playlist` again to upload your resolution.

**Deletion handling:** By default, deletions are not propagated. Pass
`--delete` to enable deletion propagation. A deletion is only applied if the
other side is unchanged since last sync.

The playlist state file is stored at
`~/.config/beets/ibroadcast-playlists.json` by default. If you previously
used beets-ibroadcast, the old state file (`.ibroadcast-playlists.json` in
your beets library directory) will be automatically migrated on first run.

You can configure a custom state file path:

```yaml
ibroadcast:
  playlist_state: /path/to/my-playlist-state.json
```

Playlist files are discovered from the directory configured by the
[playlist plugin][2]:

```yaml
playlist:
  playlist_dir: /path/to/playlists
```

See the [playlist plugin documentation][2] for details on configuring
`playlist_dir` and `relative_to`.

### How can I get more details about why things go wrong?

You can tell beets to be more verbose in its output using the `-v` flag. E.g.:

```
beet -v ib-upload usertags:favorites
beet -v ib-playlist
```

This will cause the ibroadcast plugin to emit more detailed debugging messages.

[1]: https://github.com/igordertigor/beets-usertag
[2]: https://beets.readthedocs.io/en/stable/plugins/playlist.html
