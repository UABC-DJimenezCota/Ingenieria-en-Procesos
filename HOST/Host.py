"""
Servidor Flask para Danny's Glassworks.
Requiere: pip install flask flask-cors pymysql
Variables opcionales: DB_HOST, DB_USER, DB_PASSWORD, FLASK_SECRET_KEY
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path
import ipaddress
import os
import secrets
import socket
import threading
import traceback
import tkinter as tk
import webbrowser

import pymysql
from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "interfaz" / "danny_s_glassworks.html"
ADDRESS_FILE = BASE_DIR / "direccion_ip.txt"
IMAGES_DIR = BASE_DIR / "imagenes"
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"}
PORT = 8000

CATEGORIAS = [
    "Ventana simple",
    "Vidrio para puerta",
    "Ventana corrediza horizontal",
    "Ventana corrediza vertical",
    "Pared de vidrio",
    "Puertas",
    "Puertas de vidrio",
    "Espejos",
    "Vitrinas",
]

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": "danny's glassworks",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

app = Flask(__name__, static_folder=str(HTML_FILE.parent), static_url_path="")
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Activa SESSION_COOKIE_SECURE=True cuando uses HTTPS.
    SESSION_COOKIE_SECURE=False,
)
CORS(app, supports_credentials=True)


# ---------------------------------------------------------------- utilidades
def conectar():
    return pymysql.connect(**DB_CONFIG)


def error(mensaje, codigo=400):
    return jsonify({"ok": False, "error": mensaje}), codigo


def dinero(valor):
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def limpiar(fila):
    """Convierte Decimal y datetime a tipos que jsonify entiende."""
    if fila is None:
        return None
    resultado = {}
    for clave, valor in fila.items():
        if isinstance(valor, Decimal):
            valor = float(valor)
        elif isinstance(valor, datetime):
            valor = valor.strftime("%Y-%m-%d %H:%M:%S")
        resultado[clave] = valor
    return resultado


def usuario_actual():
    uid = session.get("usuario_id")
    if not uid:
        return None
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, nombre_completo, rol FROM usuarios WHERE id=%s AND activo=TRUE",
                (uid,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def requiere(admin=False):
    def decorador(funcion):
        @wraps(funcion)
        def envoltura(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                session.clear()
                return error("Sesión no iniciada.", 401)
            if admin and usuario["rol"] != "admin":
                return error("No tienes permiso para esta acción.", 403)
            g.usuario = usuario
            return funcion(*args, **kwargs)

        return envoltura

    return decorador


# ------------------------------------------------------------------- esquema
def asegurar_columna(cur, tabla, columna, definicion):
    cur.execute(
        "SELECT COUNT(*) AS total FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (tabla, columna),
    )
    if cur.fetchone()["total"] == 0:
        cur.execute(f"ALTER TABLE `{tabla}` ADD COLUMN `{columna}` {definicion}")


def asegurar_esquema():
    """Agrega columnas nuevas sin borrar tablas ni ventas existentes (MySQL y MariaDB)."""
    conn = conectar()
    try:
        with conn.cursor() as cur:
            asegurar_columna(cur, "inventario", "categoria", "VARCHAR(100) NOT NULL DEFAULT 'Sin clasificar'")
            asegurar_columna(cur, "usuarios", "rol", "ENUM('admin','empleado') NOT NULL DEFAULT 'empleado'")
            asegurar_columna(cur, "usuarios", "activo", "BOOLEAN NOT NULL DEFAULT TRUE")
            asegurar_columna(cur, "recibos", "efectivo_recibido", "DECIMAL(10,2) NULL")
            asegurar_columna(cur, "recibos", "cambio", "DECIMAL(10,2) NOT NULL DEFAULT 0.00")
            cur.execute("UPDATE usuarios SET rol='admin' WHERE username='admin'")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------------- páginas
@app.route("/")
def index():
    return app.send_static_file(HTML_FILE.name)


# ------------------------------------------------------------------ imágenes
def clave_imagen(nombre):
    """'Ventana_Simple' -> 'ventana simple' (se compara sin mayúsculas ni extensión)."""
    return " ".join(nombre.lower().replace("_", " ").replace("-", " ").split())


@app.route("/api/imagenes", methods=["GET"])
def listar_imagenes():
    """Devuelve {nombre_en_minusculas: archivo} con lo que haya en la carpeta imagenes."""
    encontrados = {}
    if IMAGES_DIR.is_dir():
        for archivo in sorted(IMAGES_DIR.iterdir()):
            if archivo.is_file() and archivo.suffix.lower() in EXTENSIONES_IMAGEN:
                encontrados.setdefault(clave_imagen(archivo.stem), archivo.name)
    return jsonify(encontrados)


@app.route("/imagenes/<path:nombre>")
def servir_imagen(nombre):
    return send_from_directory(IMAGES_DIR, nombre)


# -------------------------------------------------------------------- sesión
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return error("Usuario y contraseña requeridos.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password, nombre_completo, rol, activo FROM usuarios WHERE username=%s",
                (username,),
            )
            usuario = cur.fetchone()
            valido = False
            if usuario and usuario["activo"]:
                guardada = usuario["password"] or ""
                if guardada.startswith(("pbkdf2:", "scrypt:")):
                    valido = check_password_hash(guardada, password)
                else:
                    # Cuenta con contraseña en texto plano: se valida y se convierte a hash.
                    valido = secrets.compare_digest(guardada.encode("utf-8"), password.encode("utf-8"))
                    if valido:
                        cur.execute(
                            "UPDATE usuarios SET password=%s WHERE id=%s",
                            (generate_password_hash(password), usuario["id"]),
                        )
                        conn.commit()
    finally:
        conn.close()

    if not valido:
        return error("Usuario o contraseña incorrectos.", 401)

    session.clear()
    session["usuario_id"] = usuario["id"]
    return jsonify(
        {
            "ok": True,
            "usuario": {
                "id": usuario["id"],
                "username": usuario["username"],
                "nombre_completo": usuario["nombre_completo"],
                "rol": usuario["rol"],
            },
        }
    )


@app.route("/api/sesion", methods=["GET"])
def sesion():
    usuario = usuario_actual()
    if usuario is None:
        return error("Sesión no iniciada.", 401)
    return jsonify({"ok": True, "usuario": usuario})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/registro", methods=["POST"])
def registro():
    """Permite a los nuevos clientes crear su propia cuenta."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    nombre = (data.get("nombre_completo") or "").strip()
    email = (data.get("email") or "").strip() or None

    if not username or not password or not nombre:
        return error("Usuario, contraseña y nombre son obligatorios.")
    if len(password) < 8:
        return error("La contraseña debe tener al menos 8 caracteres.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO usuarios (username, password, nombre_completo, email, rol) VALUES (%s, %s, %s, %s, 'cliente')",
                (username, generate_password_hash(password), nombre, email),
            )
        conn.commit()
    except pymysql.err.IntegrityError as exc:
        conn.rollback()
        if exc.args and exc.args[0] == 1062:
            return error("El nombre de usuario ya está en uso.", 409)
        raise
    finally:
        conn.close()
    return jsonify({"ok": True}), 201


