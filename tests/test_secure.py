import io
import json
import tempfile
import unittest
from unittest.mock import patch
from src.gitty.secure import Chat, LIMIT, receive, github_login


class FakePeer:
    def __init__(self, uid, login):
        self.identity = {'id': uid, 'login': login}
        self.room = None
        self.messages = []

    def send(self, text):
        self.messages.append(text)


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.chat = Chat(':memory:', 1)
        self.admin = FakePeer(1, 'admin')
        self.friend = FakePeer(2, 'friend')
        self.chat.peers = {1: self.admin, 2: self.friend}

    def tearDown(self):
        self.chat.db.close()

    def test_admin_permission_uses_id_not_name(self):
        self.friend.identity['login'] = 'admin'
        with self.assertRaises(ValueError):
            self.chat.command(self.friend, '/admin online')
        self.chat.command(self.admin, '/admin online')
        self.assertIn('Online:', self.admin.messages[-1])

    def test_room_membership_and_direct_message(self):
        self.chat.command(self.admin, '/create gaming')
        self.chat.command(self.admin, 'secret')
        self.assertEqual(self.friend.messages, [])
        self.chat.command(self.friend, '/join gaming')
        self.chat.command(self.admin, 'hello')
        self.assertIn('[gaming] admin: hello', self.friend.messages[-1])
        self.chat.command(self.friend, '/users')
        self.assertIn('admin', self.friend.messages[-1])
        self.chat.command(self.friend, '/leave')
        count = len(self.friend.messages)
        self.chat.command(self.admin, 'alone')
        self.assertEqual(len(self.friend.messages), count)
        self.chat.command(self.admin, '/msg friend hi')
        self.assertIn('[DM admin → friend] hi', self.friend.messages[-1])

    def test_admin_broadcast_and_kick(self):
        self.chat.command(self.admin, '/admin broadcast Wartung in 5 Minuten')
        self.assertIn('[ANNOUNCEMENT] Wartung in 5 Minuten', self.friend.messages[-1])
        with self.assertRaises(ValueError):
            self.chat.command(self.friend, '/admin broadcast hacker')
        # Mock socket on fake peer for kick
        class MockSock:
            def shutdown(self, how):
                pass
        self.friend.sock = MockSock()
        self.chat.command(self.admin, '/admin kick friend')
        self.assertIn('getrennt', self.friend.messages[-1])

    def test_friends_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/contacts.db'
            chat = Chat(path, 1)
            with patch('src.gitty.secure.request', return_value=self.friend.identity):
                chat.command(self.admin, '/friend add friend')
            chat.db.close()
            chat = Chat(path, 1)
            chat.command(self.admin, '/friends')
            self.assertIn('friend: offline', self.admin.messages[-1])
            chat.peers[2] = self.friend
            chat.command(self.admin, '/friends')
            self.assertIn('friend: online', self.admin.messages[-1])
            chat.command(self.admin, '/friend remove friend')
            chat.command(self.admin, '/friends')
            self.assertIn('keine', self.admin.messages[-1])
            chat.db.close()

    def test_frames_and_limits(self):
        stream = io.BytesIO(b'{"line":"a"}\n{"line":"b"}\n')
        self.assertEqual(receive(stream)['line'], 'a')
        self.assertEqual(receive(stream)['line'], 'b')
        for data in (b'[]\n', b'{}', b'x' * (LIMIT + 1)):
            with self.assertRaises(ValueError):
                receive(io.BytesIO(data))

    def test_device_flow_polling(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / 'token'
            with patch('src.gitty.secure.TOKEN_FILE', token_path), \
                    patch('src.gitty.secure.request', side_effect=[
                        {'user_code': 'test', 'device_code': 'secret', 'expires_in': 100, 'interval': 5},
                        {'error': 'authorization_pending'}, {'error': 'slow_down'}, {'access_token': 'token'}
                    ]), patch('src.gitty.secure.time.sleep') as sleep, patch('builtins.print'), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(github_login(), 'token')
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 5, 10])
                self.assertEqual(token_path.read_text(encoding='utf-8'), 'token')

    def test_cached_token_reused_and_refreshed_on_401(self):
        import urllib.error
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / 'token'
            token_path.write_text('saved-tok', encoding='utf-8')
            with patch('src.gitty.secure.TOKEN_FILE', token_path), \
                    patch('src.gitty.secure.request', return_value={'id': 1}) as req, \
                    patch.dict('os.environ', {}, clear=True):
                self.assertEqual(github_login(), 'saved-tok')
                req.assert_called_once_with('https://api.github.com/user', token='saved-tok')

            with patch('src.gitty.secure.TOKEN_FILE', token_path), \
                    patch('src.gitty.secure.request', side_effect=[
                        urllib.error.HTTPError('https://api.github.com/user', 401, 'Unauthorized', {}, None),
                        {'user_code': 'NEW', 'device_code': 'dev', 'expires_in': 100, 'interval': 5},
                        {'access_token': 'fresh-tok'},
                    ]), patch('src.gitty.secure.time.sleep'), patch('builtins.print'), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(github_login(), 'fresh-tok')
                self.assertEqual(token_path.read_text(encoding='utf-8'), 'fresh-tok')

    def test_login_via_env_token(self):
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'env-token'}):
            self.assertEqual(github_login(), 'env-token')

    def test_client_tls_eof_message(self):
        import ssl
        from src.gitty.secure import client_main
        with patch('sys.argv', ['client.py', 'example.com']), \
                patch('src.gitty.client.animation.print_banner'), \
                patch('src.gitty.secure.github_login', return_value='tok'), \
                patch('src.gitty.secure.socket.create_connection') as conn, \
                patch('src.gitty.secure.ssl.create_default_context') as ctx, \
                patch('builtins.print') as mock_print:
            conn.return_value.__enter__.return_value = object()
            ctx.return_value.wrap_socket.side_effect = ssl.SSLEOFError('eof')
            client_main()
            printed = ' '.join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn('TLS-Handshake fehlgeschlagen', printed)

    def test_grouped_help_formatting(self):
        from src.gitty.secure import HELP, ADMIN_HELP, BANNER, format_help
        self.assertIn('\033[92m', BANNER)
        self.assertTrue(BANNER.endswith('\n'))
        self.assertIn('Secure Terminal Messenger v3.2', BANNER)
        for section in ('Chat & Rooms', 'Friends', 'General'):
            self.assertIn(section, HELP)
        self.assertNotIn('Admin', HELP)
        self.assertNotIn('/admin', HELP)
        self.assertIn('Admin', ADMIN_HELP)
        with patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch.object(out, 'isatty', return_value=True):
            colored = format_help()
            self.assertIn('\033[1;92mChat & Rooms\033[0m', colored)
            self.assertIn('\033[1;95mFriends\033[0m', colored)
            self.assertIn('\033[1;94mGeneral\033[0m', colored)
            self.assertIn('\033[92m  /rooms', colored)
            self.assertIn('\033[95m  /friends', colored)
            self.assertIn('\033[94m  /help', colored)
            self.assertIn('\033[91m  /exit', colored)
            self.assertIn('\033[93m  /admin online', format_help(ADMIN_HELP))

    def test_help_admin_restricted_to_admin(self):
        self.friend.identity['login'] = 'Jan-Kirschke'
        with self.assertRaises(ValueError):
            self.chat.command(self.friend, '/help-admin')
        self.chat.command(self.admin, '/help-admin')
        self.assertIn('/admin broadcast', self.admin.messages[-1])


if __name__ == '__main__':
    unittest.main()
