"""
Aplicación de escritorio para abrir la interfaz de Danny's Glassworks.
Lee la dirección IP guardada por Host.py y abre el navegador.
"""
import os
import sys
import time
import webbrowser
from pathlib import Path

# Ruta a la carpeta del proyecto (padre de APLICACION y HOST)
BASE_DIR = Path(__file__).resolve().parent.parent
ADDRESS_FILE = BASE_DIR / "direccion_ip.txt"

def main():
    # Esperar a que el archivo de dirección exista (por si el servidor se inicia justo después)
    for _ in range(30):
        if ADDRESS_FILE.exists():
            break
        time.sleep(1)
    else:
        print("No se encontró el archivo de dirección IP. Asegúrate de haber ejecutado Host.py.")
        sys.exit(1)

    url = ADDRESS_FILE.read_text(encoding="utf-8").strip()
    if not url:
        print("La dirección IP está vacía.")
        sys.exit(1)

    print(f"Abriendo {url} en el navegador...")
    webbrowser.open(url)

if __name__ == "__main__":
    main()