# ------------------------------------------------------------------ catálogo
@app.route("/api/catalogo", methods=["GET"])
def catalogo():
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT categoria, CAST(COALESCE(SUM(cantidad), 0) AS SIGNED) AS total_unidades "
                "FROM inventario GROUP BY categoria"
            )
            filas = cur.fetchall()
    finally:
        conn.close()
    return jsonify(filas)


# ---------------------------------------------------------------- inventario
@app.route("/api/inventario", methods=["GET"])
@requiere()
def listar_inventario():
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre, categoria, precio, cantidad FROM inventario ORDER BY id")
            productos = [limpiar(f) for f in cur.fetchall()]
    finally:
        conn.close()
    return jsonify(productos)


@app.route("/api/inventario", methods=["POST"])
@requiere(admin=True)
def crear_producto():
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()
    categoria = (data.get("categoria") or "Sin clasificar").strip()
    if not nombre or len(nombre) > 100:
        return error("El nombre es obligatorio (máximo 100 caracteres).")
    if categoria != "Sin clasificar" and categoria not in CATEGORIAS:
        return error("Categoría no válida.")
    try:
        precio = dinero(data.get("precio"))
        cantidad = int(data.get("cantidad"))
    except (InvalidOperation, TypeError, ValueError):
        return error("Precio o stock inválido.")
    if precio <= 0 or cantidad < 0:
        return error("El precio debe ser mayor a 0 y el stock no puede ser negativo.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO inventario (nombre, categoria, precio, cantidad) VALUES (%s, %s, %s, %s)",
                (nombre, categoria, precio, cantidad),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True}), 201


