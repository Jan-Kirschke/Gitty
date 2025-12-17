import socket
import threading
import json
import sys
import base64

# --- Verschlüsselungs-Logik (Simuliert professionelle XOR-Crypto) ---
def encrypt_decrypt(text, key):
    """Verschlüsselt oder entschlüsselt Text mit einem Schlüssel."""
    result = []
    for i in range(len(text)):
        # XOR-Operation zwischen Zeichen und Schlüssel
        char_code = ord(text[i]) ^ ord(key[i % len(key)])
        result.append(chr(char_code))
    return "".join(result)

# --- Netzwerk-Logik ---
def receive_messages(client_socket, key):
    """Hört ständig auf neue Nachrichten."""
    while True:
        try:
            data = client_socket.recv(1024).decode('utf-8')
            if not data:
                break
            
            try:
                packet = json.loads(data)
                sender = packet.get("from")
                raw_msg = packet.get("msg")

                if sender == "SYSTEM":
                    print(f"\n[!] {raw_msg}")
                else:
                    # Nachricht entschlüsseln
                    decrypted = encrypt_decrypt(raw_msg, key)
                    print(f"\n[{sender}]: {decrypted}")
                    # Zeige auch den verschlüsselten "Hacker-Code" (optional)
                    # print(f"   (Raw Data: {repr(raw_msg)})") 
                    
                print("Du: ", end="", flush=True) # Eingabeaufforderung wiederherstellen
            except:
                print(f"\n{data}") # Fallback für reine Textnachrichten

        except:
            print("\n[!] Verbindung zum Server verloren.")
            client_socket.close()
            sys.exit()

def start_client():
    print("--- GITTY TERMINAL v3.1 ---")
    
    # Setup
    host = input("Server IP (Enter für localhost): ") or 'localhost'
    username = input("Dein Username: ")
    crypto_key = input("Verschlüsselungs-Key (muss mit Partner übereinstimmen): ")

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((host, 5555))
        # 1. Username senden zur Registrierung
        client.send(username.encode('utf-8'))
    except Exception as e:
        print(f"[-] Verbindung fehlgeschlagen: {e}")
        print("[!] Konnte keine Verbindung herstellen.")
        return

    # Starten des "Hörers" im Hintergrund
    thread = threading.Thread(target=receive_messages, args=(client, crypto_key))
    thread.daemon = True # Beendet Thread wenn Hauptprogramm endet
    thread.start()

    print(f"[*] Verbunden als {username}. Format: 'Empfänger:Nachricht'")
    
    # 2. Sende-Schleife
    while True:
        try:
            msg_input = input("Du: ")
            
            if ":" in msg_input:
                target, content = msg_input.split(":", 1)
                
                # Verschlüsseln VOR dem Senden
                encrypted_content = encrypt_decrypt(content, crypto_key)
                
                # Als JSON verpacken
                packet = json.dumps({"to": target.strip(), "msg": encrypted_content})
                client.send(packet.encode('utf-8'))
            else:
                print("[!] Falsches Format! Nutze: 'Name:Nachricht'")
                
        except KeyboardInterrupt:
            print("\n[!] Beende Gitty.")
            client.close()
            break

if __name__ == "__main__":
    start_client()