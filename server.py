import socket
import threading
import json
import logging
from datetime import datetime

# --- Konfiguration & Logging ---
HOST = '0.0.0.0'  # '0.0.0.0' erlaubt Verbindungen aus dem gesamten Netzwerk (wichtig für Pi)
PORT = 5555

# Logging Setup: Schreibt in Konsole UND in eine Datei 'gitty_server.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("gitty_server.log"),
        logging.StreamHandler()
    ]
)

# Speicher für aktive Nutzer: {'username': socket_obj}
clients = {}

def broadcast_system_msg(message, exclude_user=None):
    """Sendet eine System-Nachricht im JSON-Format an alle verbundenen Clients."""
    system_packet = json.dumps({
        "from": "SYSTEM",
        "msg": message,
        "rating": 0
    })
    
    for name, client_sock in list(clients.items()):
        if name != exclude_user:
            try:
                client_sock.send(system_packet.encode('utf-8'))
            except Exception as e:
                logging.error(f"Fehler beim Broadcast an {name}: {e}")

def handle_client(client_sock, addr):
    """Behandelt die Kommunikation mit einem einzelnen Client."""
    username = None
    logging.info(f"Neue Verbindung von Adresse: {addr}")

    try:
        # 1. Erster Empfang: Benutzername
        username = client_sock.recv(1024).decode('utf-8').strip()
        
        if not username or username in clients:
            logging.warning(f"Anmeldung abgelehnt: Name '{username}' ungültig oder vergeben.")
            client_sock.close()
            return

        clients[username] = client_sock
        logging.info(f"User '{username}' erfolgreich angemeldet.")
        broadcast_system_msg(f"--- {username} ist dem Netzwerk beigetreten ---", exclude_user=username)

        # 2. Nachrichten-Schleife
        while True:
            data = client_sock.recv(4096).decode('utf-8')
            if not data:
                break
            
            try:
                # Empfange das Paket vom Absender
                msg_obj = json.loads(data)
                target_user = msg_obj.get('to')
                
                # Wir fügen den Absendernamen zum Paket hinzu, bevor wir es weiterleiten
                msg_obj["from"] = username
                
                if target_user in clients:
                    # Das komplette Paket (inkl. msg, rating, etc.) weiterleiten
                    forward_packet = json.dumps(msg_obj)
                    clients[target_user].send(forward_packet.encode('utf-8'))
                else:
                    # Fehlermeldung an den Absender, falls Ziel nicht existiert
                    error_msg = json.dumps({
                        "from": "SYSTEM", 
                        "msg": f"User '{target_user}' ist nicht online.",
                        "rating": 0
                    })
                    client_sock.send(error_msg.encode('utf-8'))

            except json.JSONDecodeError:
                logging.error(f"Ungültiges JSON von {username} erhalten.")

    except Exception as e:
        logging.error(f"Fehler im Thread von {username if username else addr}: {e}")
    
    finally:
        # Aufräumen bei Verbindungsabbruch
        if username and username in clients:
            del clients[username]
            broadcast_system_msg(f"--- {username} hat das Netzwerk verlassen ---")
            logging.info(f"User '{username}' getrennt.")
        client_sock.close()

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Erlaubt den sofortigen Neustart des Ports nach einem Crash
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((HOST, PORT))
        server.listen()
        logging.info(f"Gitty-Server gestartet auf {HOST}:{PORT}")
    except Exception as e:
        logging.critical(f"Server konnte nicht starten: {e}")
        return

    while True:
        try:
            client_sock, addr = server.accept()
            thread = threading.Thread(target=handle_client, args=(client_sock, addr), daemon=True)
            thread.start()
        except KeyboardInterrupt:
            logging.info("Server wird durch User beendet...")
            break

if __name__ == "__main__":
    start_server()