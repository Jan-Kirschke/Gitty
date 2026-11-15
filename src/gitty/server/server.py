import json
import socket
import threading
import time
import signal
import sys
from typing import Dict, Optional
from datetime import datetime

from ..common import (
    ServerConfig,
    setup_logger,
    parse_message_packet,
    validate_username,
)


class ClientConnection:
    def __init__(self, sock: socket.socket, addr: tuple, username: str):
        self.socket = sock
        self.address = addr
        self.username = username
        self.connected_at = time.time()
        self.last_ping = time.time()
        self.is_alive = True

    def update_activity(self):
        self.last_ping = time.time()

    def is_timed_out(self, timeout: float) -> bool:
        return (time.time() - self.last_ping) > timeout


class GittyServer:
    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or ServerConfig()
        self.logger = setup_logger(
            "gitty.server",
            log_file=self.config.log_file,
            level=self.config.log_level,
        )
        self.clients: Dict[str, ClientConnection] = {}
        self.clients_lock = threading.Lock()
        self.running = False
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ping_thread: Optional[threading.Thread] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.logger.info("Shutdown signal received")
        self.shutdown()

    def start(self) -> None:
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)

        try:
            self.server_socket.bind((self.config.host, self.config.port))
            self.server_socket.listen(self.config.max_clients)
            self.running = True
            self.logger.info(
                f"Server started on {self.config.host}:{self.config.port}"
            )

            self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
            self.ping_thread.start()

            self._accept_loop()

        except OSError as e:
            self.logger.error(f"Failed to start server: {e}")
            sys.exit(1)
        finally:
            self.shutdown()

    def _accept_loop(self) -> None:
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True,
                )
                thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _ping_loop(self) -> None:
        while self.running:
            time.sleep(self.config.ping_interval)
            self._check_client_timeouts()

    def _check_client_timeouts(self) -> None:
        with self.clients_lock:
            timed_out = [
                username
                for username, conn in self.clients.items()
                if conn.is_timed_out(self.config.ping_timeout + self.config.ping_interval)
            ]

        for username in timed_out:
            self._disconnect_client(username, "Connection timeout")

    def _handle_client(self, client_sock: socket.socket, addr: tuple) -> None:
        username: Optional[str] = None

        try:
            client_sock.settimeout(self.config.timeout)

            username = self._authenticate_client(client_sock, addr)
            if not username:
                client_sock.close()
                return

            self.logger.info(f"User '{username}' authenticated from {addr}")

            while self.running:
                try:
                    data = client_sock.recv(4096).decode("utf-8")
                    if not data:
                        break

                    for packet_data in data.split("\n"):
                        if not packet_data.strip():
                            continue
                        self._process_packet(username, packet_data)

                except socket.timeout:
                    continue
                except ConnectionResetError:
                    break

        except Exception as e:
            self.logger.error(f"Error handling client {addr}: {e}")
        finally:
            if username:
                self._disconnect_client(username, "Client disconnected")

    def _authenticate_client(
        self, client_sock: socket.socket, addr: tuple
    ) -> Optional[str]:
        try:
            username = client_sock.recv(1024).decode("utf-8").strip()
        except Exception:
            return None

        valid, error = validate_username(username)
        if not valid:
            self.logger.warning(f"Authentication failed for {addr}: {error}")
            return None

        with self.clients_lock:
            if username in self.clients:
                self.logger.warning(f"Username '{username}' already taken")
                self._send_error(client_sock, "Username already in use")
                return None

            conn = ClientConnection(client_sock, addr, username)
            self.clients[username] = conn

        self._broadcast_system(f"--- {username} joined the network ---", exclude=username)
        return username

    def _process_packet(self, sender: str, data: str) -> None:
        packet = parse_message_packet(data)
        if "error" in packet:
            self.logger.warning(f"Invalid packet from {sender}")
            return

        if packet.get("command") == "users":
            self._send_user_list(sender)
            return

        target = packet.get("to")
        if not target:
            return

        packet["from"] = sender
        packet["timestamp"] = packet.get("timestamp") or datetime.now().isoformat(
            timespec="seconds"
        )
        forward_packet = (json.dumps(packet) + "\n").encode("utf-8")

        with self.clients_lock:
            target_connection = self.clients.get(target)

        if target_connection:
            try:
                target_connection.socket.sendall(forward_packet)
                target_connection.update_activity()
            except Exception as e:
                self.logger.error(f"Failed to send to {target}: {e}")
        else:
            self._send_error_to_user(sender, f"User '{target}' is not online")

    def _send_user_list(self, username: str) -> None:
        with self.clients_lock:
            connection = self.clients.get(username)
            users = sorted(self.clients)

        if not connection:
            return

        user_packet = {
            "from": "SYSTEM",
            "msg": "Online users",
            "users": users,
            "rating": 0,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            connection.socket.sendall((json.dumps(user_packet) + "\n").encode("utf-8"))
            connection.update_activity()
        except Exception as e:
            self.logger.error(f"Failed to send user list to {username}: {e}")

    def _send_error_to_user(self, username: str, message: str) -> None:
        with self.clients_lock:
            if username not in self.clients:
                return
            self._send_error(self.clients[username].socket, message)

    def _send_error(self, sock: socket.socket, message: str) -> None:
        try:
            error_packet = {
                "from": "SYSTEM",
                "msg": message,
                "rating": 0,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            sock.sendall((json.dumps(error_packet) + "\n").encode("utf-8"))
        except Exception:
            pass

    def _broadcast_system(self, message: str, exclude: Optional[str] = None) -> None:
        system_packet = {
            "from": "SYSTEM",
            "msg": message,
            "rating": 0,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        encoded_packet = (json.dumps(system_packet) + "\n").encode("utf-8")
        with self.clients_lock:
            connections = [
                conn for username, conn in self.clients.items() if username != exclude
            ]

        for conn in connections:
            try:
                conn.socket.sendall(encoded_packet)
            except Exception as e:
                self.logger.error(f"Broadcast failed: {e}")

    def _disconnect_client(self, username: str, reason: str = "") -> None:
        with self.clients_lock:
            if username in self.clients:
                try:
                    self.clients[username].socket.close()
                except Exception:
                    pass
                del self.clients[username]

        self.logger.info(f"User '{username}' disconnected: {reason}")
        self._broadcast_system(f"--- {username} left the network ---")

    def shutdown(self) -> None:
        if not self.running:
            return
        self.running = False

        with self.clients_lock:
            usernames = list(self.clients.keys())

        for username in usernames:
            self._disconnect_client(username, "Server shutdown")

        try:
            self.server_socket.close()
        except Exception:
            pass

        self.logger.info("Server shutdown complete")


def main() -> None:
    config = ServerConfig()
    server = GittyServer(config)
    server.start()


if __name__ == "__main__":
    main()
