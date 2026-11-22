import json
import socket
import threading
import sys
from typing import Optional
from .animation import print_banner

from ..common import (
    ClientConfig,
    setup_logger,
    xor_encrypt,
    format_message_packet,
    parse_message_packet,
)


class GittyClient:
    def __init__(self, config: Optional[ClientConfig] = None):
        self.config = config or ClientConfig()
        self.logger = setup_logger("gitty.client", level="INFO")
        self.socket: Optional[socket.socket] = None
        self.username: str = ""
        self.encryption_key: str = ""
        self.state = "disconnected"
        self.running = False
        self.listener_thread: Optional[threading.Thread] = None

        self.C_RED = "\033[91m"
        self.C_GREEN = "\033[92m"
        self.C_YELLOW = "\033[93m"
        self.C_CYAN = "\033[96m"
        self.C_RESET = "\033[0m"

    def clear_screen(self) -> None:
        import os
        os.system("cls" if os.name == "nt" else "clear")

    def print_banner(self) -> None:
        banner = f"""{self.C_GREEN}
   ____ ___ _____ _____ __   __
  / ___|_ _|_   _|_   _| \\ \\ / /
 | |  _ | |  | |   | |    \\ V /
 | |_| || |  | |   | |     | |
  \\____|___| |_|   |_|     |_|
  {self.C_CYAN}Secure Terminal Messenger v4.1{self.C_RESET}
  {self.C_RESET}"""
        print_banner(banner)
        print("Tippe help für die verfügbaren Befehle.")

    def print_help(self) -> None:
        print(f"""
{self.C_CYAN}Commands:{self.C_RESET}
  {self.C_GREEN}Target:Message{self.C_RESET}          Send message to user
  {self.C_GREEN}Target:Message:Rating{self.C_RESET}   Send with rating (1-1000)
  {self.C_YELLOW}users{self.C_RESET}                    List online users
  {self.C_YELLOW}clear{self.C_RESET}                    Clear screen
  {self.C_YELLOW}status{self.C_RESET}                   Show connection status
  {self.C_YELLOW}help{self.C_RESET}                     Show this help
  {self.C_RED}exit{self.C_RESET}                     Disconnect and exit
""")

    def connect(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        key: Optional[str] = None,
    ) -> bool:
        self.state = "connecting"
        target_host = host or self.config.host
        target_port = port or self.config.port

        self.clear_screen()
        self.print_banner()
        print(f"[*] Connecting to {target_host}:{target_port}...\n")

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.config.connection_timeout)
            self.socket.connect((target_host, target_port))
            self.socket.settimeout(None)

            self.username = username or self.config.default_username or input("Username: ").strip()
            while not self.username:
                self.username = input("Username cannot be empty: ").strip()

            self.encryption_key = key or self.config.encryption_key or input("Encryption Key: ").strip()

            self.socket.send(self.username.encode("utf-8"))
            self.logger.info(f"Connected as '{self.username}' to {target_host}:{target_port}")

            self.state = "connected"
            self.running = True
            print(f"{self.C_GREEN}[+] Connection established.{self.C_RESET}\n")

            self.listener_thread = threading.Thread(target=self._listen, daemon=True)
            self.listener_thread.start()

            self._input_loop()
            return True

        except socket.timeout:
            print(f"{self.C_RED}[-] Connection timed out.{self.C_RESET}")
            self.logger.error("Connection timeout")
        except ConnectionRefusedError:
            print(f"{self.C_RED}[-] Connection refused.{self.C_RESET}")
            self.logger.error("Connection refused")
        except Exception as e:
            print(f"{self.C_RED}[-] Connection failed: {e}{self.C_RESET}")
            self.logger.error(f"Connection failed: {e}")

        self.state = "disconnected"
        return False

    def _listen(self) -> None:
        buffer = ""
        while self.running:
            try:
                assert self.socket is not None
                data = self.socket.recv(4096).decode("utf-8")
                if not data:
                    break

                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._handle_message(line)

            except socket.timeout:
                continue
            except (ConnectionAbortedError, OSError):
                break
            except Exception as e:
                self.logger.error(f"Listen error: {e}")
                break

        if self.running:
            print(f"\n{self.C_RED}[!] Disconnected from server.{self.C_RESET}")
        self.running = False
        self.state = "disconnected"

    def _handle_message(self, data: str) -> None:
        packet = parse_message_packet(data)
        sender = packet.get("from", "")
        content = packet.get("msg", "")
        rating = packet.get("rating", 0)
        timestamp = packet.get("timestamp")
        timestamp_label = f"[{timestamp}] " if timestamp else ""

        if sender == "SYSTEM":
            if "users" in packet:
                users = packet.get("users") or []
                online_users = ", ".join(users) if users else "(keine)"
                print(
                    f"\r{self.C_GREEN}{timestamp_label}[USERS] "
                    f"{online_users}{self.C_RESET}"
                )
            else:
                print(f"\r{self.C_GREEN}{timestamp_label}[SYS] {content}{self.C_RESET}")
        else:
            decrypted = xor_encrypt(content, self.encryption_key)
            stars = self._get_stars(rating)
            prefix = f"[{sender}]"
            if rating > 0:
                prefix += f" {stars}"
            print(
                f"\r{self.C_CYAN}{timestamp_label}{prefix} > "
                f"{decrypted}{self.C_RESET}"
            )

        if self.state == "connected":
            print(f"{self.C_GREEN}[{self.username}] > {self.C_RESET}", end="", flush=True)

    def _get_stars(self, rating: int) -> str:
        try:
            r = max(0, min(1000, int(rating)))
            return f"{self.C_YELLOW}{'★' * r}{self.C_RESET}"
        except (ValueError, TypeError):
            return ""

    def _input_loop(self) -> None:
        self.print_help()

        while self.running:
            try:
                msg = input(f"{self.C_GREEN}[{self.username}] > {self.C_RESET}")

                if not msg.strip():
                    continue

                if msg.lower() == "exit":
                    break
                elif msg.lower() in ("help", "/help"):
                    self.print_help()
                elif msg.lower() == "clear":
                    self.clear_screen()
                    self.print_banner()
                elif msg.lower() == "status":
                    self._print_status()
                elif msg.lower() == "users":
                    self._list_users()
                else:
                    self._send_message(msg)

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as e:
                print(f"{self.C_RED}[Error] {e}{self.C_RESET}")
                self.logger.error(f"Input error: {e}")

        self.disconnect()

    def _send_message(self, msg: str) -> None:
        if ":" not in msg:
            print(f"{self.C_RED}[!] Invalid format. Use: Target:Message{self.C_RESET}")
            return

        parts = msg.split(":")
        target = parts[0].strip()
        rating = 0

        if len(parts) >= 3:
            try:
                rating = int(parts[-1])
                content = ":".join(parts[1:-1])
            except ValueError:
                content = ":".join(parts[1:])
        else:
            content = parts[1]

        encrypted = xor_encrypt(content, self.encryption_key)
        packet = format_message_packet(self.username, encrypted, target, rating)

        try:
            assert self.socket is not None
            self.socket.send((packet + "\n").encode("utf-8"))
            print(f"{self.C_CYAN}Sent to {target}: {content}{self.C_RESET}")
        except Exception as e:
            print(f"{self.C_RED}[Error] Failed to send: {e}{self.C_RESET}")

    def _print_status(self) -> None:
        print(f"""
{self.C_CYAN}Connection Status:{self.C_RESET}
  State: {self.state}
  Username: {self.username}
  Server: {self.config.host}:{self.config.port}
""")

    def _list_users(self) -> None:
        try:
            assert self.socket is not None
            request = json.dumps({"command": "users"}) + "\n"
            self.socket.sendall(request.encode("utf-8"))
        except Exception as e:
            print(f"{self.C_RED}[Error] Failed to request users: {e}{self.C_RESET}")

    def disconnect(self) -> None:
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.state = "disconnected"
        print(f"\n{self.C_RED}[*] Session ended.{self.C_RESET}")


def main() -> None:
    from ..secure import client_main
    client_main()


if __name__ == "__main__":
    main()
