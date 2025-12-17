import socket
import threading
import json

# Konfiguration
HOST = '127.0.0.1'
PORT = 5555

# Hier speichern wir die aktiven Nutzer: {'name': client_socket}
clients = {}

def broadcast(message, sender_name=None):
    """Sendet Systemnachrichten an alle."""
    for name, client in clients.items():
        if name != sender_name:
            try:
                client.send(message.encode('utf-8'))
            except:
                pass

def handle_client(client, addr):
    """Behandelt die Verbindung eines einzelnen Clients."""
    username = None
    try:
        # 1. Benutzername empfangen
        username = client.recv(1024).decode('utf-8')
        clients[username] = client
        print(f"[+] Neuer User: {username} ({addr})")
        broadcast(f"--- {username} ist dem Netzwerk beigetreten ---", username)

        # 2. Nachrichten-Schleife
        while True:
            data = client.recv(1024).decode('utf-8')
            if not data:
                break
            
            # Wir erwarten JSON: {"to": "Empfänger", "msg": "VerschlüsselterText"}
            try:
                msg_obj = json.loads(data)
                target_user = msg_obj.get('to')
                encrypted_content = msg_obj.get('msg')

                if target_user in clients:
                    # Weiterleiten an den Ziel-Nutzer
                    packet = json.dumps({"from": username, "msg": encrypted_content})
                    clients[target_user].send(packet.encode('utf-8'))
                else:
                    err = json.dumps({"from": "SYSTEM", "msg": f"User '{target_user}' nicht gefunden."})
                    client.send(err.encode('utf-8'))

            except json.JSONDecodeError:
                pass # Ignoriere fehlerhafte Daten

    except Exception as e:
        print(f"[-] Fehler bei {addr}: {e}")
    finally:
        # Aufräumen, wenn User geht
        if username and username in clients:
            del clients[username]
            client.close()
            broadcast(f"--- {username} hat das Netzwerk verlassen ---")
            print(f"[-] User getrennt: {username}")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[*] Gitty-Server läuft auf {HOST}:{PORT}")

    while True:
        client, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(client, addr))
        thread.start()

if __name__ == "__main__":
    start_server()