[![Build Status](https://api.travis-ci.com/ctrueden/beets-ibroadcast.svg?branch=master)](https://travis-ci.com/github/ctrueden/beets-ibroadcast)
[![Coverage Status](https://coveralls.io/repos/github/ctrueden/beets-ibroadcast/badge.svg?branch=master)](https://coveralls.io/github/ctrueden/beets-ibroadcast?branch=master)

# Beets iBroadcast Plugin

This plugin lets you upload music from your [beets](https://beets.io)
library to the [iBroadcast](https://www.ibroadcast.com/) streaming service.

## Setup

1. Install the plugin into your local environment with:
   ```
   pip install beets-ibroadcast
   ```

2. Enable the plugin by adding `ibroadcast` to your `plugins:` section
   in your beets config file.

3. Configure your iBroadcast credentials:
   ```yaml
   ibroadcast:
     username: <your email address>
     password: <your password>
   ```
   Be sure to put quotes around your password if it includes any special characters.

## Usage

```
beet ibroadcast <query>
```

- All tracks matching the query are uploaded as needed.
- [Usertags][1] are synced with the tags on iBroadcast.
- Syncing of iBroadcast playlists will come later.

## FAQ

### How do I know this plugin won't destroy my iBroadcast collection?

You don't. But it tries to be careful and guards against many edge cases.
If you want to see what the plugin will do without actually doing it, you can
pass the `-p` (for "pretend") flag:

```
beet ibroadcast -p
```

I recommend starting with a small query, to get a feel for how it works. E.g.:

```
beet ibroadcast -p artist:Offspring album:Americana
```

And then if you like what you see, do it again with `-p` and see how it goes.
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
will synced to iBroadcast. If you modify a track's tags remotely (e.g. via the
iBroadcast web interface), those changes will be synced to the beets database.

In order to know whether a track's tags were changed locally, remotely, or
both since the last sync, the current state of the tags is stored in an
`ib_tagids` flexible attribute upon each successful sync. This strategy makes
it clear whether, for example, a tag that exists remotely but not locally was
deleted locally versus added remotely; as such, there cannot be tag conflicts.

See the [usertag plugin documentation][1] for details on working with tags in
your beets database.

### How can I get more details about why things go wrong?

You can tell beets to be more verbose in its output using the `-v` flag. E.g.:

```
beet -v ibroadcast usertags:favorites
```

This will cause the ibroadcast plugin to emit more detailed debugging messages.

[1]: https://github.com/igordertigor/beets-usertag
