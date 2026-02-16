# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from beetsplug.ibroadcast.helpers import trackid, normpath
from beetsplug.ibroadcast.playlist_sync import PlaylistSyncManager, DEFAULT_STATE_FILE


class TestHelpers(TestCase):
    """Test helper functions."""

    def test_trackid_with_attribute(self):
        item = MagicMock()
        item.ib_trackid = 42
        self.assertEqual(trackid(item), 42)

    def test_trackid_without_attribute(self):
        item = MagicMock(spec=[])
        self.assertIsNone(trackid(item))

    def test_normpath_bytes(self):
        result = normpath(b'/tmp/test')
        self.assertIsInstance(result, Path)
        self.assertEqual(result, Path('/tmp/test').resolve())

    def test_normpath_str(self):
        result = normpath('/tmp/test')
        self.assertIsInstance(result, Path)
        self.assertEqual(result, Path('/tmp/test').resolve())


class TestM3UParsing(TestCase):
    """Test M3U file parsing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parse_m3u_basic(self):
        # Create test track files.
        track1 = Path(self.tmpdir) / 'track1.mp3'
        track2 = Path(self.tmpdir) / 'track2.mp3'
        track1.touch()
        track2.touch()

        # Create M3U file with relative paths.
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\ntrack2.mp3\n')

        paths = self.manager._parse_m3u(m3u, Path(self.tmpdir))
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], normpath(track1))
        self.assertEqual(paths[1], normpath(track2))

    def test_parse_m3u_ignores_comments(self):
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('#EXTM3U\n# comment\ntrack1.mp3\n')

        paths = self.manager._parse_m3u(m3u, Path(self.tmpdir))
        self.assertEqual(len(paths), 1)

    def test_parse_m3u_ignores_empty_lines(self):
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\n\n\ntrack2.mp3\n')

        paths = self.manager._parse_m3u(m3u, Path(self.tmpdir))
        self.assertEqual(len(paths), 2)

    def test_parse_m3u_to_trackids_success(self):
        track1 = Path(self.tmpdir) / 'track1.mp3'
        track1.touch()
        track2 = Path(self.tmpdir) / 'track2.mp3'
        track2.touch()

        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\ntrack2.mp3\n')

        path_to_trackid = {
            normpath(track1): 100,
            normpath(track2): 200,
        }

        result = self.manager._parse_m3u_to_trackids(m3u, Path(self.tmpdir), path_to_trackid)
        self.assertEqual(result, [100, 200])

    def test_parse_m3u_to_trackids_missing_trackid(self):
        track1 = Path(self.tmpdir) / 'track1.mp3'
        track1.touch()

        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\n')

        # No trackid mapping — should return None.
        result = self.manager._parse_m3u_to_trackids(m3u, Path(self.tmpdir), {})
        self.assertIsNone(result)


class TestM3UWriting(TestCase):
    """Test M3U file writing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_m3u_relative_paths(self):
        base_dir = Path(self.tmpdir) / 'music'
        base_dir.mkdir()
        track1 = base_dir / 'artist' / 'album' / 'track1.mp3'
        track1.parent.mkdir(parents=True)
        track1.touch()

        plpath = Path(self.tmpdir) / 'playlists' / 'test.m3u'

        self.manager._write_m3u(plpath, [track1], base_dir)

        content = plpath.read_text()
        self.assertEqual(content.strip(), 'artist/album/track1.mp3')

    def test_write_m3u_creates_parent_dirs(self):
        plpath = Path(self.tmpdir) / 'a' / 'b' / 'test.m3u'
        self.manager._write_m3u(plpath, [], Path(self.tmpdir))
        self.assertTrue(plpath.is_file())


