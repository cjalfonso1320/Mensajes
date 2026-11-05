import socket
import threading
import json
import time
import base64

try:
    from image_utils import encode_image_bytes, PIL_AVAILABLE
except ImportError:
    PIL_AVAILABLE = False

def get_local_ip():
    """Detecta la IP local de esta máquina en la red LAN."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

class MessageServer:
    def __init__(self, host="0.0.0.0", port=5050, discovery_port=5055, on_clients_change=None, on_message_received=None, on_whatsapp_status_change=None):
        self.host = host
        self.port = port
        self.discovery_port = discovery_port
        self.server_socket = None
        self.beacon_socket = None
        self.running = False
        
        # Diccionario de clientes conectados:
        # { socket: {"role": "gadget"|"admin", "name": "...", "addr": (ip, port), "file": file_obj} }
        self.clients = {}
        self.lock = threading.Lock()
        
        # Callbacks opcionales para la interfaz gráfica del admin
        self.on_clients_change = on_clients_change
        self.on_message_received = on_message_received
        self.on_whatsapp_status_change = on_whatsapp_status_change

    def start(self):
        """Inicia el servidor en un hilo secundario y la baliza de autodescubrimiento."""
        if self.running:
            return
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(50)
        
        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()

        # Iniciar baliza UDP para autodescubrimiento en la red local
        beacon_thread = threading.Thread(target=self._beacon_loop, daemon=True)
        beacon_thread.start()

        print(f"[SERVIDOR] Escuchando en {self.host}:{self.port} (IP Local: {get_local_ip()})")
        print(f"[SERVIDOR] Baliza UDP activa en puerto {self.discovery_port}")

    def _beacon_loop(self):
        """Emite una baliza UDP periódicamente para que los gadgets encuentren este servidor automáticamente."""
        try:
            self.beacon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.beacon_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception as e:
            print(f"[SERVIDOR] Error iniciando socket de baliza: {e}")
            return

        while self.running:
            try:
                ip = get_local_ip()
                payload = {
                    "service": "AdminMessenger",
                    "ip": ip,
                    "port": self.port,
                    "hostname": socket.gethostname()
                }
                raw = (json.dumps(payload) + "\n").encode("utf-8")
                self.beacon_socket.sendto(raw, ("<broadcast>", self.discovery_port))
            except Exception:
                pass
            time.sleep(2)
        print(f"[SERVIDOR] Escuchando en {self.host}:{self.port} (IP Local: {get_local_ip()})")

    def _accept_loop(self):
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                f_in = client_sock.makefile('r', encoding='utf-8')
                with self.lock:
                    self.clients[client_sock] = {
                        "role": "unknown",
                        "name": f"{addr[0]}:{addr[1]}",
                        "addr": addr,
                        "file": f_in
                    }
                
                t = threading.Thread(target=self._handle_client, args=(client_sock, addr, f_in), daemon=True)
                t.start()
            except Exception as e:
                if not self.running:
                    break
                print(f"[SERVIDOR] Error en accept: {e}")

    def _handle_client(self, client_sock, addr, f_in):
        try:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._process_message(client_sock, data)
                except json.JSONDecodeError:
                    print(f"[SERVIDOR] Mensaje inválido de {addr}: {line}")
        except Exception:
            pass
        finally:
            self._disconnect_client(client_sock)

    def _disconnect_client(self, client_sock):
        info = None
        with self.lock:
            if client_sock in self.clients:
                info = self.clients.pop(client_sock)
                try:
                    info["file"].close()
                except Exception:
                    pass
                try:
                    client_sock.close()
                except Exception:
                    pass
                print(f"[SERVIDOR] Cliente desconectado: {info['name']}")
        
        if info and (info.get("role") == "whatsapp" or "WhatsApp" in info.get("name", "")):
            if self.on_whatsapp_status_change:
                self.on_whatsapp_status_change("disconnected", "")

        self._notify_clients_update()

    def _process_message(self, client_sock, data):
        msg_type = data.get("type")
        
        if msg_type == "register":
            role = data.get("role", "gadget")
            name = data.get("name", "Usuario")
            hostname = data.get("hostname", "Desconocido")
            with self.lock:
                if client_sock in self.clients:
                    self.clients[client_sock]["role"] = role
                    self.clients[client_sock]["name"] = name
                    self.clients[client_sock]["hostname"] = hostname
            print(f"[SERVIDOR] Registrado {role.upper()}: {name} [{hostname}]")
            self._notify_clients_update()

        elif msg_type == "whatsapp_status":
            status = data.get("status", "disconnected")
            phone = data.get("phone", "")
            print(f"[SERVIDOR] Estado de WhatsApp recibido: {status} (Tel: {phone})")
            if self.on_whatsapp_status_change:
                self.on_whatsapp_status_change(status, phone)
            
        elif msg_type == "broadcast":
            # El administrador envía un comunicado general a todos los gadgets
            title = data.get("title", "Comunicado")
            content = data.get("content", "")
            priority = data.get("priority", "info") # "info", "warning", "urgent"
            timestamp = data.get("timestamp", time.strftime("%H:%M:%S"))
            sender = data.get("sender", "Administrador")
            image = data.get("image")
            if image and PIL_AVAILABLE:
                try:
                    # WhatsApp puede enviar fotos originales de varios MB. Reducirlas
                    # aquí antes de replicar el JSON a todos los gadgets.
                    encoded = image.split(",", 1)[1] if image.startswith("data:") else image
                    image = encode_image_bytes(base64.b64decode(encoded, validate=True))
                except Exception as exc:
                    print(f"[SERVIDOR] Imagen inválida; se enviará el comunicado sin imagen: {exc}")
                    image = None

            payload = {
                "type": "new_message",
                "title": title,
                "content": content,
                "priority": priority,
                "timestamp": timestamp,
                "sender": sender,
                "image": image
            }

            delivered_count = self.broadcast_to_gadgets(payload)
            
            # Responder al admin con confirmación
            ack = {
                "type": "broadcast_ack",
                "status": "ok",
                "delivered_to": delivered_count,
                "timestamp": timestamp
            }
            self.send_to_client(client_sock, ack)
            
            if self.on_message_received:
                self.on_message_received(payload, delivered_count)

    def broadcast_to_gadgets(self, payload):
        """Envía el paquete a todos los clientes cuyo rol sea 'gadget'."""
        targets = []
        with self.lock:
            for sock, info in self.clients.items():
                if info["role"] == "gadget":
                    targets.append(sock)
        
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        sent = 0
        for sock in targets:
            try:
                sock.sendall(raw)
                sent += 1
            except Exception:
                pass
        return sent

    def send_to_client(self, client_sock, payload):
        """Envía un paquete individual a un cliente."""
        try:
            raw = (json.dumps(payload) + "\n").encode("utf-8")
            client_sock.sendall(raw)
        except Exception:
            pass

    def get_gadget_clients(self):
        """Devuelve la lista de gadgets activos."""
        result = []
        with self.lock:
            for sock, info in self.clients.items():
                if info["role"] == "gadget":
                    result.append({
                        "name": info["name"],
                        "hostname": info.get("hostname", "Desconocido"),
                        "ip": info["addr"][0],
                        "port": info["addr"][1]
                    })
        return result

    def _notify_clients_update(self):
        gadgets = self.get_gadget_clients()
        # Notificar a los administradores
        update_payload = {
            "type": "clients_update",
            "count": len(gadgets),
            "gadgets": gadgets
        }
        
        with self.lock:
            admins = [s for s, info in self.clients.items() if info["role"] == "admin"]
            
        raw = (json.dumps(update_payload) + "\n").encode("utf-8")
        for admin_sock in admins:
            try:
                admin_sock.sendall(raw)
            except Exception:
                pass

        if self.on_clients_change:
            self.on_clients_change(gadgets)

    def stop(self):
        self.running = False
        if self.beacon_socket:
            try:
                self.beacon_socket.close()
            except Exception:
                pass
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        with self.lock:
            for sock in list(self.clients.keys()):
                try:
                    sock.close()
                except Exception:
                    pass
            self.clients.clear()

if __name__ == "__main__":
    server = MessageServer()
    server.start()
    print("Presiona Ctrl+C para detener el servidor.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("Servidor detenido.")

