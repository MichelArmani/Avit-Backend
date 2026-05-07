from flask import Flask
from flask_cors import CORS
from config import Config
import pymysql
from pymysql.cursors import DictCursor

app = Flask(__name__)

# ✅ Configuración CORS que permite TODOS los orígenes
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["*"],
        "expose_headers": ["*"]
    }
})

# También agrega este middleware MANUAL por si acaso
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', '*')
    response.headers.add('Access-Control-Allow-Methods', '*')
    response.headers.add('Access-Control-Allow-Credentials', 'false')
    return response

# Configuración de la base de datos
def get_db():
    return pymysql.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        port=Config.MYSQL_PORT,
        cursorclass=DictCursor
    )

def init_db():
    """Inicializa la base de datos y crea las tablas necesarias"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        print("🔄 Inicializando base de datos...")
        
        # Verificar si la tabla trips existe y eliminar la constraint FOREIGN KEY primero
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'trips'
        """)
        table_exists = cursor.fetchone()['COUNT(*)'] > 0
        
        if table_exists:
            print("⚠️ Tabla 'trips' existe, verificando estructura...")
            
            # Verificar el ENUM actual
            cursor.execute("""
                SELECT COLUMN_TYPE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'trips'
                AND COLUMN_NAME = 'status'
            """)
            enum_values = cursor.fetchone()
            
            if enum_values:
                print(f"📊 ENUM actual: {enum_values['COLUMN_TYPE']}")
                
                # Si el ENUM no tiene los valores correctos, recrear la tabla
                if "'searching'" not in enum_values['COLUMN_TYPE'] or "'cancelled'" not in enum_values['COLUMN_TYPE']:
                    print("🔄 ENUM incorrecto, recreando tabla trips...")
                    
                    # Eliminar foreign keys primero
                    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                    
                    # Obtener todas las foreign keys
                    cursor.execute("""
                        SELECT CONSTRAINT_NAME
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = DATABASE()
                        AND TABLE_NAME = 'trips'
                        AND REFERENCED_TABLE_NAME IS NOT NULL
                    """)
                    foreign_keys = cursor.fetchall()
                    
                    for fk in foreign_keys:
                        cursor.execute(f"ALTER TABLE trips DROP FOREIGN KEY {fk['CONSTRAINT_NAME']}")
                        print(f"✓ Eliminada foreign key: {fk['CONSTRAINT_NAME']}")
                    
                    # Renombrar tabla vieja
                    cursor.execute("RENAME TABLE trips TO trips_old")
                    print("✓ Tabla trips renombrada a trips_old")
                    
                    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        # Crear tabla trips con el ENUM correcto
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trips (
                id VARCHAR(50) PRIMARY KEY,
                passenger_id INT NOT NULL,
                driver_id INT,
                origin_lat DECIMAL(10,8) NOT NULL,
                origin_lng DECIMAL(11,8) NOT NULL,
                dest_lat DECIMAL(10,8) NOT NULL,
                dest_lng DECIMAL(11,8) NOT NULL,
                origin_address VARCHAR(500) NOT NULL,
                dest_address VARCHAR(500) NOT NULL,
                status ENUM('searching', 'accepted', 'driver_assigned', 'driver_arriving', 'in_progress', 'completed', 'cancelled', 'rejected') DEFAULT 'searching',
                vehicle_type ENUM('economy', 'comfort', 'premium') DEFAULT 'economy',
                payment_method ENUM('cash', 'card', 'wallet') DEFAULT 'cash',
                estimated_price DECIMAL(10,2) DEFAULT 0.00,
                final_price DECIMAL(10,2),
                estimated_distance DECIMAL(10,2) DEFAULT 0.00,
                estimated_duration INT DEFAULT 0,
                passenger_rating INT,
                driver_rating INT,
                cancellation_reason VARCHAR(500),
                cancelled_by ENUM('passenger', 'driver', 'system') DEFAULT NULL,
                rejected_drivers JSON DEFAULT NULL,
                driver_assigned_at TIMESTAMP NULL DEFAULT NULL,
                driver_arrived_at TIMESTAMP NULL DEFAULT NULL,
                started_at TIMESTAMP NULL DEFAULT NULL,
                completed_at TIMESTAMP NULL DEFAULT NULL,
                cancelled_at TIMESTAMP NULL DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_passenger (passenger_id),
                INDEX idx_driver (driver_id),
                INDEX idx_status (status),
                INDEX idx_created (created_at),
                FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (driver_id) REFERENCES drivers(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        print("✅ Tabla 'trips' creada correctamente con ENUM completo")
        
        # Si existía una tabla vieja, migrar los datos
        if table_exists:
            try:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                
                # Migrar datos de trips_old a trips nueva
                cursor.execute("""
                    INSERT IGNORE INTO trips (
                        id, passenger_id, driver_id, origin_lat, origin_lng,
                        dest_lat, dest_lng, origin_address, dest_address, status,
                        vehicle_type, payment_method, estimated_price, final_price,
                        estimated_distance, estimated_duration, passenger_rating,
                        driver_rating, cancellation_reason, rejected_drivers,
                        driver_assigned_at, driver_arrived_at, started_at,
                        completed_at, created_at, updated_at
                    )
                    SELECT 
                        id, passenger_id, driver_id, origin_lat, origin_lng,
                        dest_lat, dest_lng, origin_address, dest_address, 
                        CASE 
                            WHEN status = 'cancelled' THEN 'cancelled'
                            WHEN status = 'completed' THEN 'completed'
                            WHEN status = 'in_progress' THEN 'in_progress'
                            ELSE 'searching'
                        END as status,
                        vehicle_type, payment_method, estimated_price, final_price,
                        estimated_distance, estimated_duration, passenger_rating,
                        driver_rating, cancellation_reason, rejected_drivers,
                        driver_assigned_at, driver_arrived_at, started_at,
                        completed_at, created_at, updated_at
                    FROM trips_old
                """)
                print(f"✓ Migrados {cursor.rowcount} registros de trips_old")
                
                # Eliminar tabla vieja
                cursor.execute("DROP TABLE trips_old")
                print("✓ Tabla trips_old eliminada")
                
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                db.commit()
                
            except Exception as e:
                print(f"⚠️ Error al migrar datos: {str(e)}")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        # Crear el resto de las tablas
        create_other_tables(cursor)
        
        db.commit()
        print("✅ Base de datos inicializada correctamente")
        
    except Exception as e:
        print(f"❌ Error al inicializar la base de datos: {str(e)}")
        import traceback
        traceback.print_exc()
        if 'db' in locals():
            db.rollback()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()

def create_other_tables(cursor):
    """Crear las otras tablas de la base de datos"""
    
    # Tabla de usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            phone_number VARCHAR(20) UNIQUE NOT NULL,
            full_name VARCHAR(100) NOT NULL,
            email VARCHAR(100),
            password VARCHAR(255) NOT NULL,
            is_verified BOOLEAN DEFAULT FALSE,
            is_driver BOOLEAN DEFAULT FALSE,
            profile_image VARCHAR(500),
            rating DECIMAL(3,2) DEFAULT 5.00,
            total_trips INT DEFAULT 0,
            wallet_balance DECIMAL(10,2) DEFAULT 0.00,
            token VARCHAR(500) UNIQUE,
            referral_code VARCHAR(20) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_phone (phone_number),
            INDEX idx_token (token)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'users' creada/verificada")
    
    # Tabla de códigos de verificación
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            phone_number VARCHAR(20) NOT NULL,
            code VARCHAR(10) NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_phone_code (phone_number, code),
            INDEX idx_expires (expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'verification_codes' creada/verificada")
    
    # Tabla de conductores
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT UNIQUE NOT NULL,
            license_number VARCHAR(50) UNIQUE NOT NULL,
            license_expiry DATE NOT NULL,
            vehicle_make VARCHAR(50) NOT NULL,
            vehicle_model VARCHAR(50) NOT NULL,
            vehicle_year INT NOT NULL,
            vehicle_plate VARCHAR(20) UNIQUE NOT NULL,
            vehicle_color VARCHAR(30) NOT NULL,
            is_online BOOLEAN DEFAULT FALSE,
            current_lat DECIMAL(10,8),
            current_lng DECIMAL(11,8),
            rating DECIMAL(3,2) DEFAULT 5.00,
            total_trips INT DEFAULT 0,
            acceptance_rate DECIMAL(5,2) DEFAULT 100.00,
            cancellation_rate DECIMAL(5,2) DEFAULT 0.00,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_online (is_online),
            INDEX idx_location (current_lat, current_lng)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'drivers' creada/verificada")
    
    # Tabla de métodos de pago
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            payment_type ENUM('card', 'paypal', 'bank') NOT NULL,
            card_number VARCHAR(20),
            card_brand VARCHAR(20),
            card_expiry VARCHAR(10),
            is_default BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'payment_methods' creada/verificada")
    
    # Tabla de transacciones de wallet
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            transaction_type ENUM('add', 'withdraw', 'payment', 'refund') NOT NULL,
            status ENUM('pending', 'completed', 'failed') DEFAULT 'pending',
            reference_id VARCHAR(50),
            description VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_user_status (user_id, status),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'wallet_transactions' creada/verificada")
    
    # Tabla de notificaciones
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(200) NOT NULL,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT FALSE,
            notification_type VARCHAR(50),
            related_id VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_user_read (user_id, is_read),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'notifications' creada/verificada")
    
    # Tabla de device tokens
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            device_token VARCHAR(500) NOT NULL,
            device_type VARCHAR(50),
            app_version VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE KEY unique_user_device (user_id, device_token(255))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'device_tokens' creada/verificada")
    
    # Tabla de lugares guardados
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_places (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            name VARCHAR(100) NOT NULL,
            address VARCHAR(500) NOT NULL,
            lat DECIMAL(10,8) NOT NULL,
            lng DECIMAL(11,8) NOT NULL,
            place_type ENUM('home', 'work', 'favorite') DEFAULT 'favorite',
            icon VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_user_type (user_id, place_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    print("✓ Tabla 'saved_places' creada/verificada")

# Ahora importamos los blueprints DESPUÉS de definir app y get_db
from routes.auth_routes import auth_bp
from routes.passenger_routes import passenger_bp
from routes.driver_routes import driver_bp
from routes.trip_routes import trips_bp
from routes.notifications import notifications_bp
from routes.wallet import wallet_bp

# Registrar blueprints
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
    
    # Inicializar base de datos
    init_db()
    
    app.run(debug=True, port=3001, host='0.0.0.0')
