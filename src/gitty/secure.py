"""TLS-only Gitty protocol. GitHub tokens are verified, never persisted."""
import argparse
from collections import deque
import json
import logging
import os
from pathlib import Path
import re
import socket
import ssl
import sqlite3
import threading
import time
import urllib.request
import urllib.parse
import urllib.error

CLIENT_ID = 'Ov23lijEgap8bwwpxgPs'
HOST = 'chat.jankirschke.de'
LIMIT = 16384
TOKEN_FILE = Path.home() / '.gitty' / 'token'
LOGIN_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$')
LOG = logging.getLogger('gitty.secure')


def request(url, data=None, token=None):
    if not url.startswith('https://'):
        raise ValueError('Nur HTTPS-URLs erlaubt')
    headers = {'Accept': 'application/json', 'User-Agent': 'Gitty'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=20) as response:
        return json.load(response)


def validate_identity(identity):
    if not isinstance(identity, dict):
        raise ValueError('Ungültige GitHub-Antwort')
    uid = identity.get('id')
    login = identity.get('login')
    if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
        raise ValueError('Ungültige GitHub-ID')
    if not isinstance(login, str) or not LOGIN_RE.match(login):
        raise ValueError('Ungültiger GitHub-Benutzername')
    return {'id': uid, 'login': login}


