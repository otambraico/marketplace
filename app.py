import eventlet
eventlet.monkey_patch()
from datetime import timedelta

# Recién ahora puedes importar el resto
import os
from flask import Flask, render_template, request, redirect, flash, session, jsonify
from flask_socketio import SocketIO, emit, join_room

from flask import Flask, render_template, request, redirect, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from functools import wraps
from psycopg2.extras import RealDictCursor # Para acceder por nombre de columna [cite: 12, 20]
from database import init_db # [cite: 1] Asegúrate de importar ambos

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_segura_dev')

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'una_clave_muy_segura')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
# CRÍTICO para Render y WebSockets:
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

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
# Usamos eventlet o gevent para mejor compatibilidad con WebSockets
socketio = SocketIO(app, 
                    cors_allowed_origins="*", 
                    async_mode='eventlet',
                    manage_session=True,
                    ping_timeout=120,    # Aumentamos a 2 min para evitar cierres abruptos
                    ping_interval=25,
                    always_connect=True) # Fuerza la persistencia de la conexión

@socketio.on('join')
def on_join(data):
    """SRP: Conectar al usuario a su canal privado"""
    user_id = session.get('user_id')
    if user_id:
        room = f"user_{user_id}"
        join_room(room) # DESCOMENTAR ESTO
        print(f"📡 Usuario {user_id} unido a sala: {room}")

@socketio.on('enviar_mensaje')
def handle_mensaje(data):
    # Obtenemos los datos con precaución
    emisor_id = session.get('user_id')
    receptor_id = data.get('receptor_id')
    contenido = data.get('mensaje', '').strip()

    if not emisor_id:
        print("❌ Error: emisor_id no encontrado en sesión")
        return

    print(f"📩 Procesando: De {emisor_id} para {receptor_id}")

    if receptor_id and contenido:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Usamos RETURNING para confirmar que la DB lo aceptó
            cursor.execute(
                "INSERT INTO mensajes (emisor_id, receptor_id, contenido, leido) VALUES (%s, %s, %s, FALSE) RETURNING id",
                (emisor_id, receptor_id, contenido)
            )
            nuevo_id = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            
            payload = {
                'emisor_id': emisor_id,
                'receptor_id': receptor_id,
                'mensaje': contenido,
                'fecha': 'Ahora'
            }

            # Emitir a las salas
            emit('nuevo_mensaje', payload, room=f"user_{receptor_id}")
            emit('nuevo_mensaje', payload, room=f"user_{emisor_id}")
            print(f"✅ Éxito: Mensaje {nuevo_id} guardado y emitido")

        except Exception as e:
            print(f"🔥 Error crítico en DB: {e}")

