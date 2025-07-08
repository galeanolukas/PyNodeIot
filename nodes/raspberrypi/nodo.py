#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import socket
import argparse
import threading
import time
import platform
import re
from datetime import timedelta

# ======================================================================
# CONFIGURACIÓN DEL ENTORNO VIRTUAL
# ======================================================================
def setup_virtualenv():
    """Configura el entorno virtual si no existe"""
    VENV_NAME = "raspberry_env"
    REQUIREMENTS = [
        "microdot",
        "jinja2",
        "websocket-client",
        "psutil",
        "requests"
    ]

    # Verificar si ya estamos en un entorno virtual
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print(f"✅ Entorno virtual ya activado: {sys.prefix}")
        return True

    print("🔧 Configurando entorno virtual...")

    # Crear entorno virtual si no existe
    if not os.path.exists(VENV_NAME):
        try:
            subprocess.run([sys.executable, "-m", "venv", VENV_NAME], check=True)
            print(f"✅ Entorno virtual creado en: {VENV_NAME}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error creando entorno virtual: {e}")
            return False

    # Instalar dependencias
    pip_path = os.path.join(VENV_NAME, 'bin', 'pip') if os.name != 'nt' else os.path.join(VENV_NAME, 'Scripts', 'pip.exe')

    try:
        subprocess.run([pip_path, "install", "--upgrade", "pip"], check=True)
        subprocess.run([pip_path, "install"] + REQUIREMENTS, check=True)
        print("✅ Dependencias instaladas correctamente")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error instalando dependencias: {e}")
        return False

def activate_virtualenv():
    """Intenta activar el entorno virtual"""
    VENV_NAME = "raspberry_env"

    # Ruta al ejecutable Python del entorno virtual
    python_path = os.path.join(VENV_NAME, 'bin', 'python') if os.name != 'nt' else os.path.join(VENV_NAME, 'Scripts', 'python.exe')

    if not os.path.exists(python_path):
        print("❌ No se encontró el entorno virtual")
        return False

    # En Windows, crear un script batch para ejecución
    if os.name == 'nt':
        bat_content = f"""
        @echo off
        call {VENV_NAME}\\Scripts\\activate.bat
        python nodo.py %*
        """
        with open("run_node.bat", "w") as f:
            f.write(bat_content)
        print("\n⚠️ En Windows, ejecuta el archivo 'run_node.bat' en lugar de este script")
        return False

    # En Linux/Mac, ejecutar directamente
    os.execl(python_path, python_path, *sys.argv)
