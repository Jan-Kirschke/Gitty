import socket
import threading
import json
import sys
import os

class GittyClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.username = ""
        self.key = ""
        self.running = True
        
        self.C_RED = "\033[91m"
        self.C_GREEN = "\033[92m"
        self.C_CYAN = "\033[96m"
        self.C_RESET = "\033[0m"

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def print_banner(self):
        banner = f"""{self.C_GREEN}
      _____ _ _   _           
     / ____(_) | | |          
    | |  __ _| |_| |_ _   _   
    | | |_ | | __| __| | | |  
    | |__| | | |_| |_| |_| |  
     \_____|_|\__|\__|\__, |  
                       __/ |  
    TERMINAL v3.1     |___/   
    {self.C_RESET}"""
        print(banner)

    def xor_cipher(self, text):
        result = []
        for i in range(len(text)):
            char_code = ord(text[i]) ^ ord(self.key[i % len(self.key)])
            result.append(chr(char_code))
        return "".join(result)

    def listen(self):
        while self.running:
            try:
                data = self.sock.recv(4096).decode('utf-8')
                if not data:
                    break
                
                try:
                    pkg = json.loads(data)
                    sender = pkg.get("from")
                    payload = pkg.get("msg")

                    if sender == "SYSTEM":
                        print(f"\r{self.C_GREEN}[!] {payload}{self.C_RESET}")
                    else:
                        decrypted = self.xor_cipher(payload)
                        print(f"\r{self.C_CYAN}[{sender}] > {decrypted}{self.C_RESET}")
                    
                    print(f"{self.C_GREEN}[Me] > {self.C_RESET}", end="", flush=True)
                
                except json.JSONDecodeError:
                    print(f"\r[raw] {data}")

            except ConnectionAbortedError:
                break
            except Exception:
                break
        
        print(f"\n{self.C_RED}[!] Disconnected from server.{self.C_RESET}")
        self.sock.close()
        sys.exit()

    def connect(self):
        self.clear_screen()
        self.print_banner()
        
        raw_host = input(f"Target IP [default: localhost]: ").strip()
        
        if ":" in raw_host:
            raw_host = raw_host.split(":")[0]
        
        if raw_host in ["", "0.0.0.0"]:
            host = "127.0.0.1"
        else:
            host = raw_host

        self.username = input("Username: ").strip()
        while not self.username:
            self.username = input("Username cannot be empty: ").strip()

        self.key = input("Encryption Key: ").strip()
        
        print(f"\n[*] Connecting to {host}:5555...")

        try:
            self.sock.connect((host, 5555))
            self.sock.send(self.username.encode('utf-8'))
            print(f"{self.C_GREEN}[+] Connection established.{self.C_RESET}\n")
            
            listener = threading.Thread(target=self.listen, daemon=True)
            listener.start()

            self.input_loop()

        except Exception as e:
            print(f"{self.C_RED}[-] Connection failed: {e}{self.C_RESET}")

    def input_loop(self):
        print(f"Format: {self.C_CYAN}Target:Message{self.C_RESET}")
        
        while True:
            try:
                msg = input(f"{self.C_GREEN}[Me] > {self.C_RESET}")
                
                if ":" in msg:
                    target, text = msg.split(":", 1)
                    encrypted = self.xor_cipher(text)
                    packet = json.dumps({"to": target.strip(), "msg": encrypted})
                    self.sock.send(packet.encode('utf-8'))
                elif msg.lower() == "exit":
                    break
                else:
                    print(f"{self.C_RED}[!] Invalid format. Use User:Message{self.C_RESET}")
                    
            except KeyboardInterrupt:
                break
            except Exception:
                break

        self.running = False
        self.sock.close()
        print(f"\n{self.C_RED}[*] Session ended.{self.C_RESET}")

if __name__ == "__main__":
    client = GittyClient()
    client.connect()