import random
import string
import math
from datetime import datetime, timedelta
from flask import g

def generate_token():
    """Genera un token estático para autenticación"""
    return 'avit_' + ''.join(random.choices(string.ascii_letters + string.digits, k=64))

def generate_verification_code():
    """Genera código de verificación de 6 dígitos"""
    return ''.join(random.choices(string.digits, k=6))

def generate_trip_id():
    """Genera ID único para viajes"""
    return 'trip_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

def get_user_from_token(auth_header):
    """Obtiene usuario desde el token usando la conexión de Flask g"""
    if not auth_header:
        return None
    
    token = auth_header.replace('Bearer ', '')
    
    # ✅ Usar la conexión que ya está en g.db (abierta por before_request)
    if not hasattr(g, 'db') or g.db is None:
        from app import get_db
        g.db = get_db()
    
    cursor = None
    try:
        cursor = g.db.cursor()
        cursor.execute('SELECT * FROM users WHERE token = %s', (token,))
        user = cursor.fetchone()
        
        # Verificar si la conexión sigue viva
        if user is None:
            # Hacer ping para verificar conexión
            g.db.ping(reconnect=True)
            cursor.execute('SELECT * FROM users WHERE token = %s', (token,))
            user = cursor.fetchone()
            
        return user
    except Exception as e:
        print(f"Error getting user from token: {e}")
        # Reconectar si es necesario
        try:
            g.db.ping(reconnect=True)
        except:
            from app import get_db
            g.db = get_db()
        return None
    finally:
        if cursor:
            cursor.close()

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calcula distancia usando la fórmula de Haversine"""
    R = 6371  # Radio de la Tierra en km
    
    try:
        lat1, lng1, lat2, lng2 = map(float, [lat1, lng1, lat2, lng2])
        lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
        
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c
    except Exception as e:
        print(f"Error calculating distance: {e}")
        return 0