def github_login():
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        print('WARNUNG: GITHUB_TOKEN aus Umgebung wird zur Anmeldung an den Server gesendet.')
        return token
    if TOKEN_FILE.is_file():
        saved = TOKEN_FILE.read_text(encoding='utf-8').strip()
        if saved:
            try:
                request('https://api.github.com/user', token=saved)
                return saved
            except urllib.error.HTTPError as err:
                if err.code != 401:
                    raise
                TOKEN_FILE.unlink(missing_ok=True)
    data = request('https://github.com/login/device/code', {'client_id': CLIENT_ID})
    print('Öffne https://github.com/login/device und gib diesen Code ein:', data['user_code'])
    deadline = time.monotonic() + data['expires_in']
    interval = data.get('interval', 5)
    while time.monotonic() < deadline:
        time.sleep(interval)
        result = request('https://github.com/login/oauth/access_token', {
            'client_id': CLIENT_ID, 'device_code': data['device_code'],
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'})
        if 'access_token' in result:
            token = result['access_token']
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(token, encoding='utf-8')
            try:
                os.chmod(TOKEN_FILE, 0o600)
            except OSError:
                pass
            return token
        error = result.get('error')
        if error == 'slow_down':
            interval += 5
        elif error != 'authorization_pending':
            raise ValueError('GitHub-Anmeldung abgebrochen: ' + str(error))
    raise ValueError('Anmeldecode abgelaufen')


def receive(stream):
    line = stream.readline(LIMIT + 1)
    if not line:
        raise EOFError
    if len(line) > LIMIT or not line.endswith(b'\n'):
        raise ValueError('Paket zu groß oder unvollständig')
    packet = json.loads(line)
    if not isinstance(packet, dict):
        raise ValueError('Objekt erwartet')
    return packet


class Peer:
    def __init__(self, sock, identity):
        self.sock, self.identity = sock, identity
        self.lock = threading.Lock()
        self.room = None
        self._cmd_times = deque()
        self._lookup_times = deque()

    def send(self, text):
        with self.lock:
            self.sock.sendall((json.dumps({'text': text}, ensure_ascii=False) + '\n').encode())

    def check_rate(self, bucket, limit, window):
        now = time.monotonic()
        with self.lock:
            while bucket and now - bucket[0] > window:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


class Chat:
    def __init__(self, database, admin_id):
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS friends (owner INTEGER, friend INTEGER, login TEXT, PRIMARY KEY(owner, friend))')
        self.lock = threading.RLock()
        self.peers = {}
        self.rooms = set()
        self.admin_id = admin_id
        self._user_cache = {}

    def _prune_room(self, room):
        if room and not any(p.room == room for p in self.peers.values()):
            self.rooms.discard(room)

    def _resolve_user(self, target):
        now = time.monotonic()
        key = target.lower()
        with self.lock:
            cached = self._user_cache.get(key)
            if cached and now - cached[0] < 300:
                return cached[1]
        identity = validate_identity(request('https://api.github.com/users/' + target))
        with self.lock:
            if len(self._user_cache) >= 500:
                self._user_cache.clear()
            self._user_cache[key] = (now, identity)
        return identity

    def sync_login(self, identity):
        with self.lock, self.db:
            self.db.execute(
                'UPDATE friends SET login=? WHERE friend=? AND login!=?',
                (identity['login'], identity['id'], identity['login']),
            )

    def remove_peer(self, peer):
        with self.lock:
            if self.peers.get(peer.identity['id']) is peer:
                del self.peers[peer.identity['id']]
            old_room = peer.room
            peer.room = None
            self._prune_room(old_room)

    def command(self, peer, line):
        if '\n' in line or '\r' in line:
            raise ValueError('Mehrzeilige Eingaben sind nicht erlaubt')
        words = line.split(maxsplit=2)
        if not words:
            return
        if hasattr(peer, 'check_rate') and not peer.check_rate(peer._cmd_times, 15, 5):
            raise ValueError('Zu viele Nachrichten/Befehle; bitte kurz warten')
        cmd = words[0].lstrip('/')
        uid = peer.identity['id']
        name = peer.identity['login']
        if cmd == 'friend' and len(words) == 3 and words[1] in ('add', 'remove'):
            target = words[2]
            if not LOGIN_RE.match(target):
                raise ValueError('Ungültiger GitHub-Name')
            if words[1] == 'add':
                if hasattr(peer, 'check_rate') and not peer.check_rate(peer._lookup_times, 5, 60):
                    raise ValueError('Zu viele Kontakt-Abfragen; bitte kurz warten')
                # Resolve outside the state lock; friendships use immutable GitHub IDs.
                try:
                    identity = self._resolve_user(target)
                except urllib.error.HTTPError as err:
                    if err.code == 404:
                        raise ValueError(f'GitHub-Benutzer "{target}" existiert nicht')
                    raise
                with self.lock, self.db:
                    self.db.execute('INSERT OR REPLACE INTO friends VALUES (?, ?, ?)', (uid, identity['id'], identity['login']))
            else:
                with self.lock, self.db:
                    self.db.execute('DELETE FROM friends WHERE owner=? AND (login=? COLLATE NOCASE)', (uid, target))
            peer.send('Kontaktliste aktualisiert')
            return
        kick_target = None
        with self.lock:
            targets = [peer]
            if cmd == 'friends':
                rows = self.db.execute('SELECT friend, login FROM friends WHERE owner=? ORDER BY login', (uid,)).fetchall()
                text = 'Freunde: ' + (', '.join(f'{login}: ' + ('online' if fid in self.peers else 'offline') for fid, login in rows) or 'keine')
            elif cmd == 'help':
                text = HELP
            elif cmd == 'help-admin':
                if uid != self.admin_id:
                    raise ValueError('Keine Admin-Berechtigung')
                text = ADMIN_HELP
            elif cmd in ('users', 'who'):
                if peer.room:
                    in_room = [p.identity['login'] for p in self.peers.values() if p.room == peer.room]
                    text = f'Im Raum [{peer.room}]: ' + ', '.join(sorted(in_room))
                elif uid == self.admin_id:
                    text = 'Online: ' + ', '.join(sorted(p.identity['login'] for p in self.peers.values()))
                else:
                    raise ValueError('Nicht in einem Raum. /rooms und /join RAUM oder /friends verwenden')
            elif cmd == 'admin':
                if uid != self.admin_id:
                    raise ValueError('Keine Admin-Berechtigung')
                sub = words[1] if len(words) > 1 else ''
                if sub == 'online':
                    text = 'Online: ' + ', '.join(sorted(p.identity['login'] for p in self.peers.values()))
                elif sub == 'kick' and len(words) == 3:
                    target_peer = next((p for p in self.peers.values() if p.identity['login'].lower() == words[2].lower()), None)
                    if not target_peer:
                        raise ValueError(f'Benutzer "{words[2]}" ist nicht online')
                    if target_peer is peer:
                        raise ValueError('Eigenes Konto kann nicht gekickt werden')
                    kick_target = target_peer
                    if self.peers.get(target_peer.identity['id']) is target_peer:
                        del self.peers[target_peer.identity['id']]
                    old_room = target_peer.room
                    target_peer.room = None
                    self._prune_room(old_room)
                    LOG.info('Admin %s kicked %s', name, target_peer.identity['login'])
                    text = f'{words[2]} wurde getrennt'
                elif sub == 'broadcast' and len(words) == 3:
                    targets = list(self.peers.values())
                    now = time.strftime('%H:%M:%S')
                    LOG.info('Admin %s sent broadcast', name)
                    text = f'[{now}] [ANNOUNCEMENT] {words[2]}'
                else:
                    raise ValueError('Admin-Befehle: /admin online | /admin kick NAME | /admin broadcast TEXT')
            elif cmd == 'rooms':
                text = 'Räume: ' + (', '.join(sorted(self.rooms)) or 'keine')
            elif cmd in ('create', 'join') and len(words) == 2:
                room = words[1]
                if not room.isascii() or not room.replace('-', '').replace('_', '').isalnum() or len(room) > 32:
                    raise ValueError('Raumname: 1–32 Buchstaben/Ziffern, - oder _')
                if cmd == 'create':
                    if room in self.rooms:
                        raise ValueError('Raum existiert bereits; /join verwenden')
                    if len(self.rooms) >= 100:
                        raise ValueError('Raumlimit erreicht')
                    self.rooms.add(room)
                if room not in self.rooms:
                    raise ValueError('Raum existiert nicht')
                old_room = peer.room
                peer.room = room
                if old_room != room:
                    self._prune_room(old_room)
                text = 'Raum betreten: ' + room
            elif cmd == 'leave':
                old_room = peer.room
                peer.room = None
                self._prune_room(old_room)
                text = 'Raum verlassen'
            elif cmd == 'msg' and len(words) == 3:
                targets = [p for p in self.peers.values() if p.identity['login'].lower() == words[1].lower()]
                if not targets:
                    raise ValueError('Benutzer offline')
                targets = list({*targets, peer})
                now = time.strftime('%H:%M:%S')
                text = f'[{now}] [DM {name} → {words[1]}] {words[2]}'
            elif line.startswith('/'):
                raise ValueError('Unbekannter Befehl; /help zeigt die Hilfe')
            elif peer.room:
                targets = [p for p in self.peers.values() if p.room == peer.room]
                now = time.strftime('%H:%M:%S')
                text = f'[{now}] [{peer.room}] {name}: {line}'
            else:
                raise ValueError('Erst /join RAUM oder /msg NAME TEXT verwenden')
        if kick_target is not None:
            try:
                kick_target.send('Du wurdest vom Admin getrennt.')
                kick_target.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for target in targets:
            try:
                target.send(text)
            except OSError:
                pass


def server_main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--cert', default=os.environ.get('GITTY_CERT'))
    parser.add_argument('--key', default=os.environ.get('GITTY_KEY'))
    parser.add_argument('--admin-id', type=int, default=os.environ.get('GITTY_ADMIN_ID'))
    parser.add_argument('--database', default=os.environ.get('GITTY_DATABASE', 'gitty.sqlite3'))
    parser.add_argument('--port', type=int, default=5555)
    args = parser.parse_args()
    if not args.cert or not args.key or not args.admin_id:
        parser.error('--cert, --key und --admin-id sind erforderlich')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    chat = Chat(args.database, args.admin_id)
    slots = threading.BoundedSemaphore(100)
    ip_lock = threading.Lock()
    ip_counts = {}
    max_per_ip = 5

    def handle(raw, client_ip):
        peer = None
        try:
            raw.settimeout(10)
            with context.wrap_socket(raw, server_side=True) as sock, sock.makefile('rb') as stream:
                try:
                    token = receive(stream).get('token')
                    if not isinstance(token, str) or not token or len(token) > 4096:
                        raise ValueError('Token fehlt')
                    identity = validate_identity(request('https://api.github.com/user', token=token))
                    del token
                    candidate = Peer(sock, identity)
                    with chat.lock:
                        if identity['id'] in chat.peers:
                            raise ValueError('Konto bereits verbunden')
                        chat.peers[identity['id']] = candidate
                        peer = candidate
                    chat.sync_login(identity)
                except (ValueError, urllib.error.URLError) as err:
                    LOG.warning('Auth failed from %s: %s', client_ip, type(err).__name__)
                    try:
                        sock.sendall((json.dumps({'text': str(err)}, ensure_ascii=False) + '\n').encode())
                    except OSError:
                        pass
                    return
                sock.settimeout(300)
                peer.send('Angemeldet als ' + identity['login'])
                chat.command(peer, '/friends')
                while True:
                    packet = receive(stream)
                    if packet.get('ping') is True:
                        continue
                    line = packet.get('line')
                    if not isinstance(line, str) or len(line) > 4000 or '\n' in line or '\r' in line:
                        raise ValueError('Ungültige Nachricht')
                    try:
                        chat.command(peer, line.strip())
                    except ValueError as err:
                        peer.send(str(err))
                    except urllib.error.URLError:
                        peer.send('Befehl fehlgeschlagen: GitHub-Dienst nicht erreichbar. /help zeigt Befehle.')
        except (OSError, ValueError, EOFError, KeyError):
            pass
        finally:
            if peer:
                chat.remove_peer(peer)
            with ip_lock:
                remaining = ip_counts.get(client_ip, 1) - 1
                if remaining <= 0:
                    ip_counts.pop(client_ip, None)
                else:
                    ip_counts[client_ip] = remaining
            raw.close()
            slots.release()

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('0.0.0.0', args.port))
        listener.listen(100)
        print('Gitty TLS listening on', args.port, flush=True)
        while True:
            raw, addr = listener.accept()
            client_ip = addr[0]
            with ip_lock:
                if ip_counts.get(client_ip, 0) >= max_per_ip or not slots.acquire(blocking=False):
                    LOG.warning('Rejected connection from %s (rate/slot limit)', client_ip)
                    raw.close()
                    continue
                ip_counts[client_ip] = ip_counts.get(client_ip, 0) + 1
            threading.Thread(target=handle, args=(raw, client_ip), daemon=True).start()


HELP = '''Chat & Rooms
  /rooms                  List active chatrooms
  /create ROOM            Create a new chatroom
  /join ROOM              Join a chatroom
  /leave                  Leave the current chatroom
  /users                  List users in the room
  /msg USER TEXT          Send a direct message

Friends
  /friends                Show friends & online status
  /friend add USER        Add a GitHub user
  /friend remove USER     Remove a friend

General
  /help                   Show help
  /exit                   Disconnect and quit

Inside a room, just type to chat. Rooms and messages are not saved.'''

ADMIN_HELP = '''Admin
  /admin online           List all connected users
  /admin kick USER        Disconnect a user
  /admin broadcast TEXT   Send announcement to everyone'''

BANNER = '''\033[92m  _____ _ _   _         
 / ____(_) | | |        
| |  __ _| |_| |_ _   _ 
| | |_ | | __| __| | | |
| |__| | | |_| |_| |_| |
 \\_____|_|\\__|\\__|\\__, |
                  __/ |
                 |___/ \033[0m
\033[96m  Secure Terminal Messenger v3.2\033[0m
'''

SECTION_COLORS = {
    'Chat & Rooms': ('\033[1;92m', '\033[92m'),
    'Friends': ('\033[1;95m', '\033[95m'),
    'Admin': ('\033[1;93m', '\033[93m'),
    'General': ('\033[1;94m', '\033[94m'),
}


def format_help(text=HELP):
    import sys
    if not sys.stdout.isatty():
        return text
    lines = []
    cmd_color = '\033[92m'
    for line in text.splitlines():
        if line in SECTION_COLORS:
            header_color, cmd_color = SECTION_COLORS[line]
            lines.append(f'{header_color}{line}\033[0m')
        elif line.startswith('  /exit'):
            cmd, desc = line[:26], line[26:]
            lines.append(f'\033[91m{cmd}\033[0m{desc}')
        elif line.startswith('  /'):
            cmd, desc = line[:26], line[26:]
            lines.append(f'{cmd_color}{cmd}\033[0m{desc}')
        elif line:
            lines.append(f'\033[90m{line}\033[0m')
        else:
            lines.append(line)
    return '\n'.join(lines)


def client_main():
    from .client.animation import print_banner
    parser = argparse.ArgumentParser()
    parser.add_argument('host', nargs='?', default=HOST)
    parser.add_argument('-p', '--port', type=int, default=5555)
    parser.add_argument('--ca-cert', default=os.environ.get('GITTY_CA_CERT'), help='Pfad zu eigenem CA-Zertifikat')
    args = parser.parse_args()
    print_banner(BANNER)
    print(format_help())
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if args.ca_cert:
        context.load_verify_locations(args.ca_cert)
    if os.environ.get('GITTY_INSECURE') == '1':
        # shortcut: cert check bypass for local testing only
        print('WARNUNG: TLS-Zertifikatsprüfung deaktiviert (GITTY_INSECURE=1)!')
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        token = github_login()
        with socket.create_connection((args.host, args.port), timeout=20) as raw:
            with context.wrap_socket(raw, server_hostname=args.host) as sock:
                lock = threading.Lock()
                def send(packet):
                    with lock:
                        sock.sendall((json.dumps(packet, ensure_ascii=False) + '\n').encode())
                send({'token': token})
                del token
                sock.settimeout(None)
                stopped = threading.Event()
                def listen():
                    try:
                        with sock.makefile('rb') as stream:
                            while True:
                                text = receive(stream).get('text', '')
                                # Never allow remote terminal escape sequences.
                                print('\n' + ''.join(c for c in str(text) if c == '\n' or c.isprintable()))
                    except (OSError, ValueError, EOFError):
                        print('\nVerbindung beendet. Enter zum Schließen.')
                    finally:
                        stopped.set()
                def heartbeat():
                    while not stopped.wait(30):
                        try:
                            send({'ping': True})
                        except OSError:
                            stopped.set()
                threading.Thread(target=listen, daemon=True).start()
                threading.Thread(target=heartbeat, daemon=True).start()
                try:
                    while not stopped.is_set():
                        line = input('> ')
                        if line in ('exit', '/exit'):
                            break
                        if line in ('help', '/help'):
                            print(format_help())
                        elif line.strip():
                            if len(line) > 4000:
                                print('Maximal 4000 Zeichen')
                            else:
                                send({'line': line})
                finally:
                    stopped.set()
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
    except ssl.SSLCertVerificationError as error:
        print(f'TLS-Zertifikat nicht vertrauenswürdig ({error.verify_message}). --ca-cert oder Server-Zertifikat prüfen.')
    except ssl.SSLEOFError:
        print(f'TLS-Handshake fehlgeschlagen ({args.host}:{args.port}): Gegenstelle hat die Verbindung geschlossen (läuft dort noch der alte Server ohne TLS?).')
    except (OSError, ValueError, EOFError, KeyboardInterrupt, KeyError) as error:
        print('Verbindung/Anmeldung beendet:', type(error).__name__)
