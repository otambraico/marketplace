import eventlet
eventlet.monkey_patch() # DEBE ser la primera línea, antes de cualquier otro import

from flask import Flask, render_template, request, redirect, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
import psycopg2
from functools import wraps
from psycopg2.extras import RealDictCursor # Para acceder por nombre de columna [cite: 12, 20]
import os
from database import init_db # [cite: 1] Asegúrate de importar ambos

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_segura_dev')

# --- 1. DEFINIR LA CONEXIÓN PRIMERO ---
def get_db_connection():
    url = os.environ.get('DATABASE_URL')
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1) # [cite: 16]
    return psycopg2.connect(url, cursor_factory=RealDictCursor) # [cite: 1, 16]
    
# --- 2. RUTA DE EMERGENCIA (Asegúrate de que esté después de get_db_connection) ---
@app.route('/fix_admin')
def fix_admin():
    nueva_pass = generate_password_hash("admin1234")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Actualizamos la contraseña con el hash generado en este entorno
        cursor.execute(
            "UPDATE usuarios SET password = %s WHERE email = 'admin@marketplace.com'", 
            (nueva_pass,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return f"✅ Password de Admin actualizada a 'admin1234'. Hash: {nueva_pass}"
    except Exception as e:
        return f"❌ Error: {e}"

# --- 3. INICIALIZACIÓN DE TABLAS ---
with app.app_context():
    try:
        init_db() # 
        print("✅ DB inicializada")
    except Exception as e:
        print(f"Aviso DB: {e}")

# Configuración de base de datos para Render
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Por favor, inicia sesión primero")
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

# Inicializamos Socket.io
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
    receptor_id = data['receptor_id'] # 
    mensaje = data['mensaje']
    emisor_nombre = session.get('user_nombre')

    # 1. Guardar en PostgreSQL
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO mensajes (emisor_id, receptor_id, contenido) 
        VALUES (%s, %s, %s)
    ''', (emisor_id, receptor_id, mensaje)) # 
    conn.commit()
    cursor.close()
    conn.close()

    # 2. Envío privado por salas (Rooms)
    # Enviamos al receptor [cite: 4]
    emit('nuevo_mensaje', {
        'msg': mensaje,
        'de': emisor_nombre,
        'de_id': emisor_id
    }, room=str(receptor_id))

    # Enviamos al emisor para feedback inmediato [cite: 5]
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
                
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,)) # [cite: 6]
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        # 1. Validamos si el usuario existe
        if user and check_password_hash(user['password'], password):
            # 2. Validamos la contraseña
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
            flash("❌ El correo electrónico o la contraseña no está registrado.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Has cerrado sesión correctamente")
    return redirect('/')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        # 1. Captura de datos
        nombre = request.form['nombre']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        rol = request.form['rol']
        barrio_id = request.form.get('barrio_id')
        barrio_id = int(barrio_id) if barrio_id and barrio_id != "" else None
        lat = request.form.get('latitud')
        lat = float(lat) if lat and lat != "" else None
        lng = request.form.get('longitud')
        lng = float(lng) if lng and lng != "" else None
        
        try:
            # 2. Insertar en tabla usuarios (Siempre se ejecuta)
            # NOTA: Asegúrate que 'estado' en DB acepte 'Activo' o cámbialo a 'activo' (minúsculas) según tu lógica de login
            cursor.execute('''
                INSERT INTO usuarios (nombre, email, password, rol, barrio_id, estado, latitud, longitud) 
                VALUES (%s, %s, %s, %s, %s, 'activo', %s, %s) RETURNING id
            ''', (nombre, email, password, rol, barrio_id, lat, lng))
            
            # En PostgreSQL usamos RETURNING id o fetchone después del insert
            usuario_id = cursor.fetchone()['id']

            # 3. Si es MYPE, crear su perfil comercial
            if rol == 'mype':
                nombre_comercial = request.form.get('nombre_comercial')
                categoria_id = request.form.get('categoria_id')
                
                # Eliminamos lat/lng de aquí porque ya se guardaron en la tabla 'usuarios'
                cursor.execute('''
                    INSERT INTO perfiles_mype (usuario_id, nombre_comercial, categoria_id) 
                    VALUES (%s, %s, %s)
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
            cursor.close()    
            conn.close()

    # Lógica GET
    cursor.execute("SELECT * FROM maestro_barrios")
    barrios = cursor.fetchall()
    cursor.execute("SELECT * FROM maestro_categorias")
    categorias = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('registro.html', barrios=barrios, categorias=categorias)

# Agregamos una ruta básica para evitar errores si vas a /
@app.route('/')
def home():
    # Renderizamos la plantilla que contendrá el mapa
    return render_template('index.html')

@app.route('/api/mypes')
def api_mypes():
    conn = get_db_connection()
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
        cursor.execute("SELECT nombre, precio FROM productos WHERE mype_id = %s LIMIT 3", (mype_dict['mype_id'],))
        mype_dict['productos'] = [dict(p) for p in cursor.fetchall()]
        resultado.append(mype_dict)
        
    cursor.close()
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
    conn = get_db_connection()
    cursor = conn.cursor()

    try:    
    # Obtener los datos de la MYPE vinculada al usuario logueado
        cursor.execute("SELECT id, nombre_comercial FROM perfiles_mype WHERE usuario_id = %s", (session['user_id'],))
        mype = cursor.fetchone()
        
        if mype:
            # Obtener sus productos usando el mype['id'] que acabamos de encontrar
            cursor.execute("SELECT * FROM productos WHERE mype_id = %s ORDER BY fecha_creacion DESC", (mype['id'],))
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
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Buscamos el ID de la MYPE del usuario actual
    cursor.execute("SELECT id FROM perfiles_mype WHERE usuario_id = %s", (session['user_id'],))
    mype_id = cursor.fetchone()[0]
    
    cursor.execute('''
        INSERT INTO productos (mype_id, nombre, descripcion, precio) 
        VALUES (%s, %s, %s, %s)''', (mype_id, nombre, descripcion, precio))
    
    conn.commit()
    cursor.close()
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
            
    conn = get_db_connection()
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
        GROUP BY b.id, b.nombre
    ''')
    barrios = cursor.fetchall()

    # --- INDICADORES (KPIs) ---
    cursor.execute("SELECT count(*) as total FROM usuarios WHERE rol='mype'")
    total_mypes = cursor.fetchone()['total']
    
    cursor.execute("SELECT count(*) as total FROM usuarios WHERE rol='cliente'")
    total_clientes = cursor.fetchone()['total']
    
    cursor.execute("SELECT count(*) as total FROM productos")
    total_productos = cursor.fetchone()['total']

    # Usuarios registrados
    # cursor.execute("SELECT id, nombre, email, rol, estado FROM usuarios")
    # usuarios = cursor.fetchall()
    # Categorías actuales
    cursor.execute("SELECT * FROM maestro_categorias")
    categorias = cursor.fetchall()
     
    cursor.close()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO maestro_categorias (nombre) VALUES (%s)", (nombre,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Categoría añadida con éxito")
    return redirect('/admin')

# Nueva ruta para eliminar categorías
@app.route('/admin/eliminar_categoria/<int:id>')
@login_required
def eliminar_categoria(id):
    if session.get('user_rol') == 'admin':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM maestro_categorias WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Categoría eliminada.")
    return redirect('/admin')

@app.route('/admin/cambiar_estado/<int:usuario_id>/<nuevo_estado>')
@login_required
def cambiar_estado(usuario_id, nuevo_estado):
    if session.get('user_rol') != 'admin':
        return redirect('/')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET estado = %s WHERE id = %s", (nuevo_estado, usuario_id))
    conn.commit()
    cursor.close()
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
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO maestro_barrios (nombre) VALUES (%s)", (nombre,))
                conn.commit()
                flash(f"Barrio '{nombre}' agregado correctamente.", "success")
            except Exception as e: # Captura general o IntegrityError de psycopg2
                conn.rollback()
                flash("Ese barrio ya existe o hubo un error.", "warning")
            finally:
                cursor.close()
                conn.close()
    return redirect('/admin')

@app.route('/admin/eliminar_barrio/<int:id>')
@login_required
def eliminar_barrio(id):
    if session.get('user_rol') == 'admin':
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Verificamos si hay usuarios en este barrio antes de borrar
            cursor.execute("SELECT COUNT(*) FROM usuarios WHERE barrio_id = %s", (id,))
            result = cursor.fetchone()
            count = result['count'] # Acceso por nombre de columna (RealDictCursor)

            
            if count > 0:
                flash(f"No se puede eliminar: hay {count} usuarios registrados en este barrio.", "danger")
            else:
                cursor.execute("DELETE FROM maestro_barrios WHERE id = %s", (id,))
                conn.commit()
                flash("Barrio eliminado con éxito.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Error al eliminar: {e}", "danger")
        finally:
            cursor.close()
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
    if not mensaje or not receptor_id:
        return

    # 1. Guardar en PostgreSQL (Persistencia Real)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO mensajes (emisor_id, receptor_id, contenido) 
            VALUES (%s, %s, %s)
        ''', (emisor_id, receptor_id, mensaje))
        conn.commit()
    except Exception as e:
        print(f"❌ Error al guardar mensaje: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
    
    # 2. Emitir el mensaje de forma PRIVADA
    # Enviamos a la sala del receptor y a la del emisor
    payload = {
        'msg': mensaje,
        'de': emisor_nombre,
        'de_id': emisor_id
    }
    
    emit('nuevo_mensaje', payload, room=str(receptor_id))
    emit('nuevo_mensaje', payload, room=str(emisor_id))

@app.route('/chat/<int:receptor_id>')
@login_required
def chat_personal(receptor_id):
    emisor_id = session.get('user_id')
    
    # 1. Obtener datos del receptor para mostrar su nombre en el chat
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT nombre FROM usuarios WHERE id = %s", (receptor_id,))
    receptor = cursor.fetchone()
    
    if not receptor:
        cursor.close()
        conn.close()
        flash("El usuario no existe.", "warning")
        return redirect('/')

    # 2. Cargar historial de mensajes entre estos dos usuarios
    cursor.execute('''
        SELECT m.*, u.nombre as emisor_nombre 
        FROM mensajes m
        JOIN usuarios u ON m.emisor_id = u.id
        WHERE (m.emisor_id = %s AND m.receptor_id = %s) 
           OR (m.emisor_id = %s AND m.receptor_id = %s)
        ORDER BY m.fecha ASC
    ''', (emisor_id, receptor_id, receptor_id, emisor_id))
    
    historial = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('chat.html', receptor=receptor, receptor_id=receptor_id, historial=historial)

if __name__ == '__main__':
    # 1. Importamos la función de inicialización
    from database import init_db
    
    try:
        # 2. Ejecutamos la creación de tablas antes de iniciar el servidor
        print("🛠️ Verificando tablas en PostgreSQL...")
        init_db()
        print("✅ Tablas listas.")
    except Exception as e:
        print(f"❌ Error al inicializar tablas: {e}")

    # 3. Arrancamos Socket.io
    port = int(os.environ.get('PORT', 10000)) # Render usa el puerto 10000 según tu log
    socketio.run(app, host='0.0.0.0', port=port, debug=False)