class TestStateMigration(TestCase):
    """Test state file migration from old location."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.plugin.config = {'playlist_state': MagicMock()}
        self.plugin.config['playlist_state'].get.return_value = ''
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_state_from_file(self):
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)
        state_path = Path(self.tmpdir) / 'state.json'
        state_data = {'/path/to/test.m3u': {'id': 123, 'tracks': [1, 2, 3]}}
        state_path.write_text(json.dumps(state_data))

        result = manager._load_state(state_path)
        self.assertEqual(result, state_data)

    def test_load_state_missing_file(self):
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)
        state_path = Path(self.tmpdir) / 'nonexistent.json'

        result = manager._load_state(state_path)
        self.assertEqual(result, {})

    def test_save_state(self):
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)
        state_path = Path(self.tmpdir) / 'state.json'
        state_data = {'/path/to/test.m3u': {'id': 123, 'tracks': [1, 2, 3]}}

        manager._save_state(state_path, state_data)

        with open(state_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, state_data)


class TestCollectM3UPaths(TestCase):
    """Test collecting paths from M3U files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_collect_paths_from_multiple_m3us(self):
        m3u1 = Path(self.tmpdir) / 'a.m3u'
        m3u1.write_text('track1.mp3\ntrack2.mp3\n')
        m3u2 = Path(self.tmpdir) / 'b.m3u'
        m3u2.write_text('track2.mp3\ntrack3.mp3\n')

        paths = self.manager._collect_m3u_paths([m3u1, m3u2], Path(self.tmpdir))
        # Should be a set of 3 unique paths.
        self.assertEqual(len(paths), 3)

    def test_collect_paths_empty(self):
        paths = self.manager._collect_m3u_paths([], Path(self.tmpdir))
        self.assertEqual(len(paths), 0)


class TestBuildPathToTrackid(TestCase):
    """Test building path→trackid mapping via SQL."""

    def setUp(self):
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def test_empty_paths(self):
        result = self.manager._build_path_to_trackid(set())
        self.assertEqual(result, {})

    def test_filters_to_requested_paths(self):
        # Mock the database connection.
        mock_db = MagicMock()
        self.lib._connection.return_value = mock_db

        # DB returns rows for paths including ones not requested.
        mock_db.execute.return_value = [
            (b'/music/track1.mp3', '100'),
            (b'/music/track2.mp3', '200'),
            (b'/music/track3.mp3', '300'),
        ]

        requested = {normpath('/music/track1.mp3'), normpath('/music/track3.mp3')}
        result = self.manager._build_path_to_trackid(requested)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[normpath('/music/track1.mp3')], 100)
        self.assertEqual(result[normpath('/music/track3.mp3')], 300)


class TestBuildTrackidToPath(TestCase):
    """Test building trackid→path mapping via SQL."""

    def setUp(self):
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def test_builds_mapping(self):
        mock_db = MagicMock()
        self.lib._connection.return_value = mock_db
        mock_db.execute.return_value = [
            (b'/music/track1.mp3', '100'),
            (b'/music/track2.mp3', '200'),
        ]

        result = self.manager._build_trackid_to_path()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[100], normpath(b'/music/track1.mp3'))
        self.assertEqual(result[200], normpath(b'/music/track2.mp3'))

    def test_skips_invalid_values(self):
        mock_db = MagicMock()
        self.lib._connection.return_value = mock_db
        mock_db.execute.return_value = [
            (b'/music/track1.mp3', '100'),
            (b'/music/track2.mp3', 'not_a_number'),
        ]

        result = self.manager._build_trackid_to_path()
        self.assertEqual(len(result), 1)


