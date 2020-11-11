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

### How does beets-ibroadcast avoid redundant uploads?

- Tracks previously uploaded by beets-ibroadcast will already have
  `ib_uploadtime` and `ib_trackid` flexible attributes attached; if the track's
  `mtime` is older than its `ib_uploadtime`, the track is assumed to be up to
  date, and the upload is skipped.

- For tracks where `mtime` is newer, the track is uploaded again, and the
  previous track ID is trashed. As such, obsolete previous versions of tracks
  will appear in your iBroadcast trash until it is emptied.

- Regardless: before uploading, the track's MD5 checksum is computed, and if
  the server already has a track with that checksum, the upload is skipped. As
  such, if you upload tracks with a different uploader than beets-ibroadcast,
  they will still be skipped (although as of this writing, beets-ibroadcast
  will read such files to compute their checksums every time they match a
  query, which will impact performance).

- You can use the `-f` flag to skip these checks and force reupload of tracks.

### How are tags synced?

This plugin syncs tags on the iBroadcast side with the `usertags` flexible
attribute, in a way compatible with the [usertag plugin][1].
If you modify a track's tags locally (e.g. via `beet addtag`), those changes
will synced to iBroadcast. If you modify a track's tags remotely (e.g. via the
iBroadcast web interface), those changes will be synced to the beets database.

See the [usertag documentation](https://github.com/igordertigor/beets-usertag)
for details on working with tags in your beets database.

[1]: https://github.com/igordertigor/beets-usertag
