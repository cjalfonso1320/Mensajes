const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    downloadMediaMessage,
    normalizeMessageContent
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const qrcode = require('qrcode-terminal');
const net = require('net');
const path = require('path');
const fs = require('fs');

// Cargar configuración
const configPath = path.join(__dirname, 'config.json');
let config = {
    server_host: "127.0.0.1",
    server_port: 5050,
    allow_self_messages: true,
    authorized_numbers: [],
    commands: {
        urgent: ["!urgente", "!sos", "!critico"],
        warning: ["!alerta", "!importante", "!aviso"],
        info: ["!info", "!comunicado"]
    },
    reply_feedback: true
};

if (fs.existsSync(configPath)) {
    try {
        config = { ...config, ...JSON.parse(fs.readFileSync(configPath, 'utf-8')) };
    } catch (e) {
        console.error("Error leyendo config.json:", e);
    }
}

// ----------------- CLIENTE TCP HACIA SERVER.PY -----------------
class TcpBridge {
    constructor(host, port) {
        this.host = host;
        this.port = port;
        this.socket = null;
        this.connected = false;
        this.pendingCallbacks = new Map();
        this.currentStatus = "disconnected";
        this.currentPhone = "";
        this.connect();
    }

    connect() {
        this.socket = new net.Socket();
        
        this.socket.connect(this.port, this.host, () => {
            this.connected = true;
            console.log(`[TCP] Conectado al Servidor de Mensajería (${this.host}:${this.port})`);
            
            // Registrarse ante el servidor como WhatsApp Gateway
            const reg = {
                type: "register",
                role: "whatsapp",
                name: "WhatsApp Gateway"
            };
            this.socket.write(JSON.stringify(reg) + "\n");

            // Si WhatsApp ya está conectado o en otro estado, notificarlo al servidor
            if (this.currentStatus !== "disconnected") {
                this.sendStatus(this.currentStatus, this.currentPhone);
            }
        });

        let buffer = "";
        this.socket.on('data', (data) => {
            buffer += data.toString('utf-8');
            let lines = buffer.split("\n");
            buffer = lines.pop(); // Mantener fragmentos incompletos en el buffer

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const msg = JSON.parse(line.trim());
                    if (msg.type === "broadcast_ack") {
                        // Resolver el callback pendiente más antiguo
                        const keys = Array.from(this.pendingCallbacks.keys());
                        if (keys.length > 0) {
                            const cb = this.pendingCallbacks.get(keys[0]);
                            this.pendingCallbacks.delete(keys[0]);
                            if (cb) cb(null, msg);
                        }
                    }
                } catch (err) {
                    console.error("[TCP] Error parseando respuesta del servidor:", err);
                }
            }
        });

        this.socket.on('close', () => {
            if (this.connected) {
                console.log("[TCP] Conexión cerrada con el servidor. Reconectando en 3s...");
            }
            this.connected = false;
            setTimeout(() => this.connect(), 3000);
        });

        this.socket.on('error', (err) => {
            // Ignorar errores de conexión periódicos cuando el servidor de Python está apagado
            this.connected = false;
        });
    }

    sendStatus(status, phone = "") {
        this.currentStatus = status;
        this.currentPhone = phone;
        if (this.connected && this.socket) {
            try {
                const payload = {
                    type: "whatsapp_status",
                    status: status,
                    phone: phone
                };
                this.socket.write(JSON.stringify(payload) + "\n");
            } catch (err) {
                console.error("[TCP] Error enviando whatsapp_status:", err);
            }
        }
    }

    broadcast(title, content, priority, sender, imageB64, callback) {
        if (!this.connected) {
            return callback(new Error("El servidor de mensajería (server.py / admin.py) no está en línea"));
        }

        const now = new Date();
        const timestamp = now.toTimeString().split(' ')[0];

        const payload = {
            type: "broadcast",
            title: title,
            content: content,
            priority: priority,
            timestamp: timestamp,
            sender: sender,
            image: imageB64 || null
        };

        const id = Date.now().toString();
        this.pendingCallbacks.set(id, callback);

        // Limpiar callback si no hay respuesta en 5s
        setTimeout(() => {
            if (this.pendingCallbacks.has(id)) {
                const cb = this.pendingCallbacks.get(id);
                this.pendingCallbacks.delete(id);
                if (cb) cb(null, { delivered_to: "desconocido" });
            }
        }, 5000);

        this.socket.write(JSON.stringify(payload) + "\n");
    }
}

const tcpBridge = new TcpBridge(config.server_host, config.server_port);

