from flask import Flask, render_template, request, redirect, flash, session, jsonify
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
import json
import os
from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Por favor, inicia sesión primero")
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_para_flash' # Obligatorio para usar flash()

# Inicializamos Socket.io
# Usar una clave secreta real desde las variables de entorno
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'una-clave-muy-secreta-de-prueba')

# Permitir CORS solo para tu dominio (o "*" para pruebas iniciales)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Evento cuando un usuario abre cualquier chat
@socketio.on('join')
def on_join(data):
    # El usuario se une a una sala con su propio ID
    # Esto permite que el servidor le envíe mensajes privados
    room = str(session.get('user_id'))
    join_room(room)
    print(f"📡 Usuario {session.get('user_nombre')} entró a su sala privada: {room}")

@socketio.on('enviar_mensaje')
def handle_message(data):
    emisor_id = session.get('user_id')
    receptor_id = data['receptor_id']
    mensaje = data['mensaje']
    emisor_nombre = session.get('user_nombre')

    # 1. Guardar en la Base de Datos (Persistencia)
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO mensajes (emisor_id, receptor_id, contenido) 
        VALUES (%, %, %)
    ''', (emisor_id, receptor_id, mensaje))
    conn.commit()
    conn.close()

    # 2. Enviar el mensaje SOLO a los dos involucrados
    # Enviamos a la sala del receptor
    emit('nuevo_mensaje', {
        'msg': mensaje,
        'de': emisor_nombre,
        'de_id': emisor_id
    }, room=str(receptor_id))

    # Enviamos a la sala del emisor (para que vea su propio mensaje en tiempo real)
    emit('nuevo_mensaje', {
        'msg': mensaje,
        'de': emisor_nombre,
        'de_id': emisor_id
    }, room=str(emisor_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
                
        conn = sqlite3.connect('marketplace.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Buscamos al usuario por email
        cursor.execute("SELECT * FROM usuarios WHERE email = %", (email,))
        user = cursor.fetchone()
        conn.close()
        
        # 1. Validamos si el usuario existe
        if user:
            # 2. Validamos la contraseña
            if check_password_hash(user['password'], password):

                if user['estado'] != 'activo':
                   flash("⚠️ Tu cuenta está suspendida. Contacta al administrador.")
                   return redirect('/login')
                     
                # Guardamos datos clave en la sesión
                session['user_id'] = user['id']
                session['user_nombre'] = user['nombre']
                session['user_rol'] = user['rol']
            
                flash(f"¡Bienvenido de nuevo, {user['nombre']}!")
            
                # Redirección según el ROL (UX diferenciada)
                if user['rol'] == 'admin':
                    return redirect('/admin')
                elif user['rol'] == 'mype':
                    return redirect('/dashboard_mype')
                return redirect('/') # El cliente vuelve al mapa
            else:
                flash("❌ Contraseña incorrecta.", "warning")
        else:
            flash("❌ El correo electrónico no está registrado.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Has cerrado sesión correctamente")
    return redirect('/')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    conn = sqlite3.connect('marketplace.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        # 1. Captura de datos
        nombre = request.form['nombre']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        rol = request.form['rol']
        barrio_id = request.form.get('barrio_id')
        lat = request.form.get('latitud')
        lng = request.form.get('longitud')
        
        try:
            # 2. Insertar en tabla usuarios (Siempre se ejecuta)
            # NOTA: Asegúrate que 'estado' en DB acepte 'Activo' o cámbialo a 'activo' (minúsculas) según tu lógica de login
            cursor.execute('''
                INSERT INTO usuarios (nombre, email, password, rol, barrio_id, estado, latitud, longitud) 
                VALUES (%, %, %, %, %, 'activo', %, %)
            ''', (nombre, email, password, rol, barrio_id, lat, lng))
            
            usuario_id = cursor.lastrowid

            # 3. Si es MYPE, crear su perfil comercial
            if rol == 'mype':
                nombre_comercial = request.form.get('nombre_comercial')
                categoria_id = request.form.get('categoria_id')
                
                # Eliminamos lat/lng de aquí porque ya se guardaron en la tabla 'usuarios'
                cursor.execute('''
                    INSERT INTO perfiles_mype (usuario_id, nombre_comercial, categoria_id) 
                    VALUES (%, %, %)
                ''', (usuario_id, nombre_comercial, categoria_id))
            
            # 4. COMMIT FUERA DEL IF (Vital para que guarde tanto clientes como mypes)
            conn.commit()
            flash("Registro exitoso. ¡Bienvenido al Marketplace!", "success")
            return redirect('/login')

        except Exception as e:
            conn.rollback()
            print(f"Error detectado: {e}") # Esto te ayudará a ver el error real en la terminal
            flash(f"Error: Datos incompletos o el correo ya existe.", "danger")
            return redirect('/registro')
        finally:
            conn.close()

    # Lógica GET
    cursor.execute("SELECT * FROM maestro_barrios")
    barrios = cursor.fetchall()
    cursor.execute("SELECT * FROM maestro_categorias")
    categorias = cursor.fetchall()
    conn.close()
    
    return render_template('registro.html', barrios=barrios, categorias=categorias)

# Agregamos una ruta básica para evitar errores si vas a /
@app.route('/')
def home():
    # Renderizamos la plantilla que contendrá el mapa
    return render_template('index.html')

@app.route('/api/mypes')
def api_mypes():
    conn = sqlite3.connect('marketplace.db')
    conn.row_factory = sqlite3.Row # Esto nos permite acceder por nombre de columna
    cursor = conn.cursor()
    
    # Traemos las MYPES unidas a sus nombres comerciales y categorías
    query = '''
        SELECT u.latitud, u.longitud, p.nombre_comercial, c.nombre as categoria, p.id AS mype_id
        FROM usuarios u
        JOIN perfiles_mype p ON u.id = p.usuario_id
        JOIN maestro_categorias c ON p.categoria_id = c.id
        WHERE u.rol = 'mype'
    '''
    cursor.execute(query)
    mypes_rows = cursor.fetchall()
    
    resultado = []
    for row in mypes_rows:
        # Convertimos la fila a un diccionario real de Python
        mype_dict = dict(row)
        
        # Por cada MYPE, buscamos sus últimos 3 productos/ofertas
        cursor.execute("SELECT nombre, precio FROM productos WHERE mype_id = % LIMIT 3", (mype_dict['mype_id'],))
        mype_dict['productos'] = [dict(p) for p in cursor.fetchall()]
        
        resultado.append(mype_dict)
        
    conn.close()
    return jsonify(resultado) # Usa jsonify de Flask para asegurar el formato correcto

@app.route('/dashboard_mype')
@login_required
def dashboard_mype():
    # 1. Validación de seguridad
    if session.get('user_rol') != 'mype':
        flash("Acceso denegado: Esta área es solo para negocios.")
        return redirect('/')
    
# 2. Conexión y consulta (TODO esto debe estar indentado dentro de la función)
    conn = sqlite3.connect('marketplace.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:    
    # Obtener los datos de la MYPE vinculada al usuario logueado
        cursor.execute("SELECT id, nombre_comercial FROM perfiles_mype WHERE usuario_id = %", (session['user_id'],))
        mype = cursor.fetchone()
        
        if mype:
            # Obtener sus productos usando el mype['id'] que acabamos de encontrar
            cursor.execute("SELECT * FROM productos WHERE mype_id = % ORDER BY fecha_creacion DESC", (mype['id'],))
            productos = cursor.fetchall()
        else:
            productos = []
            flash("Perfil de MYPE no encontrado.")
            
    except Exception as e:
        flash(f"Error al cargar productos: {e}")
        productos = []
        mype = None
    finally:
        conn.close()
    
    # 3. Renderizado único al final con todos los datos
    return render_template('dashboard_mype.html', mype=mype, productos=productos)

@app.route('/agregar_producto', methods=['POST'])
@login_required
def agregar_producto():
    nombre = request.form['nombre']
    descripcion = request.form['descripcion']
    precio = request.form['precio']
    
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()
    
    # Buscamos el ID de la MYPE del usuario actual
    cursor.execute("SELECT id FROM perfiles_mype WHERE usuario_id = %", (session['user_id'],))
    mype_id = cursor.fetchone()[0]
    
    cursor.execute('''
        INSERT INTO productos (mype_id, nombre, descripcion, precio) 
        VALUES (%, %, %, %)''', (mype_id, nombre, descripcion, precio))
    
    conn.commit()
    conn.close()
    flash("✅ Producto publicado con éxito")
    return redirect('/dashboard_mype')

#Lógica del Admin
@app.route('/admin')
@login_required
def admin_panel():
    # Seguridad: Solo el admin entra aquí
    if session.get('user_rol') != 'admin': 
        return redirect('/')
    # flash("Acceso restringido.")
            
    conn = sqlite3.connect('marketplace.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Usuarios con su barrio (JOIN para la tabla principal de usuarios)
    cursor.execute('''
        SELECT u.id, u.nombre, u.email, u.rol, u.estado, u.fecha_registro, b.nombre as nombre_barrio
        FROM usuarios u
        LEFT JOIN maestro_barrios b ON u.barrio_id = b.id
    ''')
    usuarios = cursor.fetchall()

    # En la función admin_panel de app.py
    cursor.execute('''
        SELECT b.id, b.nombre, COUNT(u.id) as total_usuarios
        FROM maestro_barrios b
        LEFT JOIN usuarios u ON b.id = u.barrio_id
        GROUP BY b.id
    ''')
    barrios = cursor.fetchall()

    # --- INDICADORES (KPIs) ---
    cursor.execute("SELECT count(*) as total FROM usuarios WHERE rol='mype'")
    total_mypes = cursor.fetchone()['total']
    
    cursor.execute("SELECT count(*) as total FROM usuarios WHERE rol='cliente'")
    total_clientes = cursor.fetchone()['total']
    
    cursor.execute("SELECT count(*) as total FROM productos")
    total_productos = cursor.fetchone()['total']

    # --- LISTADOS ---
    # Usuarios registrados
    # cursor.execute("SELECT id, nombre, email, rol, estado FROM usuarios")
    # usuarios = cursor.fetchall()
    
    # Categorías actuales
    cursor.execute("SELECT * FROM maestro_categorias")
    categorias = cursor.fetchall()
     
    conn.close()
    return render_template('admin.html', 
                           mypes=total_mypes, 
                           clientes=total_clientes, 
                           productos=total_productos,
                           usuarios=usuarios,
                           categorias=categorias,
                           barrios=barrios
                           )

@app.route('/admin/agregar_categoria', methods=['POST'])
@login_required
def agregar_categoria():
    if session.get('user_rol') == 'admin':
        nombre = request.form['nombre_categoria']
        conn = sqlite3.connect('marketplace.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO maestro_categorias (nombre) VALUES (%)", (nombre,))
        conn.commit()
        conn.close()
        flash("Categoría añadida con éxito")
    return redirect('/admin')

# Nueva ruta para eliminar categorías
@app.route('/admin/eliminar_categoria/<int:id>')
@login_required
def eliminar_categoria(id):
    if session.get('user_rol') == 'admin':
        conn = sqlite3.connect('marketplace.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM maestro_categorias WHERE id = %", (id,))
        conn.commit()
        conn.close()
        flash("Categoría eliminada.")
    return redirect('/admin')

@app.route('/admin/cambiar_estado/<int:usuario_id>/<nuevo_estado>')
@login_required
def cambiar_estado(usuario_id, nuevo_estado):
    if session.get('user_rol') != 'admin':
        return redirect('/')
    
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET estado = % WHERE id = %", (nuevo_estado, usuario_id))
    conn.commit()
    conn.close()
    
    flash(f"Usuario actualizado a: {nuevo_estado}")
    return redirect('/admin')

# --- GESTIÓN DE BARRIOS EN ADMIN ---

@app.route('/admin/agregar_barrio', methods=['POST'])
@login_required
def agregar_barrio():
    if session.get('user_rol') == 'admin':
        nombre = request.form.get('nombre_barrio')
        if nombre:
            conn = sqlite3.connect('marketplace.db')
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO maestro_barrios (nombre) VALUES (%)", (nombre,))
                conn.commit()
                flash(f"Barrio '{nombre}' agregado correctamente.", "success")
            except sqlite3.IntegrityError:
                flash("Ese barrio ya existe.", "warning")
            finally:
                conn.close()
    return redirect('/admin')

@app.route('/admin/eliminar_barrio/<int:id>')
@login_required
def eliminar_barrio(id):
    if session.get('user_rol') == 'admin':
        conn = sqlite3.connect('marketplace.db')
        cursor = conn.cursor()
        try:
            # Verificamos si hay usuarios en este barrio antes de borrar
            cursor.execute("SELECT COUNT(*) FROM usuarios WHERE barrio_id = %", (id,))
            count = cursor.fetchone()[0]
            
            if count > 0:
                flash(f"No se puede eliminar: hay {count} usuarios registrados en este barrio.", "danger")
            else:
                cursor.execute("DELETE FROM maestro_barrios WHERE id = %", (id,))
                conn.commit()
                flash("Barrio eliminado con éxito.", "success")
        except Exception as e:
            flash(f"Error al eliminar: {e}", "danger")
        finally:
            conn.close()
    return redirect('/admin')

# ---------------------------------------------------------
# EVENTOS DE SOCKET.IO (Lógica del Chat)
# ---------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    print(f"✅ Usuario conectado: {session.get('user_nombre')}")

@socketio.on('enviar_mensaje')
def handle_message(data):
    """
    data contiene: { 'receptor_id': X, 'mensaje': 'hola', 'emisor_nombre': 'Pepe' }
    """
    mensaje = data['mensaje']
    receptor_id = data['receptor_id']
    emisor_id = session.get('user_id')
    emisor_nombre = session.get('user_nombre')

    # Guardar en la base de datos (Opcional por ahora, pero recomendado)
    # conn = sqlite3.connect('marketplace.db')
    # ... código para INSERT INTO mensajes ...
    
    # Emitir el mensaje al receptor
    emit('nuevo_mensaje', {
        'msg': mensaje,
        'de': emisor_nombre,
        'de_id': emisor_id
    }, broadcast=True) # Por ahora lo enviamos a todos para probar, luego lo filtramos por salas

@app.route('/chat/<int:receptor_id>')
@login_required
def chat_personal(receptor_id):
    emisor_id = session.get('user_id')
    
    # 1. Obtener datos del receptor para mostrar su nombre en el chat
    conn = sqlite3.connect('marketplace.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT nombre FROM usuarios WHERE id = %", (receptor_id,))
    receptor = cursor.fetchone()
    
    # 2. Cargar historial de mensajes entre estos dos usuarios
    cursor.execute('''
        SELECT m.*, u.nombre as emisor_nombre 
        FROM mensajes m
        JOIN usuarios u ON m.emisor_id = u.id
        WHERE (emisor_id = % AND receptor_id = %) 
           OR (emisor_id = % AND receptor_id = %)
        ORDER BY fecha ASC
    ''', (emisor_id, receptor_id, receptor_id, emisor_id))
    
    historial = cursor.fetchall()
    conn.close()

    return render_template('chat.html', receptor=receptor, receptor_id=receptor_id, historial=historial)

if __name__ == '__main__':
    #app.run(debug=True)
    socketio.run(app, debug=True)