@app.route('/mensajes')
@login_required
def bandeja_entrada():
    user_id = session.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor()

    # Query avanzada: Obtiene el último mensaje de cada conversación y cuenta no leídos
    query = """
    SELECT DISTINCT ON (sub.contacto_id)
        sub.contacto_id,
        u.nombre,
        sub.contenido,
        sub.fecha,
        (SELECT COUNT(*) FROM mensajes WHERE receptor_id = %s AND emisor_id = sub.contacto_id AND leido = FALSE) as pendientes
    FROM (
        SELECT 
            CASE WHEN emisor_id = %s THEN receptor_id ELSE emisor_id END as contacto_id,
            contenido, fecha
        FROM mensajes
        WHERE emisor_id = %s OR receptor_id = %s
        ORDER BY fecha DESC
    ) sub
    JOIN usuarios u ON u.id = sub.contacto_id
    ORDER BY sub.contacto_id, sub.fecha DESC
    """
    cursor.execute(query, (user_id, user_id, user_id, user_id))
    conversaciones = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('bandeja.html', conversaciones=conversaciones)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect('/dashboard_mype' if session.get('rol') == 'mype' else '/')

    if request.method == 'POST':
        # .strip() elimina espacios accidentales al inicio o final del correo
        email = request.form.get('email', '').strip() 
        password = request.form.get('password', '')

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, nombre, rol, password FROM usuarios WHERE email = %s", (email,))
        user = cursor.fetchone()

        # RAYOS X: Esto aparecerá en los logs de Render
        print(f"🔍 DEBUG LOGIN - Correo ingresado: '{email}'")
        print(f"🔍 DEBUG LOGIN - Usuario en DB: {user}")

        if user:
            # Validamos si es Diccionario o Tupla para evitar error 500
            db_password = user['password'] if isinstance(user, dict) else user[3]
            db_rol = user['rol'] if isinstance(user, dict) else user[2]
            db_id = user['id'] if isinstance(user, dict) else user[0]
            db_nombre = user['nombre'] if isinstance(user, dict) else user[1]

            if check_password_hash(db_password, password):
                session['user_id'] = db_id
                session['nombre'] = db_nombre
                session['rol'] = db_rol

                if db_rol == 'mype':
                    cursor.execute("SELECT id FROM perfiles_mype WHERE usuario_id = %s", (db_id,))
                    perfil = cursor.fetchone()
                    
                    if perfil:
                        session['mype_id'] = perfil['id'] if isinstance(perfil, dict) else perfil[0]
                    else:
                        session['mype_id'] = None 
                    
                    print(f"✅ ÉXITO - MYPE logueada. ID Sesión: {session['user_id']}, MYPE ID: {session['mype_id']}")
                    cursor.close()
                    conn.close()
                    return redirect('/dashboard_mype')
                
                # Cliente
                print(f"✅ ÉXITO - Cliente logueado. ID Sesión: {session['user_id']}")
                cursor.close()
                conn.close()
                return redirect('/')
            else:
                print("❌ ERROR - La contraseña no coincide con la BD.")
                flash("Correo o contraseña incorrectos.", "danger")
        else:
            print("❌ ERROR - El correo no existe en la BD.")
            flash("Correo o contraseña incorrectos.", "danger")
            
        cursor.close()
        conn.close()

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
        SELECT u.id as mype_id, p.id as perfil_id, p.nombre_comercial, 
               u.latitud, u.longitud, c.nombre as categoria
        FROM usuarios u
        JOIN perfiles_mype p ON u.id = p.usuario_id
        JOIN maestro_categorias c ON p.categoria_id = c.id
        WHERE u.estado = 'activo'
    '''
    cursor.execute(query)
    mypes = cursor.fetchall()
    
    resultado = []
    for mype in mypes:
        # Convertimos la fila a un diccionario real de Python
        mype_dict = dict(mype)
        
        # 2. Por cada MYPE, buscamos sus productos
        cursor.execute(
            "SELECT nombre, precio FROM productos WHERE mype_id = %s", 
            (mype_dict['perfil_id'],)
        )
        # Agregamos la lista de productos al diccionario de la MYPE
        mype_dict['productos'] = cursor.fetchall()
        
        resultado.append(mype_dict)
        
    cursor.close()
    conn.close()
    return jsonify(resultado) # Usa jsonify de Flask para asegurar el formato correcto

@app.route('/dashboard_mype')
@login_required
def dashboard_mype():
    user_id = session.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Obtener datos de la MYPE (Responsabilidad: Perfil)
    cursor.execute("SELECT * FROM perfiles_mype WHERE usuario_id = %s", (user_id,))
    mype = cursor.fetchone()
    
    if not mype:
        flash("Perfil MYPE no encontrado.", "warning")
        return redirect('/')

    # 2. Obtener productos (Responsabilidad: Inventario)
    cursor.execute("SELECT * FROM productos WHERE mype_id = %s ORDER BY id DESC", (mype['id'],))
    productos = cursor.fetchall()

    # 3. CONTAR MENSAJES PENDIENTES (Responsabilidad: Notificaciones)
    # Esta es la variable que falta en tu log
    cursor.execute("SELECT COUNT(*) as total FROM mensajes WHERE receptor_id = %s AND leido = FALSE", (user_id,))
    res_pendientes = cursor.fetchone()
    mensajes_pendientes = res_pendientes['total'] if res_pendientes else 0
    
    cursor.close()
    conn.close()
    
    # IMPORTANTE: Enviamos 'mensajes_pendientes' a la plantilla
    return render_template('dashboard_mype.html', 
                           mype=mype, 
                           productos=productos, 
                           mensajes_pendientes=mensajes_pendientes)

# --- FUNCIONALIDAD: NUEVO PRODUCTO ---
@app.route('/productos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        precio = request.form.get('precio')
        descripcion = request.form.get('descripcion')
        foto_url = request.form.get('foto_url') # Alineado a la DB
        
        # OJO: Según tu DB, la relación es con perfiles_mype. 
        # Asegúrate de que session['mype_id'] se guarde en el login.
        mype_id = session.get('mype_id') 

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO productos (mype_id, nombre, descripcion, precio, foto_url)
                VALUES (%s, %s, %s, %s, %s)
            ''', (mype_id, nombre, descripcion, precio, foto_url))
            conn.commit()
            cursor.close()
            conn.close()
            flash("Producto publicado con éxito", "success")
            return redirect('/dashboard_mype')
        except Exception as e:
            print(f"Error DB al crear producto: {e}")
            flash("Error al guardar el producto", "danger")

    return render_template('nuevo_producto.html')


