import eventlet
eventlet.monkey_patch()
from datetime import timedelta

# Recién ahora puedes importar el resto
import os
import cloudinary
import cloudinary.uploader

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

# ==========================================
# Configuración de Cloudinary (Reemplaza con tus datos del Dashboard)
# En producción, es ideal que esto esté en variables de entorno (os.environ.get)
# ==========================================

cloudinary.config( 
  cloud_name = "dw1y1tkdx", 
  api_key = "412297355718535", 
  api_secret = "yM9PBOYpNZmKYzidn9-FKtJKV5g" 
)

# ==========================================
# --- 1. DEFINIR LA CONEXIÓN PRIMERO ---
# ==========================================

def get_db_connection():
    url = os.environ.get('DATABASE_URL')
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1) # [cite: 16]
    return psycopg2.connect(url, cursor_factory=RealDictCursor) # [cite: 1, 16]

# ==========================================
# PROCESADOR DE CONTEXTO GLOBAL (Notificaciones)
# ==========================================
@app.context_processor
def inject_notificaciones():
    pendientes = 0
    # Solo buscamos si hay un usuario logueado
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Contamos los mensajes no leídos donde este usuario es el receptor
            cursor.execute(
                "SELECT COUNT(*) as total FROM mensajes WHERE receptor_id = %s AND leido = FALSE",
                (session['user_id'],)
            )
            res = cursor.fetchone()
            pendientes = res['total'] if res else 0
            
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error cargando notificaciones globales: {e}")
            
    # Devuelve un diccionario que estará disponible en TODOS los HTML
    return dict(mensajes_pendientes_global=pendientes)

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

