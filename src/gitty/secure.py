"""TLS-only Gitty protocol. GitHub tokens are verified, never persisted."""
import argparse
import json
import os
from pathlib import Path
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


def request(url, data=None, token=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'Gitty'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=20) as response:
        return json.load(response)


def github_login():
    token = os.environ.get('GITHUB_TOKEN')
    if token:
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

    def send(self, text):
        with self.lock:
            self.sock.sendall((json.dumps({'text': text}, ensure_ascii=False) + '\n').encode())


class Chat:
    def __init__(self, database, admin_id):
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS friends (owner INTEGER, friend INTEGER, login TEXT, PRIMARY KEY(owner, friend))')
        self.lock = threading.RLock()
        self.peers = {}
        self.rooms = set()
        self.admin_id = admin_id

    def command(self, peer, line):
        words = line.split(maxsplit=2)
        if not words:
            return
        cmd = words[0].lstrip('/')
        uid = peer.identity['id']
        name = peer.identity['login']
        if cmd == 'friend' and len(words) == 3 and words[1] in ('add', 'remove'):
            target = words[2]
            if not target or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in target):
                raise ValueError('Ungültiger GitHub-Name')
            # Resolve outside the state lock; friendships use immutable GitHub IDs.
            if words[1] == 'add':
                try:
                    identity = request('https://api.github.com/users/' + target)
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
        with self.lock:
            targets = [peer]
            if cmd == 'friends':
                rows = self.db.execute('SELECT friend, login FROM friends WHERE owner=? ORDER BY login', (uid,)).fetchall()
                text = 'Freunde: ' + (', '.join(f'{login}: ' + ('online' if fid in self.peers else 'offline') for fid, login in rows) or 'keine')
            elif cmd == 'help':
                text = HELP
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
                    try:
                        target_peer.send('Du wurdest vom Admin getrennt.')
                        target_peer.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    text = f'{words[2]} wurde getrennt'
                elif sub == 'broadcast' and len(words) == 3:
                    targets = list(self.peers.values())
                    now = time.strftime('%H:%M:%S')
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
                peer.room = room
                text = 'Raum betreten: ' + room
            elif cmd == 'leave':
                peer.room = None
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
        for target in targets:
            try:
                target.send(text)
            except OSError:
                pass


def server_main():
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

    def handle(raw):
        peer = None
        try:
            raw.settimeout(30)
            with context.wrap_socket(raw, server_side=True) as sock, sock.makefile('rb') as stream:
                try:
                    token = receive(stream).get('token')
                    if not isinstance(token, str) or not token or len(token) > 4096:
                        raise ValueError('Token fehlt')
                    identity = request('https://api.github.com/user', token=token)
                    del token
                    candidate = Peer(sock, identity)
                    with chat.lock:
                        if identity['id'] in chat.peers:
                            raise ValueError('Konto bereits verbunden')
                        chat.peers[identity['id']] = candidate
                        peer = candidate
                except (ValueError, urllib.error.URLError) as err:
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
                    if not isinstance(line, str) or len(line) > 4000:
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
                with chat.lock:
                    if chat.peers.get(peer.identity['id']) is peer:
                        del chat.peers[peer.identity['id']]
            raw.close()
            slots.release()

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('0.0.0.0', args.port))
        listener.listen(100)
        print('Gitty TLS listening on', args.port, flush=True)
        while True:
            raw, _ = listener.accept()
            if slots.acquire(blocking=False):
                threading.Thread(target=handle, args=(raw,), daemon=True).start()
            else:
                raw.close()


HELP = '''Chat & Räume
  /rooms                  Aktive Räume anzeigen
  /create RAUM            Neuen Raum erstellen
  /join RAUM              Raum betreten
  /leave                  Aktuellen Raum verlassen
  /users                  Teilnehmer im Raum anzeigen
  /msg NAME TEXT          Direktnachricht senden

Freunde
  /friends                Freundesliste & Status anzeigen
  /friend add NAME        GitHub-Nutzer hinzufügen
  /friend remove NAME     Freund entfernen

Admin
  /admin online           Alle verbundenen Nutzer anzeigen
  /admin kick NAME        Nutzer trennen
  /admin broadcast TEXT   Ankündigung an alle senden

Allgemein
  /help                   Hilfe anzeigen
  /exit                   Verbindung trennen

Im Raum einfach schreiben. Räume und Nachrichten werden nicht gespeichert.'''

BANNER = '''\033[92m  _____ _ _   _         
 / ____(_) | | |        
| |  __ _| |_| |_ _   _ 
| | |_ | | __| __| | | |
| |__| | | |_| |_| |_| |
 \\_____|_|\\__|\\__|\\__, |
                  __/ |
                 |___/ \033[0m
\033[96m  Secure Terminal Messenger v5.0\033[0m'''


def format_help():
    import sys
    if not sys.stdout.isatty():
        return HELP
    lines = []
    section = ''
    for line in HELP.splitlines():
        if line and not line.startswith(' ') and not line.startswith('Im Raum'):
            section = line
            lines.append(f'\033[96m{line}\033[0m')
        elif line.startswith('  /exit'):
            cmd, desc = line[:26], line[26:]
            lines.append(f'\033[91m{cmd}\033[0m{desc}')
        elif line.startswith('  /'):
            color = '\033[93m' if section == 'Admin' else '\033[92m'
            cmd, desc = line[:26], line[26:]
            lines.append(f'{color}{cmd}\033[0m{desc}')
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
    if os.environ.get('GITTY_INSECURE'):
        # shortcut: cert check bypass for local testing only
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
