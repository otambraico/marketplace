from flask import Flask, render_template, request, redirect, flash, session, jsonify
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
import sqlite3
import json
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_candidata = request.form['password']
        
        conn = sqlite3.connect('marketplace.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Buscamos al usuario por email
        cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
        usuario = cursor.fetchone()
        conn.close()
        
        if usuario and check_password_hash(usuario['password'], password_candidata):
            # Guardamos datos clave en la sesión
            session['user_id'] = usuario['id']
            session['user_nombre'] = usuario['nombre']
            session['user_rol'] = usuario['rol']
            
            flash(f"¡Bienvenido de nuevo, {usuario['nombre']}!")
            
            # Redirección según el ROL (UX diferenciada)
            if usuario['rol'] == 'mype':
                return redirect('/dashboard_mype')
            elif usuario['rol'] == 'admin':
                return redirect('/admin')
            else:
                return redirect('/') # El cliente vuelve al mapa
        else:
            flash("Correo o contraseña incorrectos")
            return redirect('/login')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Has cerrado sesión correctamente")
    return redirect('/')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM maestro_categorias")
        cats = cursor.fetchall()
        cursor.execute("SELECT * FROM maestro_barrios")
        brs = cursor.fetchall()
        conn.close()
        return render_template('registro.html', categorias=cats, barrios=brs)

    if request.method == 'POST':
        # Datos básicos
        nombre = request.form['nombre']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        rol = request.form['rol']
        lat = request.form.get('latitud') # Usamos .get por seguridad
        lng = request.form.get('longitud')
        
        try:
            # 1. Insertar en tabla usuarios
            cursor.execute('''
                INSERT INTO usuarios (nombre, email, password, rol, latitud, longitud) 
                VALUES (?, ?, ?, ?, ?, ?)''', (nombre, email, password, rol, lat, lng))
            
            # 2. Si es MYPE, crear su perfil comercial usando IDs de tablas maestras
            if rol == 'mype':
                usuario_id = cursor.lastrowid
                nombre_comercial = request.form['nombre_comercial']
                # Cambiamos 'barrio' por 'barrio_id' y capturamos 'categoria_id'
                barrio_id = request.form['barrio_id']
                categoria_id = request.form['categoria_id']
                
                cursor.execute('''
                    INSERT INTO perfiles_mype (usuario_id, nombre_comercial, barrio_id, categoria_id) 
                    VALUES (?, ?, ?, ?)''', (usuario_id, nombre_comercial, barrio_id, categoria_id))
            
            conn.commit()
            flash("Registro exitoso. ¡Bienvenido al Marketplace vecinal!")
            return redirect('/registro') # El redirect es clave para limpiar el formulario
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}")
            return redirect('/registro')
        finally:
            conn.close()

    # Si llegamos aquí, es un GET (carga inicial o después del redirect)
    cursor.execute("SELECT * FROM maestro_categorias")
    cats = cursor.fetchall()
    cursor.execute("SELECT * FROM maestro_barrios")
    brs = cursor.fetchall()
    conn.close()
    
    return render_template('registro.html', categorias=cats, barrios=brs)

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
        cursor.execute("SELECT nombre, precio FROM productos WHERE mype_id = ? LIMIT 3", (mype_dict['mype_id'],))
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
        cursor.execute("SELECT id, nombre_comercial FROM perfiles_mype WHERE usuario_id = ?", (session['user_id'],))
        mype = cursor.fetchone()
        
        if mype:
            # Obtener sus productos usando el mype['id'] que acabamos de encontrar
            cursor.execute("SELECT * FROM productos WHERE mype_id = ? ORDER BY fecha_creacion DESC", (mype['id'],))
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
    cursor.execute("SELECT id FROM perfiles_mype WHERE usuario_id = ?", (session['user_id'],))
    mype_id = cursor.fetchone()[0]
    
    cursor.execute('''
        INSERT INTO productos (mype_id, nombre, descripcion, precio) 
        VALUES (?, ?, ?, ?)''', (mype_id, nombre, descripcion, precio))
    
    conn.commit()
    conn.close()
    flash("✅ Producto publicado con éxito")
    return redirect('/dashboard_mype')

# Ruta en app.py para el Admin
@app.route('/admin')
@login_required
def admin_panel():
    if session.get('user_rol') != 'admin':
        return redirect('/')
    
    conn = sqlite3.connect('marketplace.db')
    cursor = conn.cursor()
    
    # Estadísticas rápidas
    cursor.execute("SELECT count(*) FROM usuarios WHERE rol='mype'")
    total_mypes = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM usuarios WHERE rol='cliente'")
    total_clientes = cursor.fetchone()[0]
    
    # Listado de categorías para gestión
    cursor.execute("SELECT * FROM maestro_categorias")
    categorias = cursor.fetchall()
    
    conn.close()
    return render_template('admin.html', mypes=total_mypes, clientes=total_clientes, categorias=categorias)

#Lógica del Admin
@app.route('/admin')
@login_required
def admin_panel():
    # Seguridad: Solo el admin entra aquí
    if session.get('user_rol') != 'admin':
        flash("Acceso restringido.")
        return redirect('/')
    
    conn = sqlite3.connect('marketplace.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # --- INDICADORES (KPIs) ---
    cursor.execute("SELECT count(*) as total FROM usuarios WHERE rol='mype'")
    total_mypes = cursor.fetchone()['total']
    
    cursor.execute("SELECT count(*) as total FROM usuarios WHERE rol='cliente'")
    total_clientes = cursor.fetchone()['total']
    
    cursor.execute("SELECT count(*) as total FROM productos")
    total_productos = cursor.fetchone()['total']

    # --- LISTADOS ---
    # Usuarios registrados
    cursor.execute("SELECT id, nombre, email, rol, fecha_registro FROM usuarios ORDER BY fecha_registro DESC")
    usuarios = cursor.fetchall()
    
    # Categorías actuales
    cursor.execute("SELECT * FROM maestro_categorias")
    categorias = cursor.fetchall()
    
    conn.close()
    return render_template('admin.html', 
                           mypes=total_mypes, 
                           clientes=total_clientes, 
                           productos=total_productos,
                           usuarios=usuarios,
                           categorias=categorias)

if __name__ == '__main__':
    app.run(debug=True)