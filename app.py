import tkinter as tk
from tkinter import messagebox
import time
import datetime
import socket
import threading
import json
import os
import winsound
from user_info import get_ad_user_info

try:
    from PIL import Image as PILImage, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

CONFIG_FILE = "gadget_config.json"

class FloatingGadget:
    def __init__(self):
        self.root = tk.Tk()
        
        # 1. Cargar Configuración de Conexión
        self.config = self.load_config()
        self.server_ip = self.config.get("server_ip", "127.0.0.1")
        self.server_port = int(self.config.get("server_port", 5050))
        self.client_name = self.config.get("client_name", socket.gethostname())
        
        # Estado de conexión y último mensaje
        self.connected = False
        self.sock = None
        self.running = True
        self.last_message = None
        self.is_expanded = False
        
        # Estado de imagen recibida
        self.last_image_b64 = None
        self.image_window = None      # Tk.Toplevel del visor
        self._photo_ref = None        # Referencia para evitar GC de PhotoImage
        self._thumb_ref = None        # Referencia del thumbnail en la notificación
        
        # 2. Configuración de ventana flotante sin bordes
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.90)  # Transparencia del 90%
        
        # Dimensiones para los dos estados
        self.compact_geo = "240x105+60+60"
        self.expanded_geo = "340x200+60+60"
        self.root.geometry(self.compact_geo)
        self.root.configure(bg="#1e1e1e")
        
        # 3. Marco Principal con borde
        self.frame = tk.Frame(self.root, bg="#1e1e1e", highlightbackground="#00d2d3", highlightthickness=1)
        self.frame.pack(expand=True, fill="both")
        
        # 4. Construcción de UI (Vistas Compacta y de Notificación)
        self.create_widgets()
        
        # 5. Arrastre con el ratón
        self.bind_drag(self.frame)
        self.bind_drag(self.title_bar)
        self.bind_drag(self.title_label)
        
        # 6. Actualizar reloj
        self.update_clock()
        
        # 7. Iniciar hilo de conexión en segundo plano
        self.net_thread = threading.Thread(target=self.network_loop, daemon=True)
        self.net_thread.start()

    def load_config(self):
        ad_name = get_ad_user_info()
        default = {
            "server_ip": "auto",  # 'auto' para autodescubrimiento por baliza UDP en LAN
            "server_port": 5050,
            "client_name": ad_name
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    saved_name = cfg.get("client_name", "")
                    # Si no tenía nombre o era el nombre del equipo, sustituir con el nombre de AD
                    if not saved_name or saved_name == socket.gethostname() or saved_name == "Usuario":
                        cfg["client_name"] = ad_name
                    # Si la IP guardada era la de pruebas local o vacía, pasar a modo automático
                    if not cfg.get("server_ip") or cfg.get("server_ip") == "127.0.0.1":
                        cfg["server_ip"] = "auto"
                    return {**default, **cfg}
            except Exception:
                pass
        return default

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "server_ip": self.server_ip,
                    "server_port": self.server_port,
                    "client_name": self.client_name
                }, f, indent=4)
        except Exception:
            pass

    def create_widgets(self):
        # Barra superior con título y controles
        self.title_bar = tk.Frame(self.frame, bg="#252526", height=24)
        self.title_bar.pack(fill="x", side="top")
        
        # Indicador de estado (punto verde/rojo)
        self.status_dot = tk.Label(self.title_bar, text="●", fg="#e74c3c", bg="#252526", font=("Segoe UI", 10))
        self.status_dot.pack(side="left", padx=(8, 2))
        
        # Título
        self.title_label = tk.Label(self.title_bar, text="Gadget de Mensajes", fg="#00d2d3", 
                                    bg="#252526", font=("Segoe UI", 9, "bold"))
        self.title_label.pack(side="left", padx=2)
        
        # Botón Configuración (⚙)
        self.btn_settings = tk.Button(self.title_bar, text="⚙", command=self.open_settings, 
                                      bg="#252526", fg="#888888", bd=0, font=("Arial", 10),
                                      activebackground="#333333", activeforeground="white", cursor="hand2")
        self.btn_settings.pack(side="right", padx=2)
        
        # Acceso destacado al último comunicado, incluso después de marcarlo entendido.
        self.btn_history = tk.Button(self.title_bar, text="✉ Último", command=self.show_last_message,
                                     bg="#0984e3", fg="#ffffff", bd=0,
                                     font=("Segoe UI", 8, "bold"),
                                     activebackground="#74b9ff", activeforeground="#ffffff",
                                     cursor="hand2", padx=6, pady=2)
        self.btn_history.pack(side="right", padx=(3, 5), pady=2)

        # ----------------- VISTA COMPACTA (RELOJ Y ESTADO) -----------------
        self.compact_view = tk.Frame(self.frame, bg="#1e1e1e")
        self.compact_view.pack(expand=True, fill="both")
        
        # Hora en formato 12 Horas
        self.time_label = tk.Label(self.compact_view, text="", fg="#ffffff", bg="#1e1e1e", font=("Segoe UI", 14, "bold"))
        self.time_label.pack(pady=(3, 0))
        
        # Fecha en formato small debajo de la hora
        self.date_label = tk.Label(self.compact_view, text="", fg="#a0a0a0", bg="#1e1e1e", font=("Segoe UI", 8))
        self.date_label.pack(pady=(0, 2))
        
        # Estado de conexión
        self.status_label = tk.Label(self.compact_view, text="Conectando al servidor...", 
                                     fg="#666666", bg="#1e1e1e", font=("Segoe UI", 7))
        self.status_label.pack(pady=(0, 2))
        
        self.bind_drag(self.compact_view)
        self.bind_drag(self.time_label)
        self.bind_drag(self.date_label)
        self.bind_drag(self.status_label)

        # ----------------- VISTA NOTIFICACIÓN EXPANDIDA -----------------
        self.message_view = tk.Frame(self.frame, bg="#1e1e1e", padx=10, pady=8)
        
        self.lbl_msg_header = tk.Label(self.message_view, text="", font=("Segoe UI", 10, "bold"), 
                                       fg="#ffffff", bg="#1e1e1e", anchor="w")
        self.lbl_msg_header.pack(fill="x")
        
        self.lbl_msg_title = tk.Label(self.message_view, text="", font=("Segoe UI", 11, "bold"), 
                                      fg="#00d2d3", bg="#1e1e1e", anchor="w")
        self.lbl_msg_title.pack(fill="x", pady=(2, 4))
        
        self.lbl_msg_body = tk.Label(self.message_view, text="", font=("Segoe UI", 9), 
                                     fg="#e0e0e0", bg="#1e1e1e", justify="left", 
                                     wraplength=310, anchor="w")
        self.lbl_msg_body.pack(fill="both", expand=True, pady=(2, 6))
        
        # Thumbnail de imagen (oculto por defecto)
        self.img_thumb_label = tk.Label(self.message_view, bg="#1e1e1e", cursor="hand2",
                                        relief="flat", bd=0)
        # Se muestra solo cuando hay imagen, NO pack aquí
        
        bottom_row = tk.Frame(self.message_view, bg="#1e1e1e")
        bottom_row.pack(fill="x")
        
        self.lbl_msg_time = tk.Label(bottom_row, text="", font=("Segoe UI", 8), 
                                     fg="#777777", bg="#1e1e1e")
        self.lbl_msg_time.pack(side="left")
        
        # Botón toggle visor imagen (oculto por defecto)
        self.btn_toggle_img = tk.Button(bottom_row, text="🖼️ Ver imagen",
                                        command=self.toggle_image_viewer,
                                        bg="#333333", fg="#00d2d3", font=("Segoe UI", 8),
                                        relief="flat", activebackground="#444444",
                                        cursor="hand2", padx=5)
        # Se muestra solo cuando hay imagen, NO pack aquí
        
        self.btn_ack = tk.Button(bottom_row, text="✓ Entendido", command=self.collapse_message, 
                                 bg="#0984e3", fg="white", font=("Segoe UI", 9, "bold"), 
                                 bd=0, padx=8, pady=2, cursor="hand2")
        self.btn_ack.pack(side="right")
        
        self.bind_drag(self.message_view)
        self.bind_drag(self.lbl_msg_header)
        self.bind_drag(self.lbl_msg_title)
        self.bind_drag(self.lbl_msg_body)

    # ----------------- ARRASTRE DE VENTANA -----------------
    def bind_drag(self, widget):
        widget.bind("<Button-1>", self.start_move)
        widget.bind("<B1-Motion>", self.do_move)

    def start_move(self, event):
        self.x = event.x_root - self.root.winfo_x()
        self.y = event.y_root - self.root.winfo_y()

    def do_move(self, event):
        x = event.x_root - self.x
        y = event.y_root - self.y
        self.root.geometry(f"+{x}+{y}")

    def update_clock(self):
        now = datetime.datetime.now()
        # Hora en formato 12 Horas con AM/PM (ej. "03:30:15 PM")
        current_time = now.strftime("%I:%M:%S %p")
        self.time_label.config(text=current_time)
        
        # Fecha en formato small en español debajo de la hora (ej. "Mié, 04 Nov 2026")
        dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        date_str = f"{dias[now.weekday()]}, {now.day:02d} {meses[now.month-1]} {now.year}"
        self.date_label.config(text=date_str)
        
        self.root.after(1000, self.update_clock)

    def safe_after(self, delay, callback):
        """Ejecuta una función en el hilo principal de Tkinter de forma segura."""
        if self.running:
            try:
                self.root.after(delay, callback)
            except Exception:
                pass

    # ----------------- RED Y AUTODESCUBRIMIENTO -----------------
    def discover_server(self, timeout=2.0):
        """Escucha balizas UDP en la red local para localizar el servidor del Administrador."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", 5055))
            sock.settimeout(timeout)
            data, addr = sock.recvfrom(1024)
            info = json.loads(data.decode("utf-8").strip())
            if info.get("service") == "AdminMessenger":
                discovered_ip = info.get("ip") or addr[0]
                discovered_port = int(info.get("port", 5050))
                return discovered_ip, discovered_port
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
        return None, None

    def network_loop(self):
        """Intenta conectarse al servidor y mantenerse escuchando."""
        while self.running:
            target_ip = self.server_ip
            target_port = self.server_port
            
            # Si está configurado en automático o no tiene IP fija
            if target_ip == "auto" or not target_ip:
                self.safe_after(0, lambda: self.status_label.config(text="Buscando servidor en la red...", fg="#f39c12"))
                disc_ip, disc_port = self.discover_server(timeout=2.0)
                if disc_ip:
                    target_ip = disc_ip
                    target_port = disc_port
                else:
                    time.sleep(1)
                    continue

            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5)
                self.sock.connect((target_ip, target_port))
                self.sock.settimeout(None)
                
                # Enviar registro con nombre de usuario AD y nombre de máquina
                reg_payload = {
                    "type": "register",
                    "role": "gadget",
                    "name": self.client_name,
                    "hostname": socket.gethostname()
                }
                raw = (json.dumps(reg_payload) + "\n").encode("utf-8")
                self.sock.sendall(raw)
                
                self.connected = True
                self.safe_after(0, lambda ip=target_ip: self.on_connected(ip))
                
                # Leer mensajes del servidor línea por línea
                f_in = self.sock.makefile('r', encoding='utf-8')
                for line in f_in:
                    if not line:
                        break
                    try:
                        msg = json.loads(line.strip())
                        if msg.get("type") == "new_message":
                            self.safe_after(0, lambda m=msg: self.handle_new_message(m))
                    except json.JSONDecodeError:
                        pass
                        
            except Exception:
                pass
            finally:
                self.connected = False
                self.safe_after(0, lambda ip=target_ip: self.on_disconnected(ip))
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
            
            # Esperar antes de reintentar
            time.sleep(2)

    def on_connected(self, ip):
        self.status_dot.config(fg="#2ecc71") # Verde
        self.status_label.config(text=f"Conectado a {ip}", fg="#2ecc71")

    def on_disconnected(self, ip):
        self.status_dot.config(fg="#e74c3c") # Rojo
        if self.server_ip == "auto":
            self.status_label.config(text="Buscando servidor en la red...", fg="#888888")
        else:
            self.status_label.config(text=f"Reconectando a {ip}...", fg="#888888")

    # ----------------- GESTIÓN DE MENSAJES RECIBIDOS -----------------
    def handle_new_message(self, msg):
        self.last_message = msg
        priority = msg.get("priority", "info")
        title = msg.get("title", "Comunicado")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", time.strftime("%H:%M:%S"))
        sender = msg.get("sender", "Administrador")
        image_b64 = msg.get("image", None)
        
        # Configurar colores y estilos según prioridad
        if priority == "urgent":
            accent = "#e74c3c" # Rojo
            header_text = f"🚨 COMUNICADO URGENTE de {sender}"
            # Alerta sonora en Windows
            try:
                winsound.MessageBeep(winsound.MB_ICONHAND)
            except Exception:
                pass
        elif priority == "warning":
            accent = "#f39c12" # Naranja
            header_text = f"⚠️ AVISO IMPORTANTE de {sender}"
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        else:
            accent = "#00d2d3" # Azul/Cyan
            header_text = f"ℹ️ Comunicado de {sender}"
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        
        # Actualizar widgets de texto
        self.frame.config(highlightbackground=accent, highlightthickness=2)
        self.lbl_msg_header.config(text=header_text, fg=accent)
        self.lbl_msg_title.config(text=title, fg="#ffffff")
        self.lbl_msg_body.config(text=content)
        self.lbl_msg_time.config(text=f"Recibido: {timestamp}")
        self.btn_ack.config(bg=accent)
        
        # --- Manejar imagen ---
        # Cerrar visor anterior si estaba abierto
        self._close_image_window()
        
        if image_b64 and PIL_AVAILABLE:
            self.last_image_b64 = image_b64
            try:
                from image_utils import make_thumbnail
                thumb_img = make_thumbnail(image_b64, max_width=300)
                photo_thumb = ImageTk.PhotoImage(thumb_img)
                self._thumb_ref = photo_thumb
                self.img_thumb_label.config(image=photo_thumb)
                self.img_thumb_label.pack(fill="x", pady=(0, 4))
                self.img_thumb_label.bind("<Button-1>", lambda e: self.toggle_image_viewer())
                self.btn_toggle_img.config(text="🖼️ Ver imagen")
                self.btn_toggle_img.pack(side="right", padx=(0, 4))
                expand_height = 370
            except Exception:
                self.last_image_b64 = None
                self.img_thumb_label.pack_forget()
                self.btn_toggle_img.pack_forget()
                expand_height = 220
        else:
            self.last_image_b64 = None
            self.img_thumb_label.pack_forget()
            self.btn_toggle_img.pack_forget()
            expand_height = 220
        
        # Expandir la ventana
        self.expand_message(expand_height)

    def expand_message(self, height=220):
        self.is_expanded = True
        self.compact_view.pack_forget()
        self.message_view.pack(expand=True, fill="both")
        
        # Mantener posición actual pero agrandar
        curr_x = self.root.winfo_x()
        curr_y = self.root.winfo_y()
        self.root.geometry(f"340x{height}+{curr_x}+{curr_y}")

    def collapse_message(self):
        self.is_expanded = False
        # Cerrar visor de imagen si está abierto
        self._close_image_window()
        # Ocultar widgets de imagen
        self.img_thumb_label.pack_forget()
        self.btn_toggle_img.pack_forget()
        self.last_image_b64 = None
        self._thumb_ref = None
        
        self.message_view.pack_forget()
        self.compact_view.pack(expand=True, fill="both")
        
        # Restablecer borde normal
        self.frame.config(highlightbackground="#00d2d3", highlightthickness=1)
        
        curr_x = self.root.winfo_x()
        curr_y = self.root.winfo_y()
        self.root.geometry(f"240x105+{curr_x}+{curr_y}")

    def toggle_image_viewer(self):
        """Alterna la apertura/cierre del visor de imagen."""
        if self.image_window and self.image_window.winfo_exists():
            self._close_image_window()
        else:
            self._open_image_viewer()

    def _open_image_viewer(self):
        """Abre una ventana Toplevel con la imagen a tamaño completo."""
        if not self.last_image_b64 or not PIL_AVAILABLE:
            return
        try:
            from image_utils import decode_image_b64
            img = decode_image_b64(self.last_image_b64)
            
            # Ajustar al tamaño de pantalla (máx 900x650)
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            max_w = min(900, int(screen_w * 0.75))
            max_h = min(650, int(screen_h * 0.75))
            img.thumbnail((max_w, max_h), PILImage.LANCZOS)
            
            win = tk.Toplevel(self.root)
            win.title("🖼️ Imagen del Comunicado")
            win.configure(bg="#1e1e1e")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            
            photo = ImageTk.PhotoImage(img)
            self._photo_ref = photo  # Mantener referencia para evitar GC
            
            lbl = tk.Label(win, image=photo, bg="#1e1e1e", cursor="hand2")
            lbl.pack(padx=10, pady=10)
            
            btn_cerrar = tk.Button(win, text="✕  Cerrar imagen",
                                   command=self._close_image_window,
                                   bg="#333333", fg="#ffffff", font=("Segoe UI", 9),
                                   relief="flat", activebackground="#e74c3c",
                                   cursor="hand2", pady=4)
            btn_cerrar.pack(fill="x", padx=10, pady=(0, 10))
            
            win.protocol("WM_DELETE_WINDOW", self._close_image_window)
            self.image_window = win
            self.btn_toggle_img.config(text="🖼️ Cerrar imagen")
            
            # Centrar la ventana del visor en pantalla
            win.update_idletasks()
            x = (screen_w - win.winfo_width()) // 2
            y = (screen_h - win.winfo_height()) // 2
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _close_image_window(self):
        """Cierra el visor de imagen si está abierto."""
        if self.image_window:
            try:
                if self.image_window.winfo_exists():
                    self.image_window.destroy()
            except Exception:
                pass
            self.image_window = None
            self._photo_ref = None
        try:
            self.btn_toggle_img.config(text="🖼️ Ver imagen")
        except Exception:
            pass

    def show_last_message(self):
        if self.last_message:
            self.handle_new_message(self.last_message)
        else:
            messagebox.showinfo("Bandeja", "No has recibido ningún mensaje aún.")

    # ----------------- CONFIGURACIÓN -----------------
    def open_settings(self):
        cfg_win = tk.Toplevel(self.root)
        cfg_win.title("Ajustes del Gadget")
        cfg_win.geometry("320x290")
        cfg_win.configure(bg="#252526")
        cfg_win.resizable(False, False)
        cfg_win.attributes("-topmost", True)
        
        tk.Label(cfg_win, text="⚙️ Conexión al Servidor LAN", fg="#00d2d3", bg="#252526", 
                 font=("Segoe UI", 10, "bold")).pack(pady=(10, 8))
        
        # IP Servidor
        ip_header = tk.Frame(cfg_win, bg="#252526")
        ip_header.pack(fill="x", padx=20)
        tk.Label(ip_header, text="IP del Servidor (Admin):", fg="#ffffff", bg="#252526", font=("Segoe UI", 9)).pack(side="left")
        
        entry_ip = tk.Entry(cfg_win, font=("Segoe UI", 10), bg="#1e1e1e", fg="#ffffff", insertbackground="white")
        entry_ip.pack(fill="x", padx=20, pady=(2, 4))
        entry_ip.insert(0, self.server_ip)
        
        # Checkbox para modo automático
        self.auto_ip_var = tk.BooleanVar(value=(self.server_ip == "auto"))
        
        def toggle_auto():
            if self.auto_ip_var.get():
                entry_ip.delete(0, tk.END)
                entry_ip.insert(0, "auto")
                entry_ip.config(state="disabled")
            else:
                entry_ip.config(state="normal")
                if entry_ip.get() == "auto":
                    entry_ip.delete(0, tk.END)
                    entry_ip.insert(0, "10.20.10.36")
        
        chk_auto = tk.Checkbutton(cfg_win, text="🔍 Detección automática en red (Recomendado)", 
                                  variable=self.auto_ip_var, command=toggle_auto,
                                  bg="#252526", fg="#00d2d3", selectcolor="#1e1e1e",
                                  activebackground="#252526", activeforeground="#00d2d3",
                                  font=("Segoe UI", 8))
        chk_auto.pack(anchor="w", padx=20, pady=(0, 8))
        
        if self.server_ip == "auto":
            entry_ip.config(state="disabled")
            
        # Nombre del Usuario (AD)
        name_hdr = tk.Frame(cfg_win, bg="#252526")
        name_hdr.pack(fill="x", padx=20)
        tk.Label(name_hdr, text="Nombre del Usuario:", fg="#ffffff", bg="#252526", font=("Segoe UI", 9)).pack(side="left")
        
        def reload_from_ad():
            ad_n = get_ad_user_info()
            entry_name.delete(0, tk.END)
            entry_name.insert(0, ad_n)
            
        btn_ad = tk.Button(name_hdr, text="↺ Detectar de AD", command=reload_from_ad, 
                           bg="#333333", fg="#00d2d3", bd=0, font=("Segoe UI", 8), cursor="hand2")
        btn_ad.pack(side="right")
        
        entry_name = tk.Entry(cfg_win, font=("Segoe UI", 10), bg="#1e1e1e", fg="#ffffff", insertbackground="white")
        entry_name.pack(fill="x", padx=20, pady=(2, 12))
        entry_name.insert(0, self.client_name)
        
        def save():
            if self.auto_ip_var.get():
                self.server_ip = "auto"
            else:
                self.server_ip = entry_ip.get().strip() or "auto"
                
            self.client_name = entry_name.get().strip() or socket.gethostname()
            self.save_config()
            
            # Forzar reconexión
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
            cfg_win.destroy()
            if self.server_ip == "auto":
                self.status_label.config(text="Buscando servidor en la red...", fg="#f39c12")
            else:
                self.status_label.config(text=f"Reconectando a {self.server_ip}...", fg="#888888")
            
        btn_save = tk.Button(cfg_win, text="Guardar y Conectar", command=save, 
                             bg="#0984e3", fg="white", font=("Segoe UI", 9, "bold"), 
                             relief="flat", cursor="hand2", pady=4)
        btn_save.pack(fill="x", padx=20, pady=(0, 10))

    def on_close(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = FloatingGadget()
    app.run()
