from flask import Flask, request, make_response, g
from flask_cors import CORS
from config import Config
import pymysql
from pymysql.cursors import DictCursor
import time

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], "allow_headers": ["*"], "expose_headers": ["*"]}})

# Pool de conexiones global
_db_pool = None

def init_db_pool():
    """Inicializar pool de conexiones MySQL"""
    global _db_pool
    try:
        from DBUtils.PooledDB import PooledDB
        _db_pool = PooledDB(
            creator=pymysql,
            maxconnections=Config.MYSQL_POOL_SIZE,
            mincached=2,
            maxcached=10,
            blocking=True,
            ping=1,  # Verificar conexión antes de usarla
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            port=Config.MYSQL_PORT,
            cursorclass=DictCursor,
            connect_timeout=Config.MYSQL_CONNECT_TIMEOUT,
            read_timeout=Config.MYSQL_READ_TIMEOUT,
            write_timeout=Config.MYSQL_WRITE_TIMEOUT,
            autocommit=False
        )
        print(f"✅ Pool de conexiones inicializado (max: {Config.MYSQL_POOL_SIZE})")
    except ImportError:
        print("⚠️ DBUtils no instalado, usando conexiones simples")
        _db_pool = None

def get_db():
    """Obtener conexión del pool"""
    global _db_pool
    if _db_pool is None:
        init_db_pool()
    
    if _db_pool:
        return _db_pool.connection()
    else:
        # Fallback a conexión simple
        return pymysql.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            port=Config.MYSQL_PORT,
            cursorclass=DictCursor,
            connect_timeout=Config.MYSQL_CONNECT_TIMEOUT,
            read_timeout=Config.MYSQL_READ_TIMEOUT,
            write_timeout=Config.MYSQL_WRITE_TIMEOUT
        )

def init_db():
    """Inicializar la base de datos"""
    init_db_pool()

# ============ MIDDLEWARES PARA CONTROL DE CONEXIONES ============

@app.before_request
def before_request():
    """Abrir conexión antes de cada request"""
    g.db = get_db()
    g.start_time = time.time()
    g.request_id = str(int(time.time() * 1000))

@app.teardown_request
def teardown_request(error=None):
    """Cerrar conexión garantizado al final del request"""
    db = getattr(g, 'db', None)
    if db is not None:
        try:
            if error:
                db.rollback()
            else:
                db.commit()
            db.close()
        except Exception as e:
            print(f"Error cerrando conexión: {e}")
        finally:
            g.db = None

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Cierre forzado al final del contexto"""
    db = getattr(g, 'db', None)
    if db is not None:
        try:
            db.close()
        except:
            pass
        g.db = None

# ============ END MIDDLEWARES ============

from routes.auth_routes import auth_bp
from routes.passenger_routes import passenger_bp
from routes.driver_routes import driver_bp
from routes.trip_routes import trips_bp
from routes.notifications import notifications_bp
from routes.wallet import wallet_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(passenger_bp, url_prefix='/passenger')
app.register_blueprint(driver_bp, url_prefix='/driver')
app.register_blueprint(trips_bp, url_prefix='/trips')
app.register_blueprint(notifications_bp, url_prefix='/notifications')
app.register_blueprint(wallet_bp, url_prefix='/wallet')

# Endpoint de debug para monitorear conexiones
@app.route('/debug/connections', methods=['GET'])
def debug_connections():
    """Ver estado de las conexiones (solo desarrollo)"""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
        threads = cursor.fetchone()
        
        cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
        max_conn = cursor.fetchone()
        
        cursor.execute("""
            SELECT COUNT(*) as idle_count 
            FROM information_schema.PROCESSLIST 
            WHERE command = 'Sleep' AND time > 10
        """)
        idle = cursor.fetchone()
        
        return {
            'active_connections': int(threads['Value']),
            'max_connections': int(max_conn['Value']),
            'idle_connections_gt_10s': int(idle['idle_count']),
            'status': 'ok' if int(idle['idle_count']) < 10 else 'warning'
        }
    except Exception as e:
        return {'error': str(e)}
    finally:
        cursor.close()
        db.close()

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Iniciando servidor Avit...")
    print("=" * 50)
    init_db()
    app.run(debug=True, port=3001, host='0.0.0.0')
