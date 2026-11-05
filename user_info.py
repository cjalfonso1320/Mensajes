import os
import subprocess
import socket

_cached_user_name = None

def get_ad_user_info():
    """
    Obtiene el primer nombre y primer apellido del usuario actual
    conectándose a Active Directory (AD).
    Si no está disponible, aplica fallbacks seguros (net user / cuenta Windows).
    """
    global _cached_user_name
    if _cached_user_name:
        return _cached_user_name
        
    username = os.environ.get("USERNAME", "")
    hostname = socket.gethostname()
    
    if not username:
        return f"Usuario ({hostname})"

    # Bandera para evitar que parpadee una consola en Windows al ser compilado con --noconsole
    no_window = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

    # 1. Intentar Active Directory vía ADSI Searcher (PowerShell)
    try:
        ps_script = f"""
        $u = '{username}'
        $searcher = [adsisearcher]"(sAMAccountName=$u)"
        $result = $searcher.FindOne()
        if ($result) {{
            $given = [string]$result.Properties['givenname'][0]
            $sn = [string]$result.Properties['sn'][0]
            $display = [string]$result.Properties['displayname'][0]
            Write-Output "$given;;;$sn;;;$display"
        }}
        """
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=no_window
        )
        output = proc.stdout.strip()
        if output and ";;;" in output:
            parts = output.split(";;;")
            given_name = parts[0].strip() if len(parts) > 0 else ""
            surname = parts[1].strip() if len(parts) > 1 else ""
            display_name = parts[2].strip() if len(parts) > 2 else ""

            first_name = given_name.split()[0] if given_name else ""
            first_surname = surname.split()[0] if surname else ""

            if first_name and first_surname:
                _cached_user_name = f"{first_name} {first_surname}"
                return _cached_user_name
            elif display_name:
                words = display_name.split()
                if len(words) >= 2:
                    _cached_user_name = f"{words[0]} {words[1]}"
                    return _cached_user_name
                _cached_user_name = display_name
                return _cached_user_name
    except Exception:
        pass

    # 2. Fallback: net user %USERNAME% /domain
    try:
        proc = subprocess.run(
            ["net", "user", username, "/domain"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=no_window
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if "Nombre completo" in line or "Full Name" in line:
                    full_name = line.split(maxsplit=2)[-1].strip()
                    if full_name:
                        words = full_name.split()
                        if len(words) >= 2:
                            _cached_user_name = f"{words[0]} {words[1]}"
                            return _cached_user_name
                        _cached_user_name = full_name
                        return _cached_user_name
    except Exception:
        pass

    # 3. Fallback: Formato de nombre de usuario de Windows
    clean_user = username.replace(".", " ").replace("_", " ").title()
    _cached_user_name = clean_user
    return _cached_user_name

if __name__ == "__main__":
    print("Nombre AD detectado:", get_ad_user_info())
