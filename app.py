from flask import Flask
from flask_cors import CORS
from config import Config
import pymysql
from pymysql.cursors import DictCursor

# Crear la aplicación Flask primero
app = Flask(__name__)
CORS(app, origins=[
    "http://localhost:3000",
    'https://localhost:3000',  # Next.js con HTTPS
    'http://localhost:3000',   # Tu backend
    
    'https://localhost:3001',  # Next.js con HTTPS
    'http://localhost:3001',   # Tu backend

    'https://localhost:3002',  # Next.js con HTTPS
    'http://localhost:3002',   # Tu backend
])

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
        
        print("🔄 Creando tablas en la base de datos...")
        
        # Crear tabla de usuarios
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'users' creada/verificada")
        
        # Crear tabla de códigos de verificación
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                phone_number VARCHAR(20) NOT NULL,
                code VARCHAR(10) NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'verification_codes' creada/verificada")
        
        # Crear tabla de conductores
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'drivers' creada/verificada")
        
        # Crear tabla de viajes (ACTUALIZADA con nuevas columnas)
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
                status ENUM('searching', 'driver_assigned', 'driver_arriving', 'in_progress', 'completed', 'cancelled') DEFAULT 'searching',
                vehicle_type ENUM('economy', 'comfort', 'premium') DEFAULT 'economy',
                payment_method ENUM('cash', 'card', 'wallet') DEFAULT 'cash',
                estimated_price DECIMAL(10,2) DEFAULT 0.00,
                final_price DECIMAL(10,2),
                estimated_distance DECIMAL(10,2) DEFAULT 0.00,
                estimated_duration INT DEFAULT 0,
                passenger_rating INT,
                driver_rating INT,
                cancellation_reason VARCHAR(500),
                rejected_drivers JSON DEFAULT NULL,
                driver_assigned_at TIMESTAMP NULL DEFAULT NULL,
                driver_arrived_at TIMESTAMP NULL DEFAULT NULL,
                started_at TIMESTAMP NULL DEFAULT NULL,
                completed_at TIMESTAMP NULL DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (driver_id) REFERENCES drivers(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'trips' creada/verificada (con nuevas columnas: rejected_drivers, driver_assigned_at, driver_arrived_at, started_at, completed_at)")
        
        # Crear tabla de métodos de pago (NUEVA)
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'payment_methods' creada/verificada")
        
        # Crear tabla de transacciones de wallet (NUEVA)
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'wallet_transactions' creada/verificada")
        
        # Crear tabla de notificaciones
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'notifications' creada/verificada")
        
        # Crear tabla de device tokens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                device_token VARCHAR(500) NOT NULL,
                device_type VARCHAR(50),
                app_version VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'device_tokens' creada/verificada")
        
        # Crear tabla de lugares guardados (NUEVA)
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        print("✓ Tabla 'saved_places' creada/verificada")
        
        db.commit()
        print("✅ Base de datos inicializada correctamente")
        
    except Exception as e:
        print(f"❌ Error al inicializar la base de datos: {str(e)}")
        if 'db' in locals():
            db.rollback()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()

# Ahora importamos los blueprints DESPUÉS de definir app y get_db
# Esto evita la importación circular
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
    
    print("\n📡 Servidor corriendo en:")
    print("   ➜ http://localhost:3001")
    print("   ➜ http://127.0.0.1:3001")
    print("\n📚 Endpoints disponibles:")
    print("   ➜ /auth/register")
    print("   ➜ /auth/login")
    print("   ➜ /auth/verify-phone")
    print("   ➜ /auth/complete-registration")
    print("   ➜ /passenger/*")
    print("   ➜ /driver/*")
    print("   ➜ /trips/*")
    print("\n💡 Presiona Ctrl+C para detener el servidor")
    print("=" * 50)
    
    app.run(debug=True, port=3001, host='0.0.0.0')