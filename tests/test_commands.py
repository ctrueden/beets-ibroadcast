# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

from .helper import TestHelper, Assertions, capture_log

plg_log_ns = 'beets.ibroadcast'


class CommandRegistrationTest(TestHelper, Assertions):
    """Test that both commands are registered and accessible."""

    def test_ib_upload_command_listed(self):
        output = self.runcli()
        self.assertIn('ib-upload', output)

    def test_ib_playlist_command_listed(self):
        output = self.runcli()
        self.assertIn('ib-playlist', output)

    def test_ibroadcast_alias_shows_version(self):
        """The 'ibroadcast' alias should still work for ib-upload."""
        with capture_log(plg_log_ns) as logs:
            self.runcli("ibroadcast", "--version")
        self.assertIn("plugin for Beets:", "\n".join(logs))

    def test_ib_upload_shows_version(self):
        with capture_log(plg_log_ns) as logs:
            self.runcli("ib-upload", "--version")
        self.assertIn("plugin for Beets:", "\n".join(logs))

    def test_ib_upload_pretend_no_items(self):
        """Pretend mode with no matching items should succeed silently."""
        with capture_log(plg_log_ns) as logs:
            self.runcli("ib-upload", "-p", "artist:NonexistentArtist12345")
        # Should complete without errors.

    def test_ib_playlist_pretend(self):
        """Pretend mode should work without iBroadcast connection."""
        with capture_log(plg_log_ns) as logs:
            self.runcli("ib-playlist", "-p")
        # Should complete; may log about no playlist config.
