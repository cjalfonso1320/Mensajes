"""
image_utils.py — Utilidades de imagen para el Sistema de Mensajería LAN.
Convierte imágenes a/desde Base64 con compresión JPEG para transporte eficiente.
"""

import base64
import io

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

MAX_WIDTH = 600       # Ancho máximo al codificar para envío
JPEG_QUALITY = 70     # Calidad JPEG (balance tamaño/calidad)
THUMB_WIDTH = 280     # Ancho del thumbnail en el gadget
MAX_HEIGHT = 600      # También limitar fotos verticales de celular


def encode_image_file(path: str) -> str:
    """
    Abre un archivo de imagen desde disco, lo limita a MAX_WIDTH x MAX_HEIGHT,
    lo convierte a JPEG y retorna un data URI Base64.
    
    Returns:
        str: "data:image/jpeg;base64,..." listo para incluir en JSON.
    Raises:
        RuntimeError: Si PIL no está disponible o el archivo no es imagen válida.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow no está instalado. Ejecuta: pip install pillow")
    
    img = Image.open(path)
    return _compress_and_encode(img)


def encode_image_bytes(data: bytes) -> str:
    """
    Recibe bytes crudos de imagen (buffer de WhatsApp/cualquier fuente),
    los redimensiona y retorna data URI Base64.
    
    Returns:
        str: "data:image/jpeg;base64,..."
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow no está instalado.")
    
    img = Image.open(io.BytesIO(data))
    return _compress_and_encode(img)


def _compress_and_encode(img: "Image") -> str:
    """Redimensiona, comprime a JPEG y codifica en Base64."""
    # Respetar la orientación indicada por cámaras y teléfonos.
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    # Convertir a RGB si es RGBA/P (PNG con transparencia, GIF, etc.)
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    
    # Redimensionar si es más ancho que MAX_WIDTH
    if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
        ratio = min(MAX_WIDTH / img.width, MAX_HEIGHT / img.height)
        new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
        img = img.resize(new_size, Image.LANCZOS)
    
    # Comprimir a JPEG en memoria
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    buf.seek(0)
    
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def decode_image_b64(b64str: str) -> "Image":
    """
    Decodifica un data URI Base64 y retorna un objeto PIL.Image.
    
    Args:
        b64str: "data:image/jpeg;base64,..." o solo la parte Base64.
    Returns:
        PIL.Image.Image
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow no está instalado.")
    
    if b64str.startswith("data:"):
        # Formato: "data:image/jpeg;base64,XXXXX"
        b64str = b64str.split(",", 1)[1]
    
    data = base64.b64decode(b64str)
    return Image.open(io.BytesIO(data))


def make_thumbnail(b64str: str, max_width: int = THUMB_WIDTH) -> "Image":
    """
    Crea una versión thumbnail de la imagen para mostrar en el gadget.
    
    Returns:
        PIL.Image.Image redimensionada
    """
    img = decode_image_b64(b64str)
    if img.mode != "RGB":
        img = img.convert("RGB")
    
    if img.width > max_width:
        ratio = max_width / img.width
        new_h = int(img.height * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)
    
    return img