# ======================================================================
# FUNCIONES PRINCIPALES DEL NODO
# ======================================================================
def main():
    # Configuración inicial del entorno
    if not setup_virtualenv():
        sys.exit(1)

    # Intentar activar el entorno virtual si no está activo
    if not (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)):
        print("🔧 Activando entorno virtual...")
        activate_virtualenv()
        return  # Esta línea solo se alcanza si hay error en la activación

    from microdot import Microdot, send_file, redirect
    from microdot.jinja import Template
    from microdot.websocket import with_websocket
    import websocket
    import requests
    import hashlib
    import psutil
    import asyncio
    from datetime import datetime

    # El resto de tu código del nodo...
    app = Microdot()
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=3000)
    parser.add_argument('--server', type=str, required=True)
    args = parser.parse_args()

    # Añadir al inicio del archivo
    AUTH_FILE = "node_auth.json"

    def setup_auth():
        """Configura la autenticación única del nodo"""
        if os.path.exists(AUTH_FILE):
            print("✅ Configuración de autenticación ya existe")
            return True
        else:
            return False

    def get_auth_credentials():
        """Obtiene las credenciales de autenticación"""
        try:
            with open(AUTH_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error obteniendo credenciales: {e}")
            return None

    def generate_node_id():
        auth_data = get_auth_credentials()
        if auth_data:
            return auth_data["node_id"]
        else:
            hostname = socket.gethostname().lower().replace("-", "_")
            timestamp = datetime.now().strftime("%m%d%H%M%S")[-4:]  # Últimos 4 dígitos
            return f"nodo_{hostname}_{timestamp}"

    NODE_ID = generate_node_id()

    RESOURCES_RECEIVED = False
    # Añadir estas constantes al inicio del archivo
    SHARED_DIR = "storage"
    SHARED_DIR_CONFIG = "shared_dir_config.json"
    # Añadir estas funciones
    def format_datetime(timestamp):
        return datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y %H:%M:%S')

    # En la configuración de Microdot, antes de app.run:
    def get_shared_dir():
        """Obtiene el directorio compartido configurado"""
        try:
            if os.path.exists(SHARED_DIR_CONFIG):
                with open(SHARED_DIR_CONFIG, 'r') as f:
                    config = json.load(f)
                    return config.get('shared_dir', SHARED_DIR)
            return SHARED_DIR
        except Exception as e:
            print(f"Error leyendo configuración de directorio: {e}")
            return SHARED_DIR

    def save_shared_dir(path):
        """Guarda la configuración del directorio compartido"""
        try:
            with open(SHARED_DIR_CONFIG, 'w') as f:
                json.dump({'shared_dir': path}, f)
            return True
        except Exception as e:
            print(f"Error guardando configuración de directorio: {e}")
            return False

    def list_files(directory):
        """Lista archivos en el directorio compartido"""
        try:
            files = []
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                files.append({
                    'name': item,
                    'size': os.path.getsize(item_path),
                    'modified': os.path.getmtime(item_path),
                    'is_dir': os.path.isdir(item_path)
                })
            return sorted(files, key=lambda x: x['name'])
        except Exception as e:
            print(f"Error listando archivos: {e}")
            return []

    def verify_password(password, salt_hex, key_hex):
        """Verifica una contraseña contra un hash almacenado"""
        try:
            salt = bytes.fromhex(salt_hex)
            stored_key = bytes.fromhex(key_hex)
            new_key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
            return new_key == stored_key
        except:
            return False

    def save_password(password):
        """Guarda la contraseña cifrada localmente y la envía al servidor"""
        # Generar hash seguro con salt
        salt = os.urandom(32)
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)

        # Crear estructura de datos de autenticación
        auth_data = {
            'node_id': NODE_ID,
            'salt': salt.hex(),
            'key': key.hex(),
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        # Guardar localmente
        try:
            with open(AUTH_FILE, 'w') as f:
                json.dump(auth_data, f)
            print("✅ Contraseña guardada localmente")
            return True

        except Exception as e:
            print(f"❌ Error guardando contraseña local: {e}")
            return False

    def check_auth_configured():
        """Verifica si la autenticación está configurada"""
        return os.path.exists(AUTH_FILE)

    def get_server_host(server_url):
        from urllib.parse import urlparse

        try:
            # Asegurar que la URL tenga esquema (agregar ws:// si no está presente)
            if not server_url.startswith(('ws://', 'wss://', 'http://', 'https://')):
                server_url = 'ws://' + server_url

            parsed = urlparse(server_url)
            # Validar que haya un hostname
            if not parsed.hostname:
                raise ValueError("No se pudo extraer el host de la URL")

            return parsed.hostname

        except Exception as e:
            print(f"Error al parsear la URL del servidor: {e}")
            return None

    def detect_device_type():
        # 1. Verificar si es Raspberry Pi
        if platform.system().lower() == 'linux':
            # Método 1: Verificar modelo en device-tree
            if os.path.exists('/proc/device-tree/model'):
                with open('/proc/device-tree/model', 'r') as f:
                    model = f.read().lower()
                    if 'raspberry pi' in model:
                        return 'raspberry_pi'

            # Método 2: Verificar hardware en cpuinfo
            try:
                cpuinfo = subprocess.getoutput('cat /proc/cpuinfo')
                if 'raspberry pi' in cpuinfo.lower() or 'bcm' in cpuinfo.lower():
                    return 'raspberry_pi'
            except:
                pass

        # 2. Verificar si es laptop (tiene batería)
        if os.path.exists('/sys/class/power_supply/BAT0'):
            return 'laptop'

        # 3. Para otros casos asumimos que es PC (Windows/Mac/Linux sin batería)
        return 'pc' if platform.system().lower() in ('linux', 'windows', 'darwin') else 'unknown'

    def get_system_info():
        """Obtiene información detallada del sistema"""
        try:
            # Información básica
            hostname = socket.gethostname()

            # Información de CPU
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
            model = re.search('Model\s+:\s+(.*)', cpuinfo)
            cpu = model.group(1) if model else platform.processor()

            # Uso de CPU
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memoria
            mem = psutil.virtual_memory()
            memory_used = mem.used / (1024 ** 2)
            memory_total = mem.total / (1024 ** 2)
            memory_free = memory_total - memory_used
            memory_percent = mem.percent
            memory_info = f"{memory_used:.1f} MB / {memory_total:.1f} MB"

            # Uptime
            uptime_seconds = time.time() - psutil.boot_time()
            uptime = str(timedelta(seconds=uptime_seconds)).split('.')[0]

            # Sistema operativo
            os_info = f"{platform.system()} {platform.release()}"

            # Temperatura CPU (Raspberry Pi)
            try:
                temp = subprocess.getoutput("vcgencmd measure_temp").split('=')[1].replace("'C", "")
                temperature = f"{float(temp):.1f} °C"
                temp_value = float(temp)
            except:
                temperature = "No disponible"
                temp_value = 0

            # Disco
            disk = psutil.disk_usage('/')
            disk_free = disk.free / (1024 ** 3)
            disk_total = disk.total / (1024 ** 3)
            disk_percent = disk.percent
            disk_info = f"{disk_free:.1f}G libres de {disk_total:.1f}G"

            return {
                'hostname': hostname,
                'cpu': cpu,
                'cpu_percent': cpu_percent,
                'memory_info': memory_info,
                'memory_free': memory_free,
                'memory_total': memory_total,
                'memory_percent': memory_percent,
                'uptime': uptime,
                'os': os_info,
                'temperature': temperature,
                'temp_value': temp_value,
                'disk_info': disk_info,
                'disk_free': disk_free,
                'disk_total': disk_total,
                'disk_percent': disk_percent,
                'last_update': time.strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            print(f"Error obteniendo info del sistema: {str(e)}")
            return {}

    def get_public_ip():
        try:
            return requests.get('https://api.ipify.org', timeout=3).text
        except:
            return "unknown"

    def check_resources():
        required_files = {
            'static': ['w3.css', 'logo.svg'],
            'templates': ['node_template.html']
        }
        for directory, files in required_files.items():
            for file in files:
                if not os.path.exists(f"{directory}/{file}"):
                    return False
        return True

    def save_resource(resource_type, filename, content):
        try:
            if resource_type == 'css':
                path = 'static'
            elif resource_type == 'template':
                path = 'templates'
            elif resource_type == 'image':
                path = 'static'
            else:
                print(f"⚠️ Tipo de recurso desconocido: {resource_type}")
                return False

            os.makedirs(path, exist_ok=True)
            with open(f"{path}/{filename}", "w", encoding='utf-8') as f:
                f.write(content)
            print(f"💾 Guardado: {path}/{filename}")
            return True
        except Exception as e:
            print(f"❌ Error guardando recurso: {str(e)}")
            return False

    def on_message(ws, message):
        global RESOURCES_RECEIVED
        try:
            data = json.loads(message)
            if 'type' in data and 'content' in data:
                if save_resource(data['type'], data['filename'], data['content']):
                    RESOURCES_RECEIVED = True
        except Exception as e:
            print(f"⚠️ Error procesando mensaje: {str(e)}")

    def on_error(ws, error):
        print(f"🔌 Error WS: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"🔌 Desconectado: {close_msg or 'Sin mensaje'}")
        time.sleep(2)
        connect_to_server()

    def on_open(ws):
        print("🔗 Conexión WebSocket establecida")
        # Enviar información inicial del nodo
        initial_data = {
            'node_id': NODE_ID,
            'public_ip': get_public_ip(),
            'node_type': detect_device_type(),
            'port': args.port
        }
        # Si ya hay auth configurada, enviar las credenciales
        if check_auth_configured():
            try:
                with open(AUTH_FILE, 'r') as f:
                    auth_data = json.load(f)
                    initial_data['auth_data'] = auth_data

            except Exception as e:
                print(f"⚠️ Error cargando credenciales: {e}")

        # Enviar información inicial del nodo
        ws.send(json.dumps(initial_data, ensure_ascii=False))

        # Función para enviar datos periódicamente
        def send_system_data():
            while True:
                try:
                    if ws.sock and ws.sock.connected:
                        system_info = get_system_info()
                        ws.send(json.dumps({
                            'type': 'system_info',
                            'data': system_info,
                        }, ensure_ascii=False))
                        print(f"📤 Datos enviados: {system_info['last_update']}")
                    else:
                        print("⚠️ WebSocket no conectado, no se envían datos")
                except Exception as e:
                    print(f"⚠️ Error enviando datos: {str(e)}")
                time.sleep(5)  # Enviar cada 5 segundos

        # Iniciar el hilo para enviar datos
        threading.Thread(target=send_system_data, daemon=True).start()

    def connect_to_server():
        while True:
            try:
                print(f"🔗 Conectando a {args.server}...")
                ws = websocket.WebSocketApp(
                    args.server,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    on_open=on_open
                )
                ws.run_forever()
            except Exception as e:
                print(f"⏳ Error de conexión: {str(e)} - Reintentando en 5s...")
                time.sleep(5)

    @app.route('/')
    def home(request):
        system_info = get_system_info()
        """Muestra el explorador de archivos"""
        current_dir = get_shared_dir()
        files = list_files(current_dir)
        context = {"system_info": system_info,
                    "node_id": NODE_ID.upper(),
                    "ip_publica": get_public_ip(),
                    'host_url': f"{get_server_host(args.server)}/login?id={NODE_ID}",
                    'auth_configured': check_auth_configured(),
                    'files': files,
                    'current_dir': current_dir,
                    'parent_dir': os.path.dirname(current_dir)
                    }

        if not check_resources():
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Nodo en Configuración</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                    .spinner { margin: 20px auto; width: 50px; height: 50px; border: 5px solid #f3f3f3;
                        border-top: 5px solid #3498db; border-radius: 50%; animation: spin 1s linear infinite; }
                    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                </style>
            </head>
            <body>
                <h1>Nodo en configuración</h1>
                <p>Descargando recursos del servidor...</p>
                <div class="spinner"></div>
                <p>ID del nodo: """ + NODE_ID + """</p>
            </body>
            </html>
            """
        return Template('node_template.html').render(context), {'Content-Type': 'text/html; charset=utf-8'}

    @app.route('/registro', methods=['GET', 'POST'])
    def setup_password(request):
        context = {"msj": None, "nodo_id": NODE_ID, "auth_configured": check_auth_configured()}

        if request.method == 'POST':
            password = request.form.get('password', '')
            print(password)
            confirm = request.form.get('confirmPassword', '')

            if len(password) < 8:
                context["msj"] = "La contraseña debe tener al menos 8 caracteres"
            elif password != confirm:
                context["msj"] = "Las contraseñas no coinciden"
            else:
                if save_password(password):
                    return redirect('/')
                else:
                    context["msj"] = "Error al guardar la contraseña"

        return redirect("/")

    @app.route('/files', methods=['GET'])
    def file_browser(request):
        """Muestra el explorador de archivos"""
        current_dir = get_shared_dir()
        files = list_files(current_dir)
        context = {
            'files': files,
            'current_dir': current_dir,
            'parent_dir': os.path.dirname(current_dir)
        }
        return Template('file_browser.html').render(context), {'Content-Type': 'text/html; charset=utf-8'}

    @app.route('/files/upload', methods=['POST'])
    def upload_file(request):
        """Maneja la subida de archivos"""
        current_dir = get_shared_dir()
        try:
            file = request.files.get('file')
            if file:
                file.save(os.path.join(current_dir, file.filename))
                return {'status': 'success', 'message': 'Archivo subido correctamente'}
            return {'status': 'error', 'message': 'No se recibió archivo'}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    @app.route('/files/change_dir', methods=['POST'])
    def change_directory(request):
        """Cambia el directorio compartido"""
        new_dir = request.form.get('new_dir')
        if new_dir and os.path.isdir(new_dir):
            if save_shared_dir(new_dir):
                return redirect('/files')
        return {'status': 'error', 'message': 'Directorio no válido'}

    @app.route('/files/download/<filename>', methods=['GET'])
    def download_file(request, filename):
        """Descarga un archivo"""
        current_dir = get_shared_dir()
        file_path = os.path.join(current_dir, filename)
        if os.path.exists(file_path):
            return send_file(file_path)
        return 'Archivo no encontrado', 404

    @app.route('/static/<path:path>')
    def serve_static(request, path):
        # Seguridad: Prevenir directory traversal
        if '..' in path or path.startswith('/'):
            return 'Acceso denegado', 403

        file_path = f"static/{path}"

        # Verificar si el archivo existe
        if not os.path.isfile(file_path):
            return 'Archivo no encontrado', 404

        # Determinar el tipo MIME basado en la extensión
        mime_types = {
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.html': 'text/html'
        }

        ext = os.path.splitext(path)[1]
        content_type = mime_types.get(ext.lower(), 'text/plain')

        return send_file(file_path, content_type=content_type)

    @app.route('/ws/node')
    @with_websocket
    async def node_websocket(request, ws):
        while True:
            try:
                # Enviar datos del sistema cada 2 segundos
                system_info = get_system_info()
                await ws.send(json.dumps({
                    'type': 'system_info',
                    'data': system_info,
                }))
                await asyncio.sleep(2)
            except:
                break

    # Iniciar la aplicación
    if __name__ == '__main__':
        # Crear directorios necesarios
        os.makedirs("static", exist_ok=True)
        os.makedirs("templates", exist_ok=True)
        os.makedirs(get_shared_dir(), exist_ok=True)
        # Iniciar conexión WebSocket en segundo plano
        threading.Thread(target=connect_to_server, daemon=True).start()

        print(f"🟢 Nodo {NODE_ID} iniciado en http://0.0.0.0:{args.port}")
        app.run(host='0.0.0.0', port=args.port)

if __name__ == '__main__':
    main()