@socketio.on('marcar_leido')
def handle_marcar_leido(data):
    user_id = session.get('user_id') # Yo, el que está leyendo
    emisor_id = data.get('emisor_id') # El que me mandó el mensaje
    
    if user_id and emisor_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE mensajes SET leido = TRUE WHERE emisor_id = %s AND receptor_id = %s AND leido = FALSE",
                (emisor_id, user_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            print(f"👀 Mensajes de {emisor_id} marcados como leídos por {user_id} en tiempo real.")
        except Exception as e:
            print(f"❌ Error DB al marcar leído en Socket: {e}")

#===============================================
#PostGIS / SQL
#===============================================

@app.route('/api/tiendas_cercanas')
def tiendas_cercanas():
    # 1. Obtener coordenadas del cliente y rango desde la petición HTTP GET
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    radio_km = request.args.get('radio', default=2, type=float) # 2km por defecto (Barrial)

    # Validar que existan coordenadas
    if not lat or not lng:
        return jsonify({"error": "Ubicación (lat, lng) requerida"}), 400

    try:
        conn = get_db_connection()
        # Usamos RealDictCursor para que el resultado se convierta fácilmente a JSON
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 2. Consulta SQL PostGIS Avanzada
        # - Calcula la distancia en kilómetros.
        # - Agrupa los productos en un JSON (para la lista del mapa).
        # - Filtra solo las MYPES activas que tengan ubicación registrada.
        query = '''
            SELECT 
                u.id, 
                u.latitud, 
                u.longitud,
                pm.id as mype_id,
                pm.nombre_comercial,
                -- Cálculo de distancia (Haversine) a través de PostGIS (en km)
                ST_Distance(
                    ST_SetSRID(ST_MakePoint(u.longitud, u.latitud), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                ) / 1000 as distancia_km,
                -- Empaquetamos los productos en un Array JSON
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', p.id,
                            'nombre', p.nombre,
                            'precio', p.precio
                            'foto_url', p.foto_url
                        )
                    ) FILTER (WHERE p.id IS NOT NULL), '[]'
                ) as productos
            FROM usuarios u
            JOIN perfiles_mype pm ON u.id = pm.usuario_id
            LEFT JOIN productos p ON pm.id = p.mype_id
            WHERE u.rol = 'mype' 
              AND u.estado = 'activo'
              AND u.latitud IS NOT NULL 
              AND u.longitud IS NOT NULL
              -- Filtro de proximidad usando el radio especificado
              AND ST_DWithin(
                  ST_SetSRID(ST_MakePoint(u.longitud, u.latitud), 4326)::geography,
                  ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                  %s * 1000
              )
            -- Agrupamos para poder usar json_agg
            GROUP BY u.id, pm.id
            ORDER BY distancia_km ASC;
        '''
        
        # OJO: PostGIS usa el orden (Longitud, Latitud) para ST_MakePoint
        cursor.execute(query, (lng, lat, lng, lat, radio_km))
        tiendas = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify(tiendas)
        
    except Exception as e:
        print(f"❌ Error en motor geográfico: {e}")
        # Retornamos una lista vacía para no romper el mapa en caso de error SQL
        return jsonify([]), 500

# ==========================================
#Bandeja del CHAT
# ==========================================
@app.route('/bandeja')
@login_required
def bandeja():
    user_id = session.get('user_id')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # SQL AVANZADO: Agrupa por conversación y trae el último mensaje
        query = '''
            WITH UltimosMensajes AS (
                SELECT 
                    CASE 
                        WHEN emisor_id = %s THEN receptor_id 
                        ELSE emisor_id 
                    END AS contacto_id,
                    MAX(fecha) as ultima_fecha
                FROM mensajes
                WHERE emisor_id = %s OR receptor_id = %s
                GROUP BY 
                    CASE 
                        WHEN emisor_id = %s THEN receptor_id 
                        ELSE emisor_id 
                    END
            )
            SELECT 
                um.contacto_id,
                u.nombre as contacto_nombre,
                u.rol as contacto_rol,
                pm.nombre_comercial as mype_nombre,
                m.contenido as ultimo_mensaje,
                m.fecha as fecha_mensaje,
                m.leido,
                m.emisor_id,
                (SELECT COUNT(*) FROM mensajes 
                 WHERE emisor_id = um.contacto_id AND receptor_id = %s AND leido = FALSE) as no_leidos
            FROM UltimosMensajes um
            JOIN mensajes m ON (
                (m.emisor_id = %s AND m.receptor_id = um.contacto_id) OR 
                (m.emisor_id = um.contacto_id AND m.receptor_id = %s)
            ) AND m.fecha = um.ultima_fecha
            JOIN usuarios u ON u.id = um.contacto_id
            LEFT JOIN perfiles_mype pm ON pm.usuario_id = u.id
            ORDER BY m.fecha DESC;
        '''
        
        # Pasamos el user_id las 7 veces que lo requiere la consulta
        cursor.execute(query, (user_id, user_id, user_id, user_id, user_id, user_id, user_id))
        conversaciones = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('bandeja.html', conversaciones=conversaciones)
        
    except Exception as e:
        print(f"Error cargando la bandeja: {e}")
        flash("Hubo un error al cargar tus mensajes.", "danger")
        return redirect('/')

# ==========================================
# LÓGICA DE LOGIN (El Director de Tráfico)
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    # 1. Si ya tiene sesión, redirigir a su panel
    if 'user_id' in session:
        rol = session.get('rol')
        if rol == 'admin':
            return redirect('/admin')
        elif rol == 'mype':
            return redirect('/dashboard_mype')
        elif rol == 'cliente':
            return redirect('/perfil_cliente')
        else:
            return redirect('/')

    # 2. Procesar el formulario
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # Usar RealDictCursor evita errores de índices

        cursor.execute("SELECT id, nombre, rol, password FROM usuarios WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            
            # 3. Guardar Sesión Global
            session['user_id'] = user['id']
            session['nombre'] = user['nombre']
            session['rol'] = user['rol'] # OJO: La clave es 'rol'

            # 4. Enrutamiento Específico
            if user['rol'] == 'admin':
                cursor.close()
                conn.close()
                return redirect('/admin') 

            elif user['rol'] == 'mype':
                cursor.execute("SELECT id FROM perfiles_mype WHERE usuario_id = %s", (user['id'],))
                perfil = cursor.fetchone()
                session['mype_id'] = perfil['id'] if perfil else None
                
                cursor.close()
                conn.close()
                return redirect('/dashboard_mype')

            elif user['rol'] == 'cliente':
                cursor.close()
                conn.close()
                return redirect('/perfil_cliente')
            
        else:
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

# ======================================================
# --- FUNCIONALIDAD: NUEVO PRODUCTO (CON CLOUDINARY) ---
# ======================================================

@app.route('/productos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        precio = request.form.get('precio')
        descripcion = request.form.get('descripcion')
        mype_id = session.get('mype_id') 
        
        # CAMBIO 1: Capturamos el archivo físico, no un texto.
        foto = request.files.get('foto')
        foto_url = None

        try:
            # CAMBIO 2: Si hay foto, la enviamos a Cloudinary
            if foto and foto.filename != '':
                upload_result = cloudinary.uploader.upload(foto, folder="mibarrio_productos")
                foto_url = upload_result.get('secure_url') # Extraemos el enlace de la nube

            # Guardamos en PostgreSQL de forma normal
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
            print(f"Error DB o Cloudinary al crear producto: {e}")
            flash("Error al procesar el producto o la imagen.", "danger")

    return render_template('nuevo_producto.html')

# ======================================================
# --- FUNCIONALIDAD: ELIMINAR PRODUCTO ---
# ======================================================

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

# --- FUNCIONALIDAD: EDITAR PRODUCTO ---
@app.route('/productos/editar/<int:producto_id>', methods=['GET', 'POST'])
@login_required
def editar_producto(producto_id):
    mype_id = session.get('mype_id')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 1. Seguridad: Verificar que el producto existe y pertenece a esta MYPE
    cursor.execute("SELECT * FROM productos WHERE id = %s AND mype_id = %s", (producto_id, mype_id))
    producto = cursor.fetchone()

    if not producto:
        cursor.close()
        conn.close()
        flash("Producto no encontrado o no tienes permisos para editarlo.", "danger")
        return redirect('/dashboard_mype')

    # 2. Procesar el formulario de actualización
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        precio = request.form.get('precio')
        descripcion = request.form.get('descripcion')
        foto_url = request.form.get('foto_url')

        cursor.execute('''
            UPDATE productos 
            SET nombre = %s, precio = %s, descripcion = %s, foto_url = %s
            WHERE id = %s AND mype_id = %s
        ''', (nombre, precio, descripcion, foto_url, producto_id, mype_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Producto actualizado correctamente.", "success")
        return redirect('/dashboard_mype')

    cursor.close()
    conn.close()
    return render_template('editar_producto.html', producto=producto)

# --- FUNCIONALIDAD: AJUSTES (PERFIL MYPE) CORREGIDO ---
@app.route('/perfil_mype/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil_mype():
    mype_id = session.get('mype_id')
    conn = get_db_connection()
    # Usamos RealDictCursor para poder acceder por nombre de columna en el HTML
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) 

    if request.method == 'POST':
        nombre_comercial = request.form.get('nombre_comercial')
        descripcion = request.form.get('descripcion')
        
        # Corrección: Apuntando a la tabla 'perfiles_mype' y columna 'nombre_comercial'
        cursor.execute('''
            UPDATE perfiles_mype SET nombre_comercial = %s, descripcion = %s
            WHERE id = %s
        ''', (nombre_comercial, descripcion, mype_id))
        conn.commit()
        flash("Perfil actualizado con éxito", "success")
        return redirect('/dashboard_mype')

    cursor.execute("SELECT * FROM perfiles_mype WHERE id = %s", (mype_id,))
    mype = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('editar_mype.html', mype=mype)

# ==========================================
# LÓGICA DEL ADMIN (Corregida)
# ==========================================
@app.route('/admin')
@login_required
def admin_panel():
    # Seguridad: Solo el admin entra aquí
    if session.get('rol') != 'admin': 
        flash("Acceso restringido. Área solo para administradores.", "danger")
        return redirect('/')
            
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

# Nueva ruta para agregar categorías
@app.route('/admin/agregar_categoria', methods=['POST'])
@login_required
def agregar_categoria():
    if session.get('rol') == 'admin':
        nombre = request.form['nombre_categoria']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO maestro_categorias (nombre) VALUES (%s)", (nombre,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Categoría añadida con éxito")
    return redirect('/admin')

# --- NUEVA RUTA PARA ELIMINAR CATEGORÍAS (SEGURA) ---
@app.route('/admin/eliminar_categoria/<int:id>', methods=['POST'])
@login_required
def eliminar_categoria(id):
    if session.get('rol') == 'admin':
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM maestro_categorias WHERE id = %s", (id,))
            conn.commit()
            flash("Categoría eliminada con éxito.", "success")
            
        except Exception as e:
            # Si hay un error de Foreign Key, caerá aquí en lugar de dar Error 500
            conn.rollback() 
            print(f"Error al eliminar categoría: {e}")
            flash("No se puede eliminar esta categoría porque hay MYPES que la están usando.", "danger")
            
        finally:
            cursor.close()
            conn.close()
            
    return redirect('/admin')

# Nueva ruta para cambiar estado
@app.route('/admin/cambiar_estado/<int:usuario_id>/<nuevo_estado>')
@login_required
def cambiar_estado(usuario_id, nuevo_estado):
    if session.get('rol') != 'admin':
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
    if session.get('rol') == 'admin':
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

# --- GESTIÓN DE BARRIOS EN ADMIN ---

@app.route('/admin/eliminar_barrio/<int:id>')
@login_required
def eliminar_barrio(id):
    if session.get('rol') == 'admin':
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

# ==========================================
# NUEVO: LÓGICA DEL PERFIL CLIENTE
# ==========================================
@app.route('/perfil_cliente')
@login_required
def perfil_cliente():
    if session.get('rol') != 'cliente':
        return redirect('/')
        
    user_id = session.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # 1. Obtener datos del cliente y su barrio
    cursor.execute('''
        SELECT u.nombre, u.email, u.fecha_registro, b.nombre as barrio_nombre 
        FROM usuarios u 
        LEFT JOIN maestro_barrios b ON u.barrio_id = b.id 
        WHERE u.id = %s
    ''', (user_id,))
    cliente = cursor.fetchone()
    
    # 2. Contar mensajes sin leer (Para que el cliente sepa si la MYPE le respondió)
    cursor.execute("SELECT COUNT(*) as total FROM mensajes WHERE receptor_id = %s AND leido = FALSE", (user_id,))
    res_pendientes = cursor.fetchone()
    mensajes_pendientes = res_pendientes['total'] if res_pendientes else 0
    
    cursor.close()
    conn.close()
    
    return render_template('perfil_cliente.html', cliente=cliente, mensajes_pendientes=mensajes_pendientes)

# ==========================================
#Logica del Chat
# ==========================================
@app.route('/chat/<int:receptor_id>')
@login_required
def chat_personal(receptor_id):
    user_id = session.get('user_id') # Esta es tu variable local
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
       
    # ==========================================
    # 1. ACTUALIZAR MENSAJES A "LEÍDO"
    # Todo lo que la otra persona (receptor_id) me envió a mí (user_id), ya lo vi.
    # ==========================================
    try:
        cursor.execute('''
            UPDATE mensajes 
            SET leido = TRUE 
            WHERE emisor_id = %s AND receptor_id = %s AND leido = FALSE
        ''', (receptor_id, user_id))
        conn.commit()
    except Exception as e:
        print(f"Error al marcar como leído: {e}")
        conn.rollback()

    # 2. Cargar datos del contacto (Asegúrate de incluir el 'id' como corregimos antes)
    cursor.execute("SELECT id, nombre, rol FROM usuarios WHERE id = %s", (receptor_id,))
    contacto = cursor.fetchone()
    
    if not contacto:
        cursor.close()
        conn.close()
        flash("El usuario no existe.", "warning")
        return redirect('/')

    # 3. Cargar historial de mensajes
    cursor.execute('''
        SELECT * FROM mensajes 
        WHERE (emisor_id = %s AND receptor_id = %s) 
           OR (emisor_id = %s AND receptor_id = %s)
        ORDER BY fecha ASC
    ''', (user_id, receptor_id, receptor_id, user_id))
    historial = cursor.fetchall()
    
    cursor.close()
    conn.close()

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