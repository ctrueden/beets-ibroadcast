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
        self.user_id = None
        self.token = None
        self.supported = None
        self.files = None
        self.md5 = None

        self._login(username, password)

    def _login(self, username, password):
        """
        Login to iBroadcast with the given username and password

        Raises:
            ValueError on invalid login

        """
        self.username = username
        self.password = password
        logging.debug('Logging in as ...')
        # Build a request object.
        post_data = json.dumps({
            'mode' : 'status',
            'email_address': username,
            'password': password,
            'version': __version__,
            'client': __client__,
            'supported_types' : 1,
        })
        response = requests.post(
            "https://api.ibroadcast.com/s/JSON/status",
            data=post_data,
            headers={'Content-Type': 'application/json'}
        )

        if not response.ok:
            raise ServerError('Server returned bad status: ',
                             response.status_code)

        jsoned = response.json()

        if 'user' not in jsoned:
            raise ValueError('Invalid login.')

        self.user_id = jsoned['user']['id']
        self.token = jsoned['user']['token']
        logging.debug('Login successful - user_id: %s', self.user_id)
        self.supported = []
        self.files = []
        for filetype in jsoned['supported']:
             self.supported.append(filetype['extension'])

        __load_md5()

    def __load_md5(self):
        """
        Reach out to iBroadcast and get an md5.
        """
        post_data = "user_id=%s&token=%s" % (self.user_id, self.token)

        # Send our request.
        response = requests.post(
            "https://sync.ibroadcast.com",
            data=post_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )

        if not response.ok:
            raise ServerError('Server returned bad status: ',
                             response.status_code)

        jsoned = response.json()

        self.md5 = jsoned['md5']

    def upload(self, filename):
        file_md5 = calcmd5(filename)
        if file_md5 in self.md5:
            print(f'Skipping - already uploaded: {filename}'
            return False
        else
            print(f'Uploading {filename}')

        upload_file = open(filename, 'rb')

        file_data = {
            'file': upload_file,
        }

        post_data = {
            'user_id': self.user_id,
            'token': self.token,
            'file_path' : filename,
            'method': __client__,
        }

        response = requests.post(
            "https://sync.ibroadcast.com",
            post_data,
            files=file_data,

        )

        upload_file.close()

        if not response.ok:
            raise ServerError('Server returned bad status: ',
                response.status_code)
        jsoned = response.json()
        result = jsoned['result']

        if result is False:
            raise ValueError('File upload failed.')

        return True
