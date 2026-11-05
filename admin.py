import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import json
import time
import socket
import os
import sys
import subprocess
from server import MessageServer, get_local_ip
from image_utils import encode_image_file, PIL_AVAILABLE

try:
    from PIL import ImageTk, Image as PILImage
except ImportError:
    ImageTk = None
    PILImage = None

def get_project_base_dir():
    """Obtiene la ruta base del proyecto, compatible tanto con script Python como con ejecutable PyInstaller."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        # Si el ejecutable está en dist/, buscar en el directorio padre
        parent_dir = os.path.abspath(os.path.join(exe_dir, ".."))
        if os.path.exists(os.path.join(parent_dir, "whatsapp_bridge")):
            return parent_dir
        return exe_dir
    return os.path.abspath(os.path.dirname(__file__))

class AdminApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Panel Administrador - Sistema de Mensajería LAN")
        self.root.geometry("820x620")
        self.root.minsize(700, 500)
        self.root.configure(bg="#1e1e1e")
        
        self.local_ip = get_local_ip()
        self.port = 5050
        
        # Iniciar servidor embebido por defecto
        self.server = None
        self.connected_gadgets = []
        
        # Proceso en segundo plano de WhatsApp
        self.wa_process = None
        self.running = True
        
        # Imagen adjunta (Base64)
        self.attached_image_b64 = None
        self.attached_image_path = None
        self._admin_thumb_ref = None   # Referencia para evitar GC de PhotoImage
        
        self.setup_styles()
        self.create_widgets()
        
        # Iniciar el servidor local
        self.start_embedded_server()
        
        # Iniciar la pasarela de WhatsApp en segundo plano
        self.start_whatsapp_bridge()
        
        # Manejar cierre de la ventana
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Configurar colores para ttk
        self.style.configure(".", background="#1e1e1e", foreground="#ffffff")
        self.style.configure("TLabel", background="#1e1e1e", foreground="#ffffff", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#00d2d3")
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 10), foreground="#888888")
        
        self.style.configure("TFrame", background="#1e1e1e")
        self.style.configure("Card.TFrame", background="#252526", relief="solid", borderwidth=1)
        
        self.style.configure("Treeview", 
                             background="#252526", 
                             foreground="#ffffff", 
                             fieldbackground="#252526", 
                             font=("Segoe UI", 9),
                             rowheight=24)
        self.style.configure("Treeview.Heading", 
                             background="#333333", 
                             foreground="#00d2d3", 
                             font=("Segoe UI", 9, "bold"))
        self.style.map("Treeview", background=[("selected", "#0984e3")])

    def create_widgets(self):
        # 1. ENCABEZADO Y ESTADO DE RED
        header_frame = tk.Frame(self.root, bg="#252526", bd=1, relief="solid")
        header_frame.pack(fill="x", padx=15, pady=10)
        
        title_label = tk.Label(header_frame, text="📢 Panel Administrador de Mensajes", 
                               font=("Segoe UI", 14, "bold"), fg="#00d2d3", bg="#252526")
        title_label.pack(anchor="w", padx=15, pady=(10, 2))
        
        # Info de IP local
        ip_frame = tk.Frame(header_frame, bg="#252526")
        ip_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        self.lbl_server_status = tk.Label(ip_frame, text="🟢 Servidor Activo", 
                                          font=("Segoe UI", 10, "bold"), fg="#2ecc71", bg="#252526")
        self.lbl_server_status.pack(side="left")
        
        ip_info = f" | IP de la Red Local: {self.local_ip}:{self.port} (Los gadgets deben conectarse a esta IP)"
        self.lbl_ip = tk.Label(ip_frame, text=ip_info, font=("Segoe UI", 10), fg="#bdc3c7", bg="#252526")
        self.lbl_ip.pack(side="left", padx=5)
        
        btn_copy_ip = tk.Button(ip_frame, text="📋 Copiar IP", command=self.copy_ip,
                                bg="#333333", fg="#ffffff", font=("Segoe UI", 9), 
                                relief="flat", activebackground="#444444", cursor="hand2")
        btn_copy_ip.pack(side="right")

        # Barra de estado y control de WhatsApp
        wa_frame = tk.Frame(header_frame, bg="#252526")
        wa_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        self.lbl_wa_status = tk.Label(wa_frame, text="📱 WhatsApp Móvil: Iniciando pasarela...", 
                                      font=("Segoe UI", 9, "bold"), fg="#f39c12", bg="#252526")
        self.lbl_wa_status.pack(side="left")
        
        self.btn_wa_qr = tk.Button(wa_frame, text="📲 Vincular con QR", command=self.open_wa_qr_terminal,
                                   bg="#333333", fg="#00d2d3", font=("Segoe UI", 8), 
                                   relief="flat", activebackground="#444444", cursor="hand2")
        self.btn_wa_qr.pack(side="right", padx=(5, 0))
        
        self.btn_wa_toggle = tk.Button(wa_frame, text="⏸ Pausar WhatsApp", command=self.toggle_whatsapp_bridge,
                                      bg="#333333", fg="#ffffff", font=("Segoe UI", 8), 
                                      relief="flat", activebackground="#444444", cursor="hand2")
        self.btn_wa_toggle.pack(side="right")
        
        # 2. CONTENIDO PRINCIPAL (Dividido en dos columnas: izquierda Formulario, derecha Clientes e Historial)
        main_content = tk.Frame(self.root, bg="#1e1e1e")
        main_content.pack(fill="both", expand=True, padx=15, pady=5)
        
        # Columna Izquierda: Redactor de Mensajes
        left_panel = tk.Frame(main_content, bg="#252526", bd=1, relief="solid", padx=15, pady=15)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        tk.Label(left_panel, text="✉️ Redactar Nuevo Comunicado", font=("Segoe UI", 12, "bold"), 
                 fg="#ffffff", bg="#252526").pack(anchor="w", pady=(0, 10))
        
        # Campo Título
        tk.Label(left_panel, text="Título / Asunto:", font=("Segoe UI", 10, "bold"), 
                 fg="#00d2d3", bg="#252526").pack(anchor="w", pady=(5, 2))
        self.entry_title = tk.Entry(left_panel, font=("Segoe UI", 11), bg="#1e1e1e", fg="#ffffff", 
                                    insertbackground="#ffffff", relief="solid", bd=1)
        self.entry_title.pack(fill="x", pady=(0, 10), ipady=3)
        self.entry_title.insert(0, "")
        
        # Nivel de Prioridad
        tk.Label(left_panel, text="Nivel de Prioridad:", font=("Segoe UI", 10, "bold"), 
                 fg="#00d2d3", bg="#252526").pack(anchor="w", pady=(5, 2))
        
        priority_frame = tk.Frame(left_panel, bg="#252526")
        priority_frame.pack(fill="x", pady=(0, 10))
        
        self.priority_var = tk.StringVar(value="info")
        
        rb1 = tk.Radiobutton(priority_frame, text="ℹ️ Informativo", value="info", 
                             variable=self.priority_var, bg="#252526", fg="#00d2d3", 
                             selectcolor="#1e1e1e", activebackground="#252526", activeforeground="#00d2d3",
                             font=("Segoe UI", 10))
        rb1.pack(side="left", padx=(0, 10))
        
        rb2 = tk.Radiobutton(priority_frame, text="⚠️ Importante", value="warning", 
                             variable=self.priority_var, bg="#252526", fg="#f39c12", 
                             selectcolor="#1e1e1e", activebackground="#252526", activeforeground="#f39c12",
                             font=("Segoe UI", 10))
        rb2.pack(side="left", padx=10)
        
        rb3 = tk.Radiobutton(priority_frame, text="🚨 Urgente", value="urgent", 
                             variable=self.priority_var, bg="#252526", fg="#e74c3c", 
                             selectcolor="#1e1e1e", activebackground="#252526", activeforeground="#e74c3c",
                             font=("Segoe UI", 10, "bold"))
        rb3.pack(side="left", padx=10)
        
        # Contenido del Mensaje
        tk.Label(left_panel, text="Mensaje para los Gadgets:", font=("Segoe UI", 10, "bold"), 
                 fg="#00d2d3", bg="#252526").pack(anchor="w", pady=(5, 2))
        
        self.text_content = scrolledtext.ScrolledText(left_panel, font=("Segoe UI", 10), 
                                                      bg="#1e1e1e", fg="#ffffff", insertbackground="#ffffff",
                                                      relief="solid", bd=1, height=6)
        self.text_content.pack(fill="both", expand=True, pady=(0, 10))
        self.text_content.insert("1.0", "")
        
        # --- Fila de imagen adjunta ---
        img_row = tk.Frame(left_panel, bg="#252526")
        img_row.pack(fill="x", pady=(0, 10))
        
        self.btn_attach = tk.Button(img_row, text="📎 Adjuntar Imagen", command=self.attach_image,
                                    bg="#333333", fg="#00d2d3", font=("Segoe UI", 9),
                                    relief="flat", activebackground="#444444", cursor="hand2", padx=6)
        self.btn_attach.pack(side="left")
        
        self.lbl_img_name = tk.Label(img_row, text="Sin imagen", font=("Segoe UI", 8),
                                     fg="#666666", bg="#252526", anchor="w")
        self.lbl_img_name.pack(side="left", padx=8, fill="x", expand=True)
        
        self.btn_clear_img = tk.Button(img_row, text="✕", command=self.clear_image,
                                       bg="#333333", fg="#e74c3c", font=("Segoe UI", 9, "bold"),
                                       relief="flat", activebackground="#444444", cursor="hand2",
                                       width=2)
        self.btn_clear_img.pack(side="right")
        self.btn_clear_img.pack_forget()  # Oculto hasta que haya imagen
        
        # Thumbnail preview en el panel admin
        self.lbl_img_preview = tk.Label(left_panel, bg="#252526", cursor="hand2")
        # (se muestra sólo cuando hay imagen adjunta)
        
        # Botón Enviar
        self.btn_send = tk.Button(left_panel, text="📢 Enviar Comunicado a Todos los Gadgets", 
                                  command=self.send_broadcast, bg="#0984e3", fg="#ffffff", 
                                  font=("Segoe UI", 11, "bold"), relief="flat", 
                                  activebackground="#74b9ff", cursor="hand2", pady=8)
        self.btn_send.pack(fill="x")
        
        # Columna Derecha: Clientes Conectados e Historial
        right_panel = tk.Frame(main_content, bg="#252526", bd=1, relief="solid", padx=15, pady=15)
        right_panel.pack(side="right", fill="both", expand=True)
        
        # Lista de gadgets
        self.lbl_clients_count = tk.Label(right_panel, text="👥 Gadgets Conectados: 0", 
                                          font=("Segoe UI", 11, "bold"), fg="#ffffff", bg="#252526")
        self.lbl_clients_count.pack(anchor="w", pady=(0, 5))
        
        self.tree_clients = ttk.Treeview(right_panel, columns=("Usuario", "Equipo", "IP"), show="headings", height=5)
        self.tree_clients.heading("Usuario", text="Usuario (AD)")
        self.tree_clients.heading("Equipo", text="Equipo")
        self.tree_clients.heading("IP", text="Dirección IP")
        self.tree_clients.column("Usuario", width=140)
        self.tree_clients.column("Equipo", width=90)
        self.tree_clients.column("IP", width=95)
        self.tree_clients.pack(fill="x", pady=(0, 15))
        
        # Historial de Envíos
        tk.Label(right_panel, text="📜 Historial de Mensajes Enviados", font=("Segoe UI", 11, "bold"), 
                 fg="#ffffff", bg="#252526").pack(anchor="w", pady=(5, 5))
        
        self.tree_history = ttk.Treeview(right_panel, columns=("Hora", "Prioridad", "Título", "Entregados"), show="headings")
        self.tree_history.heading("Hora", text="Hora")
        self.tree_history.heading("Prioridad", text="Prioridad")
        self.tree_history.heading("Título", text="Título")
        self.tree_history.heading("Entregados", text="Enviado a")
        
        self.tree_history.column("Hora", width=65, anchor="center")
        self.tree_history.column("Prioridad", width=80, anchor="center")
        self.tree_history.column("Título", width=140)
        self.tree_history.column("Entregados", width=70, anchor="center")
        self.tree_history.pack(fill="both", expand=True)

    def start_embedded_server(self):
        """Inicia el servidor local automáticamente."""
        try:
            self.server = MessageServer(
                host="0.0.0.0", 
                port=self.port,
                on_clients_change=self.on_clients_change_from_server,
                on_message_received=self.on_message_broadcasted,
                on_whatsapp_status_change=self.on_whatsapp_status_from_server
            )
            self.server.start()
        except Exception as e:
            messagebox.showerror("Error al iniciar servidor", f"No se pudo iniciar el servidor en el puerto {self.port}:\n{e}")

    def copy_ip(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.local_ip)
        messagebox.showinfo("Copiado", f"IP {self.local_ip} copiada al portapapeles.\nPásala a los usuarios para sus gadgets.")

    def safe_after(self, delay, callback, *args):
        """Ejecuta una función en el hilo principal de Tkinter de forma segura."""
        if getattr(self, "running", True):
            try:
                self.root.after(delay, callback, *args)
            except Exception:
                pass

    def on_clients_change_from_server(self, gadgets):
        """Callback del servidor cuando un gadget se conecta o desconecta."""
        self.safe_after(0, self._update_gadgets_ui, gadgets)

    def _update_gadgets_ui(self, gadgets):
        self.connected_gadgets = gadgets
        self.lbl_clients_count.config(text=f"👥 Gadgets Conectados: {len(gadgets)}")
        
        # Limpiar y repoblar treeview
        for item in self.tree_clients.get_children():
            self.tree_clients.delete(item)
            
        for g in gadgets:
            self.tree_clients.insert("", "end", values=(
                g["name"],
                g.get("hostname", "-"),
                f"{g['ip']}:{g['port']}"
            ))

    def send_broadcast(self):
        title = self.entry_title.get().strip()
        content = self.text_content.get("1.0", tk.END).strip()
        priority = self.priority_var.get()
        
        if not title:
            messagebox.showwarning("Atención", "Por favor ingresa un título para el mensaje.")
            return
            
        if not content:
            messagebox.showwarning("Atención", "El mensaje no puede estar vacío.")
            return
            
        timestamp = time.strftime("%H:%M:%S")
        
        payload = {
            "type": "new_message",
            "title": title,
            "content": content,
            "priority": priority,
            "timestamp": timestamp,
            "sender": "Administrador",
            "image": self.attached_image_b64   # None si no hay imagen
        }
        
        count = self.server.broadcast_to_gadgets(payload)
        
        # Agregar al historial (con indicador si tiene imagen)
        prio_names = {"info": "ℹ️ Info", "warning": "⚠️ Aviso", "urgent": "🚨 Urgente"}
        prio_display = prio_names.get(priority, priority)
        hist_title = f"🖼️ {title}" if self.attached_image_b64 else title
        
        self.tree_history.insert("", 0, values=(timestamp, prio_display, hist_title, f"{count} gadgets"))
        
        # Feedback visual en el botón
        self.btn_send.config(text="✓ ¡Comunicado Enviado con Éxito!", bg="#2ecc71")
        self.root.after(2000, lambda: self.btn_send.config(
            text="📢 Enviar Comunicado a Todos los Gadgets", bg="#0984e3"))

    def attach_image(self):
        """Abre diálogo para seleccionar imagen, la comprime y guarda como Base64."""
        if not PIL_AVAILABLE:
            messagebox.showwarning(
                "Pillow no disponible",
                "No se puede adjuntar imágenes porque la librería Pillow no está instalada.\n"
                "Ejecuta: pip install pillow"
            )
            return
        
        path = filedialog.askopenfilename(
            title="Seleccionar Imagen",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.bmp *.gif *.webp"), ("Todos los archivos", "*.*")]
        )
        if not path:
            return
        
        try:
            self.attached_image_b64 = encode_image_file(path)
            self.attached_image_path = path
            fname = os.path.basename(path)
            
            # Mostrar nombre y botón limpiar
            self.lbl_img_name.config(text=fname, fg="#00d2d3")
            self.btn_clear_img.pack(side="right")
            
            # Miniatura preview (máx 160x80)
            if ImageTk and PILImage:
                img = PILImage.open(path)
                img.thumbnail((160, 80), PILImage.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._admin_thumb_ref = photo
                self.lbl_img_preview.config(image=photo, bg="#252526")
                self.lbl_img_preview.pack(fill="x", pady=(0, 8))
        except Exception as e:
            messagebox.showerror("Error al cargar imagen", str(e))
            self.attached_image_b64 = None

    def clear_image(self):
        """Limpia la imagen adjunta."""
        self.attached_image_b64 = None
        self.attached_image_path = None
        self._admin_thumb_ref = None
        self.lbl_img_name.config(text="Sin imagen", fg="#666666")
        self.lbl_img_preview.config(image="")
        self.lbl_img_preview.pack_forget()
        self.btn_clear_img.pack_forget()

    def on_whatsapp_status_from_server(self, status, phone=""):
        """Recibe directamente por socket el estado de conexión de WhatsApp desde whatsapp_bridge."""
        self.safe_after(0, self._update_whatsapp_status_ui, status, phone)

    def _update_whatsapp_status_ui(self, status, phone=""):
        if status == "connected":
            phone_txt = f" (+{phone})" if phone else ""
            self.lbl_wa_status.config(
                text=f"📱 WhatsApp{phone_txt}: 🟢 Conectado y escuchando (!aviso, !alerta, !urgente)",
                fg="#2ecc71"
            )
            self.btn_wa_toggle.config(text="⏸ Pausar WhatsApp", state="normal")
            self.btn_wa_qr.config(text="✓ Vinculado")
        elif status == "qr_required":
            self.lbl_wa_status.config(
                text="📱 WhatsApp: ⚠️ Requiere escanear código QR",
                fg="#f39c12"
            )
            self.btn_wa_qr.config(text="📲 Vincular con QR", fg="#00d2d3")
        else:
            self.lbl_wa_status.config(
                text="📱 WhatsApp: ⚪ Desconectado / Reconectando...",
                fg="#888888"
            )
            self.btn_wa_toggle.config(text="▶ Iniciar WhatsApp", state="normal")

    # ----------------- GESTIÓN DE PASARELA WHATSAPP -----------------
    def start_whatsapp_bridge(self):
        """Inicia el proceso de Node.js de WhatsApp en segundo plano de forma invisible."""
        base_dir = get_project_base_dir()
        bridge_dir = os.path.join(base_dir, "whatsapp_bridge")
        index_js = os.path.join(bridge_dir, "index.js")
        
        if not os.path.exists(index_js):
            self.lbl_wa_status.config(text="📱 WhatsApp: Carpeta whatsapp_bridge no encontrada", fg="#888888")
            self.btn_wa_toggle.config(state="disabled")
            self.btn_wa_qr.config(state="disabled")
            return

        # Detener cualquier proceso anterior que hayamos iniciado
        self.stop_whatsapp_bridge()

        try:
            no_window = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
            self.wa_process = subprocess.Popen(
                ["node", "index.js"],
                cwd=bridge_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=no_window,
                bufsize=1
            )
            
            self.lbl_wa_status.config(text="📱 WhatsApp: Conectando...", fg="#f39c12")
            self.btn_wa_toggle.config(text="⏸ Pausar WhatsApp", state="normal")
            
            # Monitorear la salida de Node.js en un hilo secundario
            monitor_thread = threading.Thread(target=self._monitor_wa_output, daemon=True)
            monitor_thread.start()
        except Exception as e:
            self.lbl_wa_status.config(text=f"📱 WhatsApp: Error al iniciar ({e})", fg="#e74c3c")

    def _monitor_wa_output(self):
        """Lee la salida de Node.js para actualizar dinámicamente el estado en la interfaz."""
        proc = self.wa_process
        if not proc or not proc.stdout:
            return
            
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                if "WHATSAPP VINCULADO CON ÉXITO" in line or "Conectado al Servidor de Mensajería" in line:
                    self.root.after(0, lambda: self.lbl_wa_status.config(
                        text="📱 WhatsApp: 🟢 Conectado y escuchando (!aviso, !alerta, !urgente)", 
                        fg="#2ecc71"
                    ))
                elif "ESCANEA ESTE CÓDIGO QR" in line:
                    self.root.after(0, lambda: self.lbl_wa_status.config(
                        text="📱 WhatsApp: ⚠️ Requiere escanear código QR", 
                        fg="#f39c12"
                    ))
                elif "Conexión cerrada" in line:
                    self.root.after(0, lambda: self.lbl_wa_status.config(
                        text="📱 WhatsApp: Reconectando...", 
                        fg="#f39c12"
                    ))
        except Exception:
            pass

    def stop_whatsapp_bridge(self):
        """Detiene el proceso de WhatsApp en segundo plano limpiamente."""
        if self.wa_process:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.wa_process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                try:
                    self.wa_process.kill()
                except Exception:
                    pass
            self.wa_process = None
            
        self.lbl_wa_status.config(text="📱 WhatsApp: ⚪ Pausado / Desconectado", fg="#888888")
        self.btn_wa_toggle.config(text="▶ Iniciar WhatsApp")

    def toggle_whatsapp_bridge(self):
        if self.wa_process:
            self.stop_whatsapp_bridge()
        else:
            self.start_whatsapp_bridge()

    def open_wa_qr_terminal(self):
        """Abre la ventana interactiva para volver a escanear el QR si fuese necesario."""
        self.stop_whatsapp_bridge()
        base_dir = get_project_base_dir()
        bat_path = os.path.join(base_dir, "iniciar_whatsapp.bat")
        
        if os.path.exists(bat_path):
            subprocess.Popen(["cmd.exe", "/c", "start", bat_path])
            messagebox.showinfo(
                "Vincular WhatsApp", 
                "Se ha abierto una ventana de consola con el código QR.\n\n"
                "Una vez escaneado con tu celular, cierra esa consola y pulsa '▶ Iniciar WhatsApp' aquí en el panel."
            )
        else:
            messagebox.showwarning("Atención", f"No se encontró el archivo: {bat_path}")

    def on_message_broadcasted(self, payload, count):
        """Callback cuando cualquier fuente externa (como WhatsApp) difunde un comunicado."""
        timestamp = payload.get("timestamp", time.strftime("%H:%M:%S"))
        priority = payload.get("priority", "info")
        title = payload.get("title", "Comunicado")
        sender = payload.get("sender", "Admin")
        
        prio_names = {"info": "ℹ️ Info", "warning": "⚠️ Aviso", "urgent": "🚨 Urgente"}
        prio_display = prio_names.get(priority, priority)
        
        display_title = f"[{sender}] {title}" if "WhatsApp" in sender else title
        self.safe_after(0, lambda: self.tree_history.insert("", 0, values=(timestamp, prio_display, display_title, f"{count} gadgets")))

    def on_close(self):
        self.running = False
        self.stop_whatsapp_bridge()
        if self.server:
            self.server.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = AdminApp(root)
    root.mainloop()