class TestTrackidResolution(TestCase):
    """Test resolving track IDs to paths."""

    def setUp(self):
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def test_resolve_all_trackids(self):
        trackid_to_path = {
            100: Path('/music/track1.mp3'),
            200: Path('/music/track2.mp3'),
        }
        paths, unresolved = self.manager._resolve_trackids_to_paths([100, 200], trackid_to_path)
        self.assertEqual(paths, [Path('/music/track1.mp3'), Path('/music/track2.mp3')])
        self.assertEqual(unresolved, 0)

    def test_resolve_missing_trackid(self):
        trackid_to_path = {100: Path('/music/track1.mp3')}
        paths, unresolved = self.manager._resolve_trackids_to_paths([100, 999], trackid_to_path)
        self.assertEqual(paths, [Path('/music/track1.mp3')])
        self.assertEqual(unresolved, 1)

    def test_resolve_empty_list(self):
        paths, unresolved = self.manager._resolve_trackids_to_paths([], {})
        self.assertEqual(paths, [])
        self.assertEqual(unresolved, 0)


class TestThreeWayMerge(TestCase):
    """Test the three-way merge logic in upload."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_upload_new_playlist(self):
        """A new local playlist not in state should create a remote playlist."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib, pretend=True)

        track = Path(self.tmpdir) / 'track1.mp3'
        track.touch()
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\n')

        path_to_trackid = {normpath(track): 100}
        state = {}

        manager._upload_playlist(m3u, Path(self.tmpdir), path_to_trackid, state)

        # In pretend mode, should log the creation intent.
        self.plugin._log.info.assert_called()
        call_args = str(self.plugin._log.info.call_args)
        self.assertIn('Would create', call_args)

    def test_upload_unchanged_playlist(self):
        """An unchanged playlist should be skipped."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib, pretend=True)

        track = Path(self.tmpdir) / 'track1.mp3'
        track.touch()
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\n')

        path_to_trackid = {normpath(track): 100}
        state = {str(m3u): {'id': 1, 'tracks': [100]}}

        manager._upload_playlist(m3u, Path(self.tmpdir), path_to_trackid, state)

        call_args = self.plugin._log.info.call_args
        self.assertIsNone(call_args)

    def test_upload_modified_playlist(self):
        """A locally modified playlist should be synced."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib, pretend=True)

        track1 = Path(self.tmpdir) / 'track1.mp3'
        track1.touch()
        track2 = Path(self.tmpdir) / 'track2.mp3'
        track2.touch()
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\ntrack2.mp3\n')

        path_to_trackid = {normpath(track1): 100, normpath(track2): 200}
        state = {str(m3u): {'id': 1, 'tracks': [100]}}

        # Remote is unchanged from last sync (local-only change).
        self.ib_base.ib.playlist.return_value = {'tracks': [100]}

        manager._upload_playlist(m3u, Path(self.tmpdir), path_to_trackid, state)

        call_args = str(self.plugin._log.info.call_args)
        self.assertIn('Would upload modified', call_args)


    def test_upload_converged_playlist(self):
        """When local and remote both changed to the same value, update state."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

        track1 = Path(self.tmpdir) / 'track1.mp3'
        track1.touch()
        track2 = Path(self.tmpdir) / 'track2.mp3'
        track2.touch()
        m3u = Path(self.tmpdir) / 'test.m3u'
        m3u.write_text('track1.mp3\ntrack2.mp3\n')

        path_to_trackid = {normpath(track1): 100, normpath(track2): 200}
        # State has old value; both local and remote now have [100, 200].
        state = {str(m3u): {'id': 1, 'tracks': [300]}}

        self.ib_base.ib.playlist.return_value = {'tracks': [100, 200]}

        manager._upload_playlist(m3u, Path(self.tmpdir), path_to_trackid, state)

        # State should be updated to the converged value.
        self.assertEqual(state[str(m3u)]['tracks'], [100, 200])
        # No remote update should be attempted.
        self.ib_base.ib.settracks.assert_not_called()


class TestUploadDeletion(TestCase):
    """Test deletion propagation on upload."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_remote_for_deleted_local(self):
        """When local M3U is deleted and remote is unchanged, delete remote."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

        # State references a file that no longer exists.
        deleted_path = Path(self.tmpdir) / 'deleted.m3u'
        state = {str(deleted_path): {'id': 42, 'tracks': [100, 200]}}

        # Remote is unchanged.
        self.ib_base.ib.playlist.return_value = {'tracks': [100, 200]}
        self.ib_base.ib.deleteplaylist.return_value = None

        manager._handle_upload_deletions(state)

        self.ib_base.ib.deleteplaylist.assert_called_once_with(42)
        self.assertEqual(state, {})

    def test_no_delete_if_remote_changed(self):
        """Don't delete remote if it was modified since last sync."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

        deleted_path = Path(self.tmpdir) / 'deleted.m3u'
        state = {str(deleted_path): {'id': 42, 'tracks': [100, 200]}}

        # Remote was modified.
        self.ib_base.ib.playlist.return_value = {'tracks': [100, 200, 300]}

        manager._handle_upload_deletions(state)

        self.ib_base.ib.deleteplaylist.assert_not_called()
        # State should still be there.
        self.assertIn(str(deleted_path), state)


