# This is free and unencumbered software released into the public domain.
# See https://unlicense.org/ for details.

import hashlib
import json
import logging
import requests

__version__ = '0.1.0.dev'
__client__ = 'beets-ibroadcast'

def calcmd5(filePath="."):
    with open(filePath, 'rb') as fh:
        m = hashlib.md5()
        while True:
            data = fh.read(8192)
            if not data:
                break
            m.update(data)
    return m.hexdigest()

def _json(response):
    if not response.ok:
        raise ServerError('Server returned bad status: ',
                         response.status_code)
    json = response.json()
    if 'message' in json:
        logging.info(json['message'])
    if json['result'] is False:
        raise ValueError('Operation failed.')
    return json

def _decode(data):
    """
    Normalize a "compressed" dictionary with special 'map' entry.

    This format looks like a way to reduce bandwidth by avoiding repeated
    key strings. Maybe it's a JSON standard with a built-in method to
    decode it? But since I'm REST illiterate, we decode it manually!

    For example, the following data object:

        data = {
           "244526" : [
              "Starter Songs",
              [
                 134082068,
                 134082066,
                 134082069,
                 134082067
              ],
              "1234-1234-1234-1234",
              false,
              null,
              null,
              null,
              null,
              1
           ],
           "map" : {
              "artwork_id" : 7,
              "description" : 6,
              "name" : 0,
              "public_id" : 4,
              "sort" : 8,
              "system_created" : 3,
              "tracks" : 1,
              "type" : 5,
              "uid" : 2
           }
        }

    will be decoded to:

       data = {
          "244526" : {
             "name": "Starter Songs",
             "tracks": [
                134082068,
                134082066,
                134082069,
                134082067
             ],
             "uid": "1234-1234-1234-1234",
             "system_created": false,
             "public_id": null,
             "type": null,
             "description": null,
             "artwork_id": null,
             "sort": 1
          }
       }
    """

    if not 'map' in data or type(data['map']) is not dict:
        return data
    keymap = {v: k for (k, v) in data['map'].items()}

    result = {}
    for k, v in data.items():
        if type(v) is list:
            result[k] = {keymap[i]: v[i] for i in range(len(v))}
    return result

class ServerError(Exception):
    pass

class iBroadcast(object):
    """
    Class for making iBroadcast requests.

    Adapted from ibroadcast-uploader.py at <https://project.ibroadcast.com/>.
    """

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self._login(username, password)

    def _login(self, username, password):
        """
        Login to iBroadcast with the given username and password

        Raises:
            ValueError on invalid login
            ServerError on problem logging in

        """
        self.username = username
        self.password = password

        # Log in.
        logging.info(f'Logging in as {username}...')
        self.status = _json(requests.post(
            "https://api.ibroadcast.com/s/JSON/status",
            data=json.dumps({
                'mode': 'status',
                'email_address': username,
                'password': password,
                'version': __version__,
                'client': __client__,
                'supported_types': 1,
            }),
            headers={'Content-Type': 'application/json'}
        ))
        if 'user' not in self.status:
            raise ValueError('Invalid login.')

        logging.info(f'Login successful - user_id: {self.user_id()}')
        self.refresh()

    def refresh(self):
        """
        Download library data: albums, artists, MD5 checksums, etc.
        """

        logging.info('Downloading MD5 checksums...')
        self.state = _json(requests.post(
            "https://sync.ibroadcast.com",
            data=f'user_id={self.user_id()}&token={self.token()}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        ))
        self.md5 = set(self.state['md5'])

        logging.info('Downloading library data...')
        self.library = _json(requests.post(
            "https://library.ibroadcast.com",
            data=json.dumps({
                '_token': self.token(),
                '_userid': self.user_id(),
                'client': __client__,
                'version': __version__,
                'mode': 'library',
                'supported_types': False,
                'url': '//library.ibroadcast.com',
            }),
            headers={'Content-Type': 'application/json'}
        ))
        self.albums = _decode(self.library['library']['albums'])
        self.artists = _decode(self.library['library']['artists'])
        self.playlists = _decode(self.library['library']['playlists'])
        self.tags = _decode(self.library['library']['tags'])
        self.tracks = _decode(self.library['library']['tracks'])

    def user_id(self):
        """
        Gets the user_id for the current session.
        """
        return self.status['user']['id']

    def token(self):
        """
        Gets the authentication token for the current session.
        """
        return self.status['user']['token']

    def extensions(self):
        """
        Get file extensions for supported audio formats.
        """
        return [ft['extension'] for ft in self.status['supported']]

    def isuploaded(self, filename):
        return calcmd5(filename) in self.md5

    def upload(self, filename):
        """
        Upload the given file to iBroadcast, if it isn't there already.
        """
        if self.isuploaded(filename):
            logging.info(f'Skipping - already uploaded: {filename}')
            return False

        logging.info(f'Uploading {filename}')

        with open(filename, 'rb') as upload_file:
            _json(requests.post(
                "https://sync.ibroadcast.com",
                data={
                    'user_id': self.user_id,
                    'token': self.token,
                    'file_path': filename,
                    'method': __client__,
                },
                files={'file': upload_file},
            ))

        return True

    def createtag(self, tagname):
        """
        Create a tag.

        Returns:
            ID of newly created tag.
        """
        json = _json(requests.post(
            "https://api.ibroadcast.com/s/JSON/createtag",
            data=json.dumps({
                '_token': self.token(),
                '_userid': self.user_id(),
                'client': __client__,
                'version': __version__,
                'mode': 'createtag',
                'supported_types': False,
                'tagname': tagname,
                'url': '//api.ibroadcast.com/s/JSON/createtag',
            }),
            headers={'Content-Type': 'application/json'}
        ))
        return json['id']

    def tagtracks(self, tagid, trackids, untag=False):
        """
        Applies or removes the given tag to the specified tracks.

        :param tagid: ID of the tag to apply.
        :param trackids: List of IDs for the tracks to tag.
        :param untag: If true, remove the tag rather than applying it.
        """
        _json(requests.post(
            "https://api.ibroadcast.com/s/JSON/tagtracks",
            data=json.dumps({
                '_token': self.token(),
                '_userid': self.user_id(),
                'client': __client__,
                'version': __version__,
                'mode': 'tagtracks',
                'supported_types': False,
                'tagid': tagid,
                'tracks': trackids,
                'untag': untag,
                'url': '//api.ibroadcast.com/s/JSON/tagtracks',
            }),
            headers={'Content-Type': 'application/json'}
        ))

    def trash(self, trackids):
        """
        Moves the given tracks to the trash.

        :param trackids: List of IDs for the tracks to tag.
        """
        _json(requests.post(
            "https://api.ibroadcast.com/s/JSON/tagtracks",
            data=json.dumps({
                '_token': self.token(),
                '_userid': self.user_id(),
                'client': __client__,
                'version': __version__,
                'mode': 'trash',
                'supported_types': False,
                'tracks': trackids,
                'url': '//api.ibroadcast.com/s/JSON/tagtracks',
            }),
            headers={'Content-Type': 'application/json'}
        ))
