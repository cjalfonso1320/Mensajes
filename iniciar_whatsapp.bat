@echo off
title WhatsApp Bridge - Mensajes LAN
cd /d "%~dp0whatsapp_bridge"
echo ========================================================
echo    Iniciando Pasarela de WhatsApp para Gadgets
echo ========================================================
node index.js
pause

