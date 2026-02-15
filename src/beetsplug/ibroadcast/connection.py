# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import json
import logging
import os
from pathlib import Path

from ibroadcast import from_device_code, iBroadcast, oauth

from beetsplug.ibroadcast import common


CLIENT_ID = '9f66b85509db11f1b9ffb49691aa2236'
SCOPES = ['user.library:read', 'user.library:write', 'user.upload']
TOKEN_FILE = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'beets' / 'ibroadcast-tokens.json'


def _load_tokens():
    """Load saved tokens from disk, or return None."""
    if not TOKEN_FILE.is_file():
        return None
    with open(TOKEN_FILE) as f:
        return oauth.TokenSet.from_dict(json.load(f))


def _save_tokens(token_set):
    """Save tokens to disk with restrictive permissions."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_set.to_dict(), f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)


class IBroadcastBase:
    """Shared connection and logging base for iBroadcast commands."""

    plugin = None
    ib = None
    tags = None

    def _connect(self):
        self.plugin._log.debug('Connecting to iBroadcast')
        version = common.plg_ns['__version__']

        # Try loading saved tokens first.
        tokens = _load_tokens()
        if tokens:
            if tokens.is_expired and tokens.refresh_token:
                # Try refreshing expired tokens.
                try:
                    tokens = oauth.refresh_access_token(CLIENT_ID, tokens.refresh_token)
                    _save_tokens(tokens)
                except Exception:
                    tokens = None  # Fall through to device code flow.

            if tokens:
                self.ib = iBroadcast(
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    client_id=CLIENT_ID,
                    token_refreshed_callback=_save_tokens,
                    client='beets-ibroadcast',
                    version=version,
                )
                self.ib.refresh()
                self._organize_tags()
                return

        # No valid tokens -- run device code flow.
        self.ib = from_device_code(
            client_id=CLIENT_ID,
            scopes=SCOPES,
            on_device_code=self._prompt_device_code,
            token_refreshed_callback=_save_tokens,
            client='beets-ibroadcast',
            version=version,
        )
        _save_tokens(self.ib.token_set)
        self.ib.refresh()
        self._organize_tags()

    def _organize_tags(self):
        """Reorganize tags to be keyed on name rather than ID."""
        self.tags = {}
        for tagid, tag in self.ib.tags.items():
            tagcopy = tag.copy()
            tagname = tagcopy.pop('name')
            tagcopy['id'] = tagid
            if tagname in self.tags:
                self.plugin._log.warning(f"Ignoring duplicate tag '{tagname}' with ID {tagid}.")
            else:
                self.tags[tagname] = tagcopy

    def _prompt_device_code(self, user_code, verification_uri, verification_uri_complete):
        self.plugin._log.info(f"To authorize beets-ibroadcast, visit: {verification_uri}")
        self.plugin._log.info(f"And enter code: {user_code}")
        if verification_uri_complete:
            self.plugin._log.info(f"Or visit: {verification_uri_complete}")
        self.plugin._log.info("Waiting for authorization...")

    def _verbose(self):
        return self.plugin._log.level <= logging.DEBUG

    def _stack_trace(self, e):
        if self._verbose():
            self.plugin._log.exception(e)
