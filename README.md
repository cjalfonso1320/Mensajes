# 💬 Sistema de Mensajería LAN con Gadget Flotante

Sistema de comunicación en tiempo real para red local (LAN) compuesto por:
1. **Panel Administrador (`admin.py`)**: Interfaz gráfica en Tkinter para redactar y enviar comunicados (Informativos, Importantes o Urgentes) y monitorear qué gadgets están conectados en tiempo real. Incluye servidor embebido automático.
2. **Gadget Flotante (`app.py`)**: Widget de escritorio discreto, transparente, sin bordes y siempre visible (`Always on top`) que muestra la hora y, al recibir un mensaje del administrador, se expande con una alerta visual y sonora.
3. **Módulo de Identificación AD (`user_info.py`)**: Detecta automáticamente el primer nombre y primer apellido del usuario activo consultando Active Directory (ADSI / LDAP).
4. **Servidor Central (`server.py`)**: Motor de sockets TCP de alta velocidad sin dependencias externas.

### Imágenes en los comunicados
- En el administrador, usa **📎 Adjuntar Imagen** para seleccionar JPG, PNG u otro formato compatible; verás una miniatura y puedes quitarla con **✕**.
- Desde WhatsApp, adjunta una foto y escribe el comando en el caption, por ejemplo: `!urgente Falla detectada en el rack 2`.
- El servidor corrige la orientación de fotos de celular y las convierte a JPEG de hasta 600 × 600 px antes de distribuirlas.
- Los gadgets muestran una vista previa y permiten abrir el visor desde la miniatura o el botón **🖼️ Ver imagen**.
- Pillow es necesario para adjuntar y visualizar imágenes. Está incluido en las especificaciones de PyInstaller; para ejecutar desde Python instala `pip install pillow`.

---

## 📦 Ejecutables Portables (No requieren Python instalado)

En la carpeta `dist/` se han generado los archivos ejecutables listos para distribuir:
- **`dist/AdminMensajes.exe`**: Ejecutable para la máquina del administrador.
- **`dist/GadgetMensajes.exe`**: Ejecutable portable para los clientes / estaciones de trabajo. Solo copia este archivo a las máquinas de los usuarios y ejecútalo directamente.

---

## 🚀 Cómo Usarlo

### 1. En la Máquina del Administrador
Ejecuta el panel del administrador (`dist\AdminMensajes.exe` o `python admin.py`):
- Al abrirse, iniciará automáticamente el servidor en el puerto `5050` y te mostrará tu **IP de la Red Local** (por ejemplo: `10.20.10.36`).
- El Treeview de gadgets conectados mostrará: **Usuario (AD)** (primer nombre y primer apellido), **Equipo** (hostname) y **Dirección IP**.
- Haz clic en **"📋 Copiar IP"** para compartirla con los usuarios que instalarán el gadget.

### 2. En las Máquinas de los Usuarios (Clientes)
Ejecuta el gadget en cada equipo (`dist\GadgetMensajes.exe` o `python app.py`):
- **Cero Configuración:** El gadget detecta automáticamente el Administrador mediante una baliza UDP en la red local y se conecta solo al instante.
- El gadget detecta automáticamente el **Primer Nombre y Primer Apellido** del usuario conectado en el dominio de Active Directory (ej. `Cristhian Alfonso`).
- Si en algún momento se desea forzar una IP fija o cambiar el nombre, se puede hacer desde el icono **⚙ (Ajustes)**.
- El punto indicador cambiará a **🟢 Verde**, confirmando la conexión activa.

### 3. Pasarela de WhatsApp Móvil (Integrada en el Administrador)
Permite enviar comunicados a todos los gadgets directamente desde tu celular sin tener ninguna ventana de comandos abierta:
1. **Automático:** Al abrir `dist\AdminMensajes.exe` (o `python admin.py`), la pasarela de WhatsApp se inicia **automáticamente en segundo plano** de forma invisible.
2. En la barra superior del panel verás el estado en vivo:
   - `📱 WhatsApp: 🟢 Conectado y escuchando (!aviso, !alerta, !urgente)`
3. **Enviar comunicados desde WhatsApp:** Escribe desde tu celular (incluso en tu chat personal o "Mensajes a ti mismo"):
   - `!aviso [texto]` ➔ Alerta Informativa (Azul).
   - `!alerta [texto]` ➔ Alerta Importante (Amarillo).
   - `!urgente [texto]` ➔ Alerta Urgente (Rojo con sonido fuerte).
4. El bot te responderá a WhatsApp confirmando cuántos gadgets recibieron el mensaje, y en el panel del Administrador quedará registrado automáticamente en el historial.
5. **Cierre limpio:** Al cerrar el panel del Administrador, el proceso de WhatsApp se cierra automáticamente. *(Si alguna vez necesitas pausarlo sin cerrar el panel, cuentas con el botón "⏸ Pausar WhatsApp")*.

---

## 🎨 Características del Gadget
- **Modo Standby / Reloj**: Ventana compacta (240x95 px) flotante que muestra la hora y el estado de la conexión.
- **Notificación Emergente**: Al recibir un mensaje, el gadget se expande automáticamente (340x200 px), emite un sonido del sistema (`winsound`) y resalta con colores según la prioridad:
  - ℹ️ **Informativo**: Acento Cyan / Azul.
  - ⚠️ **Importante**: Acento Ámbar / Amarillo.
  - 🚨 **Urgente**: Acento Rojo.
- **Botón "✓ Entendido"**: Cierra la notificación y regresa el gadget al modo reloj compacto.
- **Botón "✉"**: Permite volver a consultar el último mensaje recibido en cualquier momento.
- **Movilidad**: Arrastra el gadget con el clic izquierdo a cualquier parte de la pantalla.

---

## 🛡️ Nota sobre el Firewall de Windows (Red Local)
Al iniciar `admin.py` por primera vez, Windows Firewall puede mostrar una ventana emergente solicitando permisos de red:
- Asegúrate de marcar la casilla **"Redes privadas"** y pulsar **"Permitir acceso"** para que los demás equipos puedan conectar sus gadgets al puerto 5050.

