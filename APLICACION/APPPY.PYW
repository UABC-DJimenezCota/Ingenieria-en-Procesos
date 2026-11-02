"""
Aplicación de escritorio para Danny's Glassworks.
Ejecuta el servidor Host.py en segundo plano, espera la IP y abre la interfaz en una ventana de pywebview.
"""
import subprocess
import sys
import time
from pathlib import Path

try:
    import webview
except ImportError:
    import subprocess
    print("Instalando la librería pywebview...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview"])
    import webview

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

    # Esperar a que el servidor arranque y genere la IP
    print("Esperando a que el servidor inicie...")
    url = ""
    for _ in range(15):
        if ADDRESS_FILE.exists():
            contenido = ADDRESS_FILE.read_text(encoding="utf-8").strip()
            if contenido:
                url = contenido.splitlines()[0].strip()
                break
        time.sleep(1)

    # Si no se leyó del archivo, usar por defecto http://127.0.0.1:8000
    if not url:
        url = "http://127.0.0.1:8000"

    print(f"Abriendo ventana de aplicación en {url}...")

    try:
        # Crear ventana con pywebview
        window = webview.create_window("Danny's Glassworks", url, width=1200, height=800, min_size=(800, 600))
        webview.start()
    finally:
        # Al cerrar la ventana, terminar el proceso del servidor Flask
        print("Cerrando el servidor...")
        servidor_proceso.terminate()
        servidor_proceso.wait()

if __name__ == "__main__":
    main()