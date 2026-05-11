from flask import Flask, request, make_response
from flask_cors import CORS
from config import Config
import pymysql
from pymysql.cursors import DictCursor

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], "allow_headers": ["*"], "expose_headers": ["*"]}})

def kill_idle_connections():
    """Elimina todas las conexiones idle en la base de datos MySQL"""
    try:
        # Conexión temporal para ejecutar el kill de conexiones idle
        temp_conn = pymysql.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            port=Config.MYSQL_PORT,
            cursorclass=DictCursor
        )
        
        with temp_conn.cursor() as cursor:
            # Obtener todas las conexiones idle (que no sean la conexión actual)
            cursor.execute("""
                SELECT ID, TIME, COMMAND, USER, HOST, DB
                FROM information_schema.PROCESSLIST
                WHERE COMMAND = 'Sleep' 
                AND USER = %s
                AND DB = %s
                AND ID != CONNECTION_ID()
            """, (Config.MYSQL_USER, Config.MYSQL_DB))
            
            idle_connections = cursor.fetchall()
            
            # Matar cada conexión idle
            for conn in idle_connections:
                try:
                    cursor.execute(f"KILL {conn['ID']}")
                    print(f"🔪 Conexión idle eliminada: ID {conn['ID']} - Tiempo: {conn['TIME']} segundos")
                except Exception as e:
                    print(f"❌ Error al matar conexión {conn['ID']}: {e}")
            
            temp_conn.commit()
            
        temp_conn.close()
        
        if idle_connections:
            print(f"✅ {len(idle_connections)} conexiones idle eliminadas")
        else:
            print("✅ No hay conexiones idle para eliminar")
            
    except Exception as e:
        print(f"⚠️ Error al limpiar conexiones idle: {e}")

def get_db():
    # Primero eliminar todas las conexiones idle
    kill_idle_connections()
    
    # Luego retornar una nueva conexión
    return pymysql.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        port=Config.MYSQL_PORT,
        cursorclass=DictCursor
    )

def init_db():
    # Inicialización de la base de datos
    pass

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

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Iniciando servidor Avit...")
    print("=" * 50)
    init_db()
    app.run(debug=True, port=3001, host='0.0.0.0')
