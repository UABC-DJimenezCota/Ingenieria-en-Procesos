"""
Aplicación de escritorio para Danny's Glassworks.
Ejecuta el servidor Host.py en segundo plano, espera unos segundos y abre la interfaz en el navegador.
"""
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HOST_FILE = BASE_DIR / "HOST" / "Host.py"
ADDRESS_FILE = BASE_DIR / "direccion_ip.txt"

def main():
    # Iniciar Host.py en un proceso separado
    print("Iniciando el servidor Host.py...")
    if not HOST_FILE.exists():
        print(f"No se encontró el archivo del servidor en: {HOST_FILE}")
        sys.exit(1)

    # Lanzar el servidor usando el intérprete de python actual
    servidor_proceso = subprocess.Popen([sys.executable, str(HOST_FILE)])

    # Esperar 3 segundos para que el servidor arranque y genere la IP
    print("Esperando a que el servidor inicie...")
    time.sleep(3)

    # Intentar leer la IP desde el archivo generado por Host.py
    url = ""
    for _ in range(10):
        if ADDRESS_FILE.exists():
            contenido = ADDRESS_FILE.read_text(encoding="utf-8").strip()
            if contenido:
                url = contenido.splitlines()[0].strip()
                break
        time.sleep(1)

    # Si no se leyó del archivo, usar por defecto http://127.0.0.1:8000
    if not url:
        url = "http://127.0.0.1:8000"
    print(f"Abriendo {url} en el navegador...")
    webbrowser.open(url)

    try:
        # Mantener el script corriendo mientras el servidor esté activo
        servidor_proceso.wait()
    except KeyboardInterrupt:
        servidor_proceso.terminate()

if __name__ == "__main__":
    main()