# --- FUNCIONALIDAD: ELIMINAR PRODUCTO ---
@app.route('/productos/eliminar/<int:producto_id>', methods=['POST'])
@login_required
def eliminar_producto(producto_id):
    mype_id = session.get('mype_id')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Seguridad: Solo borra si el producto_id coincide Y pertenece a esta MYPE
        cursor.execute("DELETE FROM productos WHERE id = %s AND mype_id = %s", (producto_id, mype_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Producto eliminado correctamente.", "success")
    except Exception as e:
        print(f"Error DB al eliminar: {e}")
        flash("Hubo un error al eliminar el producto.", "danger")
        
    return redirect('/dashboard_mype')

# --- FUNCIONALIDAD: AJUSTES (PERFIL MYPE) ---
@app.route('/perfil_mype/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil_mype():
    mype_id = session.get('mype_id')
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        # Aquí puedes añadir rubro, contacto, etc.
        
        cursor.execute('''
            UPDATE mypes SET nombre = %s, descripcion = %s
            WHERE id = %s
        ''', (nombre, descripcion, mype_id))
        conn.commit()
        flash("Perfil actualizado", "success")
        return redirect('/dashboard_mype')

    cursor.execute("SELECT * FROM mypes WHERE id = %s", (mype_id,))
    mype = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('editar_mype.html', mype=mype)

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

#Chat

@app.route('/chat/<int:receptor_id>')
@login_required
def chat_personal(receptor_id):
    user_id = session.get('user_id') # Esta es tu variable local
    conn = get_db_connection()
    cursor = conn.cursor()
       
    # CORRECCIÓN 1: Incluir 'id' en el SELECT para que el JS lo reciba
    cursor.execute("SELECT id, nombre FROM usuarios WHERE id = %s", (receptor_id,))
    contacto = cursor.fetchone()
    
    if not contacto:
        cursor.close()
        conn.close()
        flash("El usuario no existe.", "warning")
        return redirect('/')

    # CORRECCIÓN 2: Usar 'user_id' en lugar de 'emisor_id' para coincidir con la sesión
    cursor.execute('''
        SELECT * FROM mensajes 
        WHERE (emisor_id = %s AND receptor_id = %s) 
           OR (emisor_id = %s AND receptor_id = %s)
        ORDER BY fecha ASC
    ''', (user_id, receptor_id, receptor_id, user_id))
    historial = cursor.fetchall()
    
    cursor.close()
    conn.close()

    # Ahora 'contacto' contiene {'id': X, 'nombre': '...'} y el JS funcionará
    return render_template('chat.html', contacto=contacto, historial=historial)

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