@app.route("/api/inventario/<int:pid>/stock", methods=["PATCH"])
@requiere(admin=True)
def ajustar_stock(pid):
    data = request.get_json(silent=True) or {}
    try:
        delta = int(data.get("delta"))
    except (TypeError, ValueError):
        return error("Ajuste inválido.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventario SET cantidad = GREATEST(0, cantidad + %s) WHERE id=%s",
                (delta, pid),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return error("Producto no encontrado.", 404)
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventario/<int:pid>", methods=["DELETE"])
@requiere(admin=True)
def eliminar_producto(pid):
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM inventario WHERE id=%s", (pid,))
            if cur.rowcount == 0:
                conn.rollback()
                return error("Producto no encontrado.", 404)
        conn.commit()
    except pymysql.err.IntegrityError:
        conn.rollback()
        return error("No se puede eliminar: el producto ya tiene ventas registradas.", 409)
    finally:
        conn.close()
    return jsonify({"ok": True})


# -------------------------------------------------------------------- ventas
@app.route("/api/ventas", methods=["POST"])
@requiere()
def registrar_venta():
    data = request.get_json(silent=True) or {}
    items = data.get("productos")
    metodo = str(data.get("metodo_pago") or "").strip().lower()

    if metodo not in ("efectivo", "tarjeta"):
        return error("Método de pago inválido.")
    if not isinstance(items, list) or not items:
        return error("La venta no tiene productos.")

    cantidades = {}
    for item in items:
        try:
            pid = int(item.get("producto_id"))
            cant = int(item.get("cantidad"))
        except (TypeError, ValueError, AttributeError):
            return error("Datos de venta inválidos.")
        if cant < 1:
            return error("Datos de venta inválidos.")
        cantidades[pid] = cantidades.get(pid, 0) + cant

    conn = conectar()
    try:
        with conn.cursor() as cur:
            ids = sorted(cantidades)
            marcadores = ",".join(["%s"] * len(ids))
            cur.execute(
                f"SELECT id, nombre, precio, cantidad FROM inventario WHERE id IN ({marcadores}) ORDER BY id FOR UPDATE",
                ids,
            )
            filas = {f["id"]: f for f in cur.fetchall()}

            total = Decimal("0.00")
            for pid in ids:
                fila = filas.get(pid)
                if fila is None:
                    conn.rollback()
                    return error("Un producto de la venta ya no existe.", 404)
                if fila["cantidad"] < cantidades[pid]:
                    conn.rollback()
                    return error(f"No hay existencias suficientes de {fila['nombre']}.")
                total += dinero(fila["precio"]) * cantidades[pid]
            total = dinero(total)

            if metodo == "efectivo":
                try:
                    efectivo = dinero(data.get("efectivo_recibido"))
                except (InvalidOperation, TypeError):
                    conn.rollback()
                    return error("Efectivo recibido inválido.")
                if efectivo < total:
                    conn.rollback()
                    return error("El efectivo recibido debe ser igual o mayor al total.")
                cambio = efectivo - total
            else:
                efectivo = None
                cambio = Decimal("0.00")

            ahora = datetime.now()
            base = "R-" + ahora.strftime("%Y%m%d%H%M%S")
            folio, n = base, 1
            while True:
                cur.execute("SELECT 1 FROM recibos WHERE folio=%s", (folio,))
                if cur.fetchone() is None:
                    break
                n += 1
                folio = f"{base}-{n}"

            cur.execute(
                "INSERT INTO recibos (folio, fecha_hora, subtotal, total, metodo_pago, usuario_id, efectivo_recibido, cambio) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (folio, ahora, total, total, metodo, g.usuario["id"], efectivo, cambio),
            )
            recibo_id = cur.lastrowid
            for pid in ids:
                cur.execute(
                    "INSERT INTO recibo_detalle (recibo_id, producto_id, cantidad, precio_unitario) VALUES (%s, %s, %s, %s)",
                    (recibo_id, pid, cantidades[pid], dinero(filas[pid]["precio"])),
                )
                cur.execute(
                    "UPDATE inventario SET cantidad = cantidad - %s WHERE id=%s",
                    (cantidades[pid], pid),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        traceback.print_exc()
        return error("No se pudo guardar la venta.", 500)
    finally:
        conn.close()

    return (
        jsonify(
            {
                "ok": True,
                "folio": folio,
                "recibo_id": recibo_id,
                "total": float(total),
                "cambio": float(cambio),
            }
        ),
        201,
    )


# ------------------------------------------------------------------- recibos
@app.route("/api/recibos", methods=["GET"])
@requiere(admin=True)
def listar_recibos():
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.folio, r.fecha_hora, r.total, r.metodo_pago,
                       u.username, u.nombre_completo
                FROM recibos r
                LEFT JOIN usuarios u ON u.id = r.usuario_id
                ORDER BY r.fecha_hora DESC, r.id DESC
                """
            )
            recibos = [limpiar(f) for f in cur.fetchall()]
    finally:
        conn.close()
    return jsonify(recibos)


@app.route("/api/recibos/<int:recibo_id>", methods=["GET"])
@requiere(admin=True)
def detalle_recibo(recibo_id):
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM recibos WHERE id=%s", (recibo_id,))
            recibo = limpiar(cur.fetchone())
            if recibo is None:
                return error("Recibo no encontrado.", 404)
            cur.execute(
                """
                SELECT rd.id, rd.cantidad, rd.precio_unitario, i.nombre
                FROM recibo_detalle rd
                JOIN inventario i ON i.id = rd.producto_id
                WHERE rd.recibo_id=%s
                ORDER BY rd.id
                """,
                (recibo_id,),
            )
            recibo["detalle"] = [limpiar(f) for f in cur.fetchall()]
    finally:
        conn.close()
    return jsonify(recibo)


# ----------------------------------------------------------------- empleados
@app.route("/api/usuarios", methods=["GET"])
@requiere(admin=True)
def listar_usuarios():
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, nombre_completo, email, rol, activo FROM usuarios ORDER BY id")
            usuarios = cur.fetchall()
    finally:
        conn.close()
    return jsonify(usuarios)


@app.route("/api/usuarios", methods=["POST"])
@requiere(admin=True)
def crear_usuario():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    nombre = (data.get("nombre_completo") or "").strip()
    email = (data.get("email") or "").strip() or None
    rol = data.get("rol") or "empleado"

    if not username or not password or not nombre:
        return error("Usuario, contraseña y nombre son obligatorios.")
    if len(username) > 16:
        return error("El usuario no puede superar 16 caracteres.")
    if len(password) < 8:
        return error("La contraseña debe tener al menos 8 caracteres.")
    if rol not in ("admin", "empleado"):
        return error("Rol inválido.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO usuarios (username, password, nombre_completo, email, rol) VALUES (%s, %s, %s, %s, %s)",
                (username, generate_password_hash(password), nombre, email, rol),
            )
        conn.commit()
    except pymysql.err.IntegrityError as exc:
        conn.rollback()
        if exc.args and exc.args[0] == 1062:
            return error("El usuario ya existe.", 409)
        raise
    finally:
        conn.close()
    return jsonify({"ok": True}), 201


@app.route("/api/usuarios/<int:uid>", methods=["DELETE"])
@requiere(admin=True)
def desactivar_usuario(uid):
    if uid == g.usuario["id"]:
        return error("No puedes desactivar tu propia cuenta.")
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET activo=FALSE WHERE id=%s", (uid,))
            if cur.rowcount == 0:
                conn.rollback()
                return error("Usuario no encontrado.", 404)
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ------------------------------------------------------------ arranque / red
def obtener_ip_local():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        ip = sock.getsockname()[0]
        parsed = ipaddress.ip_address(ip)
        if parsed.is_private and not parsed.is_loopback:
            return ip
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for resultado in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = resultado[4][0]
            parsed = ipaddress.ip_address(ip)
            if parsed.is_private and not parsed.is_loopback:
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def puerto_libre():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def pausar(mensaje="Presiona Enter para cerrar..."):
    try:
        input(mensaje)
    except (EOFError, RuntimeError):
        pass


def mostrar_ventana_direccion(url):
    root = tk.Tk()
    root.title("Danny's Glassworks - Servidor local")
    root.geometry("520x190")
    root.resizable(False, False)

    tk.Label(root, text="Servidor iniciado en la red local", font=("Segoe UI", 14, "bold")).pack(pady=(18, 8))
    url_entry = tk.Entry(root, font=("Segoe UI", 12), justify="center", width=42)
    url_entry.insert(0, url)
    url_entry.configure(state="readonly")
    url_entry.pack(pady=4)

    def abrir_pagina():
        webbrowser.open(url)

    def copiar_direccion():
        root.clipboard_clear()
        root.clipboard_append(url)
        estado.configure(text="Dirección copiada")

    acciones = tk.Frame(root)
    acciones.pack(pady=12)
    tk.Button(acciones, text="Abrir página", command=abrir_pagina).pack(side="left", padx=6)
    tk.Button(acciones, text="Copiar dirección", command=copiar_direccion).pack(side="left", padx=6)
    estado = tk.Label(root, text=f"Dirección guardada en: {ADDRESS_FILE}", font=("Segoe UI", 9))
    estado.pack()
    root.mainloop()


def main():
    if not HTML_FILE.exists():
        raise FileNotFoundError(f"No se encontró la interfaz: {HTML_FILE}")
    IMAGES_DIR.mkdir(exist_ok=True)
    asegurar_esquema()
    if not puerto_libre():
        raise RuntimeError(f"El puerto {PORT} ya está en uso. Cierra la otra copia del servidor.")

    url = f"http://{obtener_ip_local()}:{PORT}"
    ADDRESS_FILE.write_text(url + "\n", encoding="utf-8")

    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True),
        daemon=True,
    ).start()

    print("=" * 50)
    print("Servidor iniciado. Dirección en la red local:")
    print(f"  {url}")
    print("=" * 50)

    try:
        mostrar_ventana_direccion(url)
    except tk.TclError:
        print("No se pudo abrir la ventana; usa la dirección de arriba.")

    # Pausa después de mostrar la IP: el servidor sigue activo hasta presionar Enter.
    pausar("Servidor activo. Presiona Enter para detenerlo y cerrar...")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        pausar("\nOcurrió un error. Presiona Enter para cerrar...")