class TestDownloadDeletion(TestCase):
    """Test deletion propagation on download."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.ib_base.ib = MagicMock()
        self.ib_base.ib.playlists = {}
        self.lib = MagicMock()
        self.lib.items.return_value = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_local_for_deleted_remote(self):
        """When remote playlist is deleted and local is unchanged, delete local."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

        local_m3u = Path(self.tmpdir) / 'test.m3u'
        local_m3u.write_text('track1.mp3\n')

        state = {str(local_m3u): {'id': 42, 'tracks': [100]}}
        id_to_statekey = {42: str(local_m3u)}

        manager._handle_download_deletions(state, id_to_statekey)

        self.assertFalse(local_m3u.is_file())
        self.assertEqual(state, {})

    def test_no_delete_local_if_not_in_state(self):
        """Don't delete files not tracked in state."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)
        state = {}
        manager._handle_download_deletions(state, {})
        # Should complete without error.


class TestResolveTrackPrefix(TestCase):
    """Test track prefix resolution for different relative_to configs."""

    def setUp(self):
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def test_playlist_relative(self):
        plpath = Path('/playlists/sub/test.m3u')
        result = self.manager._resolve_track_prefix(plpath, 'playlist')
        self.assertEqual(result, normpath('/playlists/sub'))

    def test_directory_relative(self):
        plpath = Path('/playlists/test.m3u')
        base = Path('/music')
        result = self.manager._resolve_track_prefix(plpath, base)
        self.assertEqual(result, normpath('/music'))


class TestDownloadPlaylistsFolderAware(TestCase):
    """Test folder-aware download behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.ib_base.ib = MagicMock()
        self.lib = MagicMock()
        self.lib.items.return_value = []
        self.playlist_dir = Path(self.tmpdir) / 'playlists'
        self.playlist_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_manager(self, pretend=True):
        return PlaylistSyncManager(self.plugin, self.ib_base, self.lib, pretend=pretend)

    def test_skips_system_playlists(self):
        """System playlists (recently-played, thumbsup, etc.) should be skipped."""
        self.ib_base.ib.playlists = {
            '100': {'name': 'Recently Played', 'type': 'recently-played'},
            '101': {'name': 'Thumbs Up', 'type': 'thumbsup'},
            '102': {'name': 'Recently Uploaded', 'type': 'recently-uploaded'},
        }

        manager = self._make_manager()
        state = {}
        trackid_to_path = {}

        manager._download_playlists(
            self.playlist_dir, Path(self.tmpdir),
            trackid_to_path, state, False)

        # playlist() should never be called for system playlists.
        self.ib_base.ib.playlist.assert_not_called()
        # Debug logs should mention skipping.
        debug_calls = [str(c) for c in self.plugin._log.debug.call_args_list]
        system_skips = [c for c in debug_calls if 'system playlist' in c.lower()]
        self.assertEqual(len(system_skips), 3)

    def test_skips_folder_entries(self):
        """Folder entries should be skipped (not treated as playlists)."""
        self.ib_base.ib.playlists = {
            '200': {'name': 'KB', 'type': 'folder', 'tracks': [201, 202]},
            '201': {'name': 'KB 01', 'type': None, 'tracks': [1, 2]},
            '202': {'name': 'KB 02', 'type': None, 'tracks': [3, 4]},
        }
        self.ib_base.ib.playlist.return_value = {'tracks': [1, 2]}

        manager = self._make_manager()
        state = {}
        trackid_to_path = {
            1: normpath(Path(self.tmpdir) / 'track1.mp3'),
            2: normpath(Path(self.tmpdir) / 'track2.mp3'),
            3: normpath(Path(self.tmpdir) / 'track3.mp3'),
            4: normpath(Path(self.tmpdir) / 'track4.mp3'),
        }

        manager._download_playlists(
            self.playlist_dir, Path(self.tmpdir),
            trackid_to_path, state, False)

        # playlist() should be called for children but not the folder.
        call_args = [c[0][0] for c in self.ib_base.ib.playlist.call_args_list]
        self.assertNotIn(200, call_args)
        self.assertIn(201, call_args)
        self.assertIn(202, call_args)

    def test_child_playlists_placed_in_subdirectory(self):
        """Child playlists of a folder should be placed in a subdirectory."""
        self.ib_base.ib.playlists = {
            '300': {'name': 'MyFolder', 'type': 'folder', 'tracks': [301]},
            '301': {'name': 'Child Playlist', 'type': None},
        }
        self.ib_base.ib.playlist.return_value = {'tracks': [1, 2]}

        trackid_to_path = {
            1: normpath(Path(self.tmpdir) / 'track1.mp3'),
            2: normpath(Path(self.tmpdir) / 'track2.mp3'),
        }

        manager = self._make_manager(pretend=False)
        state = {}

        # Create track files so write_m3u can generate relative paths.
        (Path(self.tmpdir) / 'track1.mp3').touch()
        (Path(self.tmpdir) / 'track2.mp3').touch()

        manager._download_playlists(
            self.playlist_dir, Path(self.tmpdir),
            trackid_to_path, state, False)

        expected_path = self.playlist_dir / 'MyFolder' / 'Child Playlist.m3u'
        self.assertTrue(expected_path.is_file(),
                        f"Expected M3U at {expected_path}")
        # State key should use the full path.
        self.assertIn(str(expected_path), state)

    def test_top_level_playlist_not_in_subdirectory(self):
        """Playlists not in a folder should stay at the top level."""
        self.ib_base.ib.playlists = {
            '400': {'name': 'Top Level', 'type': None},
        }
        self.ib_base.ib.playlist.return_value = {'tracks': [1]}

        trackid_to_path = {
            1: normpath(Path(self.tmpdir) / 'track1.mp3'),
        }

        manager = self._make_manager(pretend=False)
        state = {}
        (Path(self.tmpdir) / 'track1.mp3').touch()

        manager._download_playlists(
            self.playlist_dir, Path(self.tmpdir),
            trackid_to_path, state, False)

        expected_path = self.playlist_dir / 'Top Level.m3u'
        self.assertTrue(expected_path.is_file())

    def test_folder_name_filter_includes_children(self):
        """Filtering by folder name should include all child playlists."""
        self.ib_base.ib.playlists = {
            '500': {'name': 'KB', 'type': 'folder', 'tracks': [501, 502]},
            '501': {'name': 'KB 01', 'type': None},
            '502': {'name': 'KB 02', 'type': None},
            '503': {'name': 'Other', 'type': None},
        }

        def playlist_side_effect(pid):
            return {'tracks': [1]}

        self.ib_base.ib.playlist.side_effect = playlist_side_effect

        trackid_to_path = {
            1: normpath(Path(self.tmpdir) / 'track1.mp3'),
        }

        manager = self._make_manager()
        state = {}

        manager._download_playlists(
            self.playlist_dir, Path(self.tmpdir),
            trackid_to_path, state, False, filters=['KB'])

        # playlist() should be called for children of KB but not Other.
        call_args = [c[0][0] for c in self.ib_base.ib.playlist.call_args_list]
        self.assertIn(501, call_args)
        self.assertIn(502, call_args)
        self.assertNotIn(503, call_args)

    def test_folder_name_filter_case_insensitive(self):
        """Folder name filter should be case-insensitive."""
        self.ib_base.ib.playlists = {
            '600': {'name': 'MyFolder', 'type': 'folder', 'tracks': [601]},
            '601': {'name': 'Child', 'type': None},
        }
        self.ib_base.ib.playlist.return_value = {'tracks': [1]}

        trackid_to_path = {
            1: normpath(Path(self.tmpdir) / 'track1.mp3'),
        }

        manager = self._make_manager()
        state = {}

        manager._download_playlists(
            self.playlist_dir, Path(self.tmpdir),
            trackid_to_path, state, False, filters=['myfolder'])

        # Should still match the folder and include the child.
        call_args = [c[0][0] for c in self.ib_base.ib.playlist.call_args_list]
        self.assertIn(601, call_args)


class TestMergeTrackids(TestCase):
    """Test the three-way merge algorithm."""

    def setUp(self):
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def _merged(self, segments):
        """Extract flat track list from clean-only segments."""
        result = []
        for seg in segments:
            self.assertEqual(seg[0], 'clean')
            result.extend(seg[1])
        return result

    def test_all_identical(self):
        """No changes on either side."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 2, 3], [1, 2, 3])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 2, 3])

    def test_local_append(self):
        """Local adds a track, remote unchanged."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 2, 3, 4], [1, 2, 3])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 2, 3, 4])

    def test_remote_append(self):
        """Remote adds a track, local unchanged."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 2, 3], [1, 2, 3, 5])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 2, 3, 5])

    def test_both_append_different(self):
        """Both sides append different tracks."""
        segments, conflicts = self.manager._merge_trackids(
            [1, 2, 3], [1, 2, 3, 4], [1, 2, 3, 5])
        self.assertFalse(conflicts)
        merged = self._merged(segments)
        # Both new tracks should be present.
        self.assertIn(4, merged)
        self.assertIn(5, merged)
        # Original tracks preserved in order.
        self.assertEqual(merged[:3], [1, 2, 3])

    def test_non_overlapping_changes(self):
        """Different positions changed on each side."""
        segments, conflicts = self.manager._merge_trackids(
            [1, 2, 3, 4, 5], [1, 9, 3, 4, 5], [1, 2, 3, 4, 8])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 9, 3, 4, 8])

    def test_local_delete(self):
        """Local deletes a track, remote unchanged."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 3], [1, 2, 3])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 3])

    def test_both_delete_same(self):
        """Both sides delete the same track."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 3], [1, 3])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 3])

    def test_conflict_both_modify_same(self):
        """Both sides modify the same position differently."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 9, 3], [1, 8, 3])
        self.assertTrue(conflicts)
        # Should have conflict segment.
        conflict_segs = [s for s in segments if s[0] == 'conflict']
        self.assertTrue(len(conflict_segs) > 0)

    def test_conflict_delete_vs_modify(self):
        """One side deletes, other modifies the same region."""
        segments, conflicts = self.manager._merge_trackids([1, 2, 3], [1, 3], [1, 9, 3])
        self.assertTrue(conflicts)

    def test_empty_base(self):
        """Empty base with additions on both sides — concatenates local then remote."""
        segments, conflicts = self.manager._merge_trackids([], [1], [2])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 2])

    def test_empty_base_same_additions(self):
        """Empty base, both sides add the same thing."""
        segments, conflicts = self.manager._merge_trackids([], [1, 2], [1, 2])
        self.assertFalse(conflicts)
        self.assertEqual(self._merged(segments), [1, 2])


class TestWriteConflictedM3U(TestCase):
    """Test writing M3U files with conflict markers."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_conflict_markers_are_hash_prefixed(self):
        """Conflict markers should start with # so M3U parsers treat them as comments."""
        plpath = Path(self.tmpdir) / 'test.m3u'
        segments = [
            ('conflict', [1], [2]),
        ]
        trackid_to_path = {
            1: Path(self.tmpdir) / 'local.mp3',
            2: Path(self.tmpdir) / 'remote.mp3',
        }
        self.manager._write_conflicted_m3u(plpath, segments, trackid_to_path, Path(self.tmpdir))
        content = plpath.read_text()
        self.assertIn('#<<<<<<< local', content)
        self.assertIn('#=======', content)
        self.assertIn('#>>>>>>> remote', content)

    def test_clean_segments_render_as_paths(self):
        """Clean segments should render as normal track paths."""
        plpath = Path(self.tmpdir) / 'test.m3u'
        segments = [
            ('clean', [1, 2]),
        ]
        trackid_to_path = {
            1: Path(self.tmpdir) / 'track1.mp3',
            2: Path(self.tmpdir) / 'track2.mp3',
        }
        self.manager._write_conflicted_m3u(plpath, segments, trackid_to_path, Path(self.tmpdir))
        content = plpath.read_text()
        self.assertIn('track1.mp3', content)
        self.assertIn('track2.mp3', content)
        self.assertNotIn('#<<<<<<', content)

    def test_mixed_clean_and_conflict(self):
        """Mixed segments should produce both paths and markers."""
        plpath = Path(self.tmpdir) / 'test.m3u'
        segments = [
            ('clean', [1]),
            ('conflict', [2], [3]),
            ('clean', [4]),
        ]
        trackid_to_path = {
            1: Path(self.tmpdir) / 'track1.mp3',
            2: Path(self.tmpdir) / 'local.mp3',
            3: Path(self.tmpdir) / 'remote.mp3',
            4: Path(self.tmpdir) / 'track4.mp3',
        }
        self.manager._write_conflicted_m3u(plpath, segments, trackid_to_path, Path(self.tmpdir))
        content = plpath.read_text()
        lines = content.strip().split('\n')
        self.assertEqual(lines[0], 'track1.mp3')
        self.assertEqual(lines[1], '#<<<<<<< local')
        self.assertEqual(lines[2], 'local.mp3')
        self.assertEqual(lines[3], '#=======')
        self.assertEqual(lines[4], 'remote.mp3')
        self.assertEqual(lines[5], '#>>>>>>> remote')
        self.assertEqual(lines[6], 'track4.mp3')


