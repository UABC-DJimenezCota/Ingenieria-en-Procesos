"""
Servidor Flask para Danny's Glassworks.
Requiere: pip install flask flask-cors pymysql
Variables opcionales: DB_HOST, DB_USER, DB_PASSWORD, FLASK_SECRET_KEY,
SESSION_COOKIE_SECURE y CORS_ALLOWED_ORIGINS
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path
import ipaddress
import os
import sys
import secrets
import socket
import threading
import traceback
import tkinter as tk
import webbrowser

import pymysql
from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

# Detección de entorno para rutas relativas estables
if getattr(sys, 'frozen', False):
    # Si se ejecuta como Host.exe
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Si se ejecuta como Host.py
    BASE_DIR = Path(__file__).resolve().parent
    
HTML_FILE = BASE_DIR.parent / "INTERFAZ" / "danny_s_glassworks.html"
ADDRESS_FILE = BASE_DIR.parent / "direccion_ip.txt"
IMAGES_DIR = BASE_DIR.parent / "RECURSOS"
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"}
PORT = 8000
VERSION = "2026.11.2"  # sube al cambiar rutas; la interfaz la usa para detectar un Host.exe viejo
MSG_SIN_PERMISOS = "No tienes permisos para esta acción."
ESTADOS_CITA = ("pendiente", "confirmada", "completada", "cancelada")

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
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
)
cors_origins = [
    origen.strip()
    for origen in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origen.strip()
]
CORS(app, resources={r"/api/*": {"origins": cors_origins}}, supports_credentials=True)


@app.errorhandler(Exception)
def manejar_excepcion(exc):
    """Toda falla de /api/* responde en JSON (la interfaz lee siempre el campo 'error')."""
    es_api = request.path.startswith("/api/")
    if isinstance(exc, HTTPException):
        if es_api:
            return jsonify({"ok": False, "error": exc.description or exc.name}), exc.code or 500
        return exc
    traceback.print_exc()
    if es_api:
        return jsonify({"ok": False, "error": "Error interno del servidor."}), 500
    return "Error interno del servidor.", 500


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


def requiere(admin=False, personal=False):
    """
    admin=True    -> solo rol 'admin'.
    personal=True -> solo 'empleado' o 'admin' (rechaza a los clientes).
    Sin argumentos -> cualquier usuario con sesión iniciada.
    """

    def decorador(funcion):
        @wraps(funcion)
        def envoltura(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                session.clear()
                return error("Sesión no iniciada.", 401)
            if usuario["rol"] == "cliente" and (admin or personal):
                return error(MSG_SIN_PERMISOS, 403)
            if admin and usuario["rol"] != "admin":
                return error(MSG_SIN_PERMISOS, 403)
            if personal and usuario["rol"] not in ("empleado", "admin"):
                return error(MSG_SIN_PERMISOS, 403)
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
            asegurar_columna(cur, "usuarios", "rol", "ENUM('admin','empleado','cliente') NOT NULL DEFAULT 'cliente'")
            asegurar_columna(cur, "usuarios", "email", "VARCHAR(255) NULL")
            asegurar_columna(cur, "usuarios", "activo", "BOOLEAN NOT NULL DEFAULT TRUE")
            # Bases antiguas: el ENUM podía no incluir 'cliente'. Se amplía sin tocar los datos.
            cur.execute(
                "ALTER TABLE usuarios MODIFY COLUMN rol "
                "ENUM('admin','empleado','cliente') NOT NULL DEFAULT 'cliente'"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS citas (
                  id INT NOT NULL AUTO_INCREMENT,
                  cliente_id INT NOT NULL,
                  fecha_hora DATETIME NOT NULL,
                  descripcion TEXT DEFAULT NULL,
                  estado ENUM('pendiente','confirmada','completada','cancelada') NOT NULL DEFAULT 'pendiente',
                  ubicacion VARCHAR(255) DEFAULT NULL,
                  presupuesto_estimado DECIMAL(10,2) DEFAULT 0.00,
                  create_time TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (id),
                  KEY idx_cliente (cliente_id),
                  CONSTRAINT fk_citas_cliente FOREIGN KEY (cliente_id) REFERENCES usuarios (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
                """
            )
            asegurar_columna(cur, "citas", "ubicacion", "VARCHAR(255) DEFAULT NULL")
            asegurar_columna(cur, "citas", "presupuesto_estimado", "DECIMAL(10,2) DEFAULT 0.00")
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


@app.route("/api/version", methods=["GET"])
def version():
    return jsonify({"ok": True, "version": VERSION})


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
    if len(username) > 16:
        return error("El usuario no puede superar 16 caracteres.")
    if len(password) < 8:
        return error("La contraseña debe tener al menos 8 caracteres.")
    if len(nombre) > 100:
        return error("El nombre no puede superar 100 caracteres.")
    if email and len(email) > 255:
        return error("El correo no puede superar 255 caracteres.")

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
            return error("El nombre de usuario ya existe.", 409)
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
@requiere(admin=True)  # los clientes reciben 403 "No tienes permisos para esta acción."
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
@requiere(personal=True)
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
            # Todos los roles: admin, empleado y cliente.
            cur.execute("SELECT id, username, nombre_completo, email, rol, activo FROM usuarios ORDER BY id")
            usuarios = [limpiar(f) for f in cur.fetchall()]
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


@app.route("/api/usuarios/<int:uid>/password", methods=["PATCH"])
@requiere(admin=True)
def cambiar_password_usuario(uid):
    data = request.get_json(silent=True) or {}
    nueva = data.get("nueva_password")
    if not isinstance(nueva, str) or len(nueva) < 8:
        return error("La nueva contraseña debe tener al menos 8 caracteres.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM usuarios WHERE id=%s", (uid,))
            if cur.fetchone() is None:
                return error("Usuario no encontrado.", 404)
            cur.execute(
                "UPDATE usuarios SET password=%s WHERE id=%s",
                (generate_password_hash(nueva), uid),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        traceback.print_exc()
        return error("No se pudo actualizar la contraseña.", 500)
    finally:
        conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------------- citas
def interpretar_fecha_hora(valor):
    """Acepta DATETIME local ('2026-11-05T10:30', '2026-11-05 10:30[:00]')."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip().replace("T", " ")
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


@app.route("/api/citas", methods=["POST"])
@requiere()
def crear_cita():
    data = request.get_json(silent=True) or {}
    fecha = interpretar_fecha_hora(data.get("fecha_hora"))
    descripcion = (data.get("descripcion") or "").strip()
    ubicacion = (data.get("ubicacion") or "").strip() or None
    cliente_id = g.usuario["id"]  # un cliente siempre agenda para sí mismo

    if g.usuario["rol"] in ("empleado", "admin"):
        try:
            cliente_id = int(data.get("cliente_id"))
        except (TypeError, ValueError):
            return error("Selecciona el cliente de la cita.")

    if fecha is None:
        return error("La fecha y hora de la cita no son válidas.")
    if not descripcion:
        return error("La descripción de la cita es obligatoria.")
    if ubicacion and len(ubicacion) > 255:
        return error("La ubicación no puede superar 255 caracteres.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            if cliente_id != g.usuario["id"]:
                cur.execute(
                    "SELECT id FROM usuarios WHERE id=%s AND rol='cliente' AND activo=TRUE",
                    (cliente_id,),
                )
                if cur.fetchone() is None:
                    return error("El cliente seleccionado no existe o está inactivo.", 404)
            cur.execute(
                "INSERT INTO citas (cliente_id, fecha_hora, descripcion, ubicacion, estado) "
                "VALUES (%s, %s, %s, %s, 'pendiente')",
                (cliente_id, fecha, descripcion, ubicacion),
            )
            cita_id = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        traceback.print_exc()
        return error("No se pudo guardar la cita.", 500)
    finally:
        conn.close()
    return jsonify({"ok": True, "id": cita_id}), 201


@app.route("/api/clientes", methods=["GET"])
@requiere(personal=True)
def listar_clientes():
    """Clientes activos, para que empleado/admin agenden una cita a su nombre."""
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, nombre_completo, email FROM usuarios "
                "WHERE rol='cliente' AND activo=TRUE ORDER BY nombre_completo, username"
            )
            clientes = [limpiar(f) for f in cur.fetchall()]
    finally:
        conn.close()
    return jsonify(clientes)


@app.route("/api/citas", methods=["GET"])
@requiere()
def listar_citas():
    conn = conectar()
    try:
        with conn.cursor() as cur:
            if g.usuario["rol"] == "cliente":
                cur.execute(
                    "SELECT * FROM citas WHERE cliente_id = %s ORDER BY fecha_hora DESC",
                    (g.usuario["id"],),
                )
            else:  # 'empleado' o 'admin'
                cur.execute(
                    "SELECT c.*, u.nombre_completo, u.email, u.username "
                    "FROM citas c JOIN usuarios u ON c.cliente_id = u.id "
                    "ORDER BY c.fecha_hora DESC"
                )
            citas = [limpiar(f) for f in cur.fetchall()]
    finally:
        conn.close()
    return jsonify(citas)


@app.route("/api/citas/<int:cid>", methods=["PATCH"])
@requiere(personal=True)
def actualizar_cita(cid):
    data = request.get_json(silent=True) or {}
    cambios, valores = [], []

    if "estado" in data:
        estado = str(data.get("estado") or "").strip().lower()
        if estado not in ESTADOS_CITA:
            return error("Estado inválido. Usa: " + ", ".join(ESTADOS_CITA) + ".")
        cambios.append("estado=%s")
        valores.append(estado)

    if data.get("presupuesto_estimado") is not None:
        try:
            presupuesto = dinero(data.get("presupuesto_estimado"))
        except (InvalidOperation, TypeError, ValueError):
            return error("Presupuesto estimado inválido.")
        if presupuesto < 0 or presupuesto > Decimal("99999999.99"):
            return error("El presupuesto estimado debe estar entre 0 y 99,999,999.99.")
        cambios.append("presupuesto_estimado=%s")
        valores.append(presupuesto)

    if not cambios:
        return error("Indica el estado y/o el presupuesto estimado a actualizar.")

    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM citas WHERE id=%s", (cid,))
            if cur.fetchone() is None:
                return error("Cita no encontrada.", 404)
            cur.execute(
                f"UPDATE citas SET {', '.join(cambios)} WHERE id=%s",
                (*valores, cid),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        traceback.print_exc()
        return error("No se pudo actualizar la cita.", 500)
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