// ----------------- CLIENTE WHATSAPP (BAILEYS) -----------------
async function startWhatsApp() {
    const authFolder = path.join(__dirname, 'auth_info');
    const { state, saveCreds } = await useMultiFileAuthState(authFolder);

    const sock = makeWASocket({
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log("\n=======================================================");
            console.log("📲 ESCANEA ESTE CÓDIGO QR CON TU WHATSAPP PARA VINCULAR:");
            console.log("   (WhatsApp > Ajustes / Menú > Dispositivos Vinculados)");
            console.log("=======================================================\n");
            qrcode.generate(qr, { small: true });
            tcpBridge.sendStatus("qr_required");
        }

        if (connection === 'close') {
            tcpBridge.sendStatus("disconnected");
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log(`[WHATSAPP] Conexión cerrada. Reconectar: ${shouldReconnect}`);
            if (shouldReconnect) {
                startWhatsApp();
            } else {
                console.log("[WHATSAPP] Sesión cerrada. Elimina la carpeta 'auth_info' y reinicia para volver a escanear.");
            }
        } else if (connection === 'open') {
            const userPhone = sock.user?.id ? sock.user.id.split(':')[0] : 'Admin';
            console.log("\n=======================================================");
            console.log(`✅ ¡WHATSAPP VINCULADO CON ÉXITO!`);
            console.log(`   Número conectado: +${userPhone}`);
            console.log(`   Esperando comandos: !aviso, !alerta, !urgente`);
            console.log("=======================================================\n");
            tcpBridge.sendStatus("connected", userPhone);
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        for (const m of messages) {
            if (!m.message) continue;

            // WhatsApp puede envolver el contenido (por ejemplo, mensajes efímeros).
            // Normalizarlo permite leer texto y captions de forma uniforme.
            const messageContent = normalizeMessageContent(m.message) || m.message;
            const text = messageContent.conversation ||
                         messageContent.extendedTextMessage?.text ||
                         messageContent.imageMessage?.caption || "";

            if (!text.trim()) {
                if (messageContent.imageMessage) {
                    console.log(`[WHATSAPP] Imagen recibida sin caption con comando (tipo ${type}).`);
                }
                continue;
            }

            const fromMe = m.key.fromMe;
            const remoteJid = m.key.remoteJid || "";
            const senderJid = m.key.participant || remoteJid;
            const senderNumber = senderJid.replace(/@.+/, '').replace(/\D/g, '');

            // Verificar si el remitente está autorizado
            const isAuthorized = (fromMe && config.allow_self_messages) || 
                                 (config.authorized_numbers.length === 0 && fromMe) ||
                                 config.authorized_numbers.includes(senderNumber);

            if (!isAuthorized) {
                console.log(`[WHATSAPP] Mensaje ignorado: remitente no autorizado (${senderNumber || 'desconocido'}).`);
                continue;
            }

            // Analizar si el mensaje comienza con algún comando
            const cleanText = text.trim();
            const lowerText = cleanText.toLowerCase();

            let priority = null;
            let title = "";
            let commandPrefix = "";

            // 1. Urgente
            for (const cmd of config.commands.urgent) {
                if (lowerText.startsWith(cmd.toLowerCase())) {
                    priority = "urgent";
                    title = "🚨 COMUNICADO URGENTE";
                    commandPrefix = cmd;
                    break;
                }
            }

            // 2. Advertencia / Importante
            if (!priority) {
                for (const cmd of config.commands.warning) {
                    if (lowerText.startsWith(cmd.toLowerCase())) {
                        priority = "warning";
                        title = "⚠️ AVISO IMPORTANTE";
                        commandPrefix = cmd;
                        break;
                    }
                }
            }

            // 3. Informativo
            if (!priority) {
                for (const cmd of config.commands.info) {
                    if (lowerText.startsWith(cmd.toLowerCase())) {
                        priority = "info";
                        title = "ℹ️ COMUNICADO GENERAL";
                        commandPrefix = cmd;
                        break;
                    }
                }
            }

            if (!priority) {
                console.log(`[WHATSAPP] Mensaje recibido sin comando reconocido (tipo ${type}).`);
                continue;
            }

            // Extraer el contenido del mensaje removiendo el prefijo
            const content = cleanText.substring(commandPrefix.length).trim();
            if (!content) {
                if (config.reply_feedback) {
                    await sock.sendMessage(remoteJid, { 
                        text: `⚠️ *Mensaje vacío*\nUso: \`${commandPrefix} Tu mensaje aquí\`` 
                    }, { quoted: m });
                }
                continue;
            }

            // --- Descargar imagen adjunta si existe ---
            let imageB64 = null;
            if (messageContent.imageMessage) {
                try {
                    console.log("[WHATSAPP] Descargando imagen adjunta...");
                    const buffer = await downloadMediaMessage(m, 'buffer', {});
                    imageB64 = 'data:image/jpeg;base64,' + buffer.toString('base64');
                    console.log(`[WHATSAPP] Imagen descargada (${Math.round(buffer.length / 1024)} KB)`);
                } catch (e) {
                    console.error("[WHATSAPP] Error al descargar imagen:", e.message);
                }
            }

            const senderLabel = fromMe ? "WhatsApp (Admin)" : `WhatsApp (+${senderNumber})`;
            const imgMark = imageB64 ? " 🖼️" : "";
            console.log(`\n[WHATSAPP -> GADGETS] Nuevo mensaje (${priority})${imgMark}: "${content}"`);

            // Reenviar a través del socket hacia server.py
            tcpBridge.broadcast(title, content, priority, senderLabel, imageB64, async (err, ack) => {
                if (!config.reply_feedback) return;

                if (err) {
                    await sock.sendMessage(remoteJid, { 
                        text: `❌ *Error al difundir comunicado:*\n${err.message}` 
                    }, { quoted: m });
                } else {
                    const count = ack ? ack.delivered_to : 0;
                    const prioText = priority === "urgent" ? "🚨 Urgente" : priority === "warning" ? "⚠️ Importante" : "ℹ️ Informativo";
                    const imgTxt = imageB64 ? "\n• *Imagen:* ✅ Enviada con el comunicado" : "";
                    const reply = `✅ *Comunicado emitido a pantallas*\n` +
                                  `• *Prioridad:* ${prioText}\n` +
                                  `• *Entregado a:* ${count} gadget(s) activos\n` +
                                  `• *Mensaje:* "${content}"${imgTxt}`;
                    await sock.sendMessage(remoteJid, { text: reply }, { quoted: m });
                }
            });
        }
    });
}

// Iniciar
startWhatsApp().catch(err => {
    console.error("[FATAL ERROR] Fallo al iniciar WhatsApp Bridge:", err);
});