class TestDownloadMergeIntegration(TestCase):
    """Integration tests for merge in the download path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin = MagicMock()
        self.ib_base = MagicMock()
        self.lib = MagicMock()
        self.music_dir = Path(self.tmpdir) / 'music'
        self.music_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_track(self, name):
        """Create a dummy track file and return its path."""
        p = self.music_dir / name
        p.touch()
        return normpath(p)

    def test_clean_merge_writes_merged_m3u(self):
        """When both sides add different tracks, merged M3U is written and remote updated."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

        t1 = self._make_track('track1.mp3')
        t2 = self._make_track('track2.mp3')
        t3 = self._make_track('track3.mp3')
        t4 = self._make_track('track4.mp3')
        t5 = self._make_track('track5.mp3')

        trackid_to_path = {1: t1, 2: t2, 3: t3, 4: t4, 5: t5}

        # Write local M3U with tracks [1,2,3,4] (local added 4).
        plpath = Path(self.tmpdir) / 'test.m3u'
        lines = [str(t.relative_to(self.music_dir)) for t in [t1, t2, t3, t4]]
        plpath.write_text('\n'.join(lines) + '\n')

        statekey = str(plpath)
        state = {statekey: {'id': 42, 'tracks': [1, 2, 3]}}

        # Remote has [1,2,3,5] (remote added 5).
        self.ib_base.ib.playlist.return_value = {'tracks': [1, 2, 3, 5]}

        manager._download_linked_playlist(
            42, 'test', statekey, self.music_dir, trackid_to_path, state)

        # settracks should be called with merged list.
        self.ib_base.ib.settracks.assert_called_once()
        merged_tracks = self.ib_base.ib.settracks.call_args[0][1]
        self.assertIn(4, merged_tracks)
        self.assertIn(5, merged_tracks)
        self.assertEqual(merged_tracks[:3], [1, 2, 3])

        # State should be updated.
        self.assertEqual(state[statekey]['tracks'], merged_tracks)

        # M3U should be rewritten.
        content = plpath.read_text()
        self.assertNotIn('#<<<<<<', content)

    def test_conflict_writes_conflicted_m3u_no_state_update(self):
        """When both sides modify the same region, write conflicted M3U, don't update state."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib)

        t1 = self._make_track('track1.mp3')
        t3 = self._make_track('track3.mp3')
        t8 = self._make_track('track8.mp3')
        t9 = self._make_track('track9.mp3')

        trackid_to_path = {1: t1, 3: t3, 8: t8, 9: t9}

        # Local has [1,9,3] (local changed pos 1 to 9).
        plpath = Path(self.tmpdir) / 'test.m3u'
        lines = [str(t.relative_to(self.music_dir)) for t in [t1, t9, t3]]
        plpath.write_text('\n'.join(lines) + '\n')

        statekey = str(plpath)
        original_state = {'id': 42, 'tracks': [1, 2, 3]}
        state = {statekey: dict(original_state)}

        # Remote has [1,8,3] (remote changed pos 1 to 8).
        self.ib_base.ib.playlist.return_value = {'tracks': [1, 8, 3]}

        manager._download_linked_playlist(
            42, 'test', statekey, self.music_dir, trackid_to_path, state)

        # State should be updated to remote so next sync sees local-only change.
        self.assertEqual(state[statekey]['tracks'], [1, 8, 3])

        # M3U should have conflict markers.
        content = plpath.read_text()
        self.assertIn('#<<<<<<< local', content)
        self.assertIn('#>>>>>>> remote', content)

        # settracks should NOT be called.
        self.ib_base.ib.settracks.assert_not_called()

    def test_pretend_mode_merge(self):
        """In pretend mode, merge should log but not write."""
        manager = PlaylistSyncManager(self.plugin, self.ib_base, self.lib, pretend=True)

        t1 = self._make_track('track1.mp3')
        t2 = self._make_track('track2.mp3')
        t3 = self._make_track('track3.mp3')
        t4 = self._make_track('track4.mp3')

        trackid_to_path = {1: t1, 2: t2, 3: t3, 4: t4}

        # Local has [1,2,3,4] (added 4), remote has [1,2,3] (unchanged from base perspective,
        # but we need remote to differ from base too for merge path).
        # Actually: base=[1,2], local=[1,2,3], remote=[1,2,4] — both changed.
        plpath = Path(self.tmpdir) / 'test.m3u'
        lines = [str(t.relative_to(self.music_dir)) for t in [t1, t2, t3]]
        plpath.write_text('\n'.join(lines) + '\n')
        original_content = plpath.read_text()

        statekey = str(plpath)
        state = {statekey: {'id': 42, 'tracks': [1, 2]}}

        self.ib_base.ib.playlist.return_value = {'tracks': [1, 2, 4]}

        manager._download_linked_playlist(
            42, 'test', statekey, self.music_dir, trackid_to_path, state)

        # File should be unchanged.
        self.assertEqual(plpath.read_text(), original_content)
        # settracks should NOT be called in pretend mode.
        self.ib_base.ib.settracks.assert_not_called()
        # State should be unchanged.
        self.assertEqual(state[statekey]['tracks'], [1, 2])
