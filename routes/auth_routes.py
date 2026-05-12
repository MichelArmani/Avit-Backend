from flask import Blueprint, request, jsonify, g
from utils.helpers import generate_token, generate_verification_code
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    phone_number = data.get('phone_number')
    full_name = data.get('full_name')
    email = data.get('email')
    password = data.get('password')
    
    if not phone_number or not full_name or not password:
        return jsonify({'error': 'Missing required fields'}), 400
    
    # ✅ Usar conexión de g.db (abierta por middleware)
    cursor = g.db.cursor()
    
    try:
        # Verificar si el teléfono ya existe
        cursor.execute('SELECT id FROM users WHERE phone_number = %s', (phone_number,))
        if cursor.fetchone():
            return jsonify({'error': 'Phone number already registered'}), 400
        
        # Generar código de verificación
        code = generate_verification_code()
        expires_at = datetime.now() + timedelta(minutes=10)
        
        # Guardar código de verificación
        cursor.execute(
            'INSERT INTO verification_codes (phone_number, code, expires_at) VALUES (%s, %s, %s)',
            (phone_number, code, expires_at)
        )
        g.db.commit()
        
        # En desarrollo, mostrar el código en consola
        print(f'📱 Verification code for {phone_number}: {code}')
        
        return jsonify({
            'message': 'Verification code sent',
            'code': code,
            'data': {
                'message': 'Verification code sent',
                'code': code
            }
        }), 201
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@auth_bp.route('/verify-phone', methods=['POST'])
def verify_phone():
    data = request.json
    phone_number = data.get('phone_number')
    code = data.get('code')
    
    cursor = g.db.cursor()
    
    try:
        # Verificar código
        cursor.execute(
            'SELECT * FROM verification_codes WHERE phone_number = %s AND code = %s AND expires_at > NOW() ORDER BY id DESC LIMIT 1',
            (phone_number, code)
        )
        verification = cursor.fetchone()
        
        if not verification:
            return jsonify({'error': 'Invalid or expired code'}), 400
        
        # Marcar como usado
        cursor.execute('DELETE FROM verification_codes WHERE id = %s', (verification['id'],))
        g.db.commit()
        
        return jsonify({
            'message': 'Phone verified successfully',
            'code': code
        }), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@auth_bp.route('/resend-code', methods=['POST'])
def resend_code():
    data = request.json
    phone_number = data.get('phone_number')
    
    cursor = g.db.cursor()
    
    try:
        code = generate_verification_code()
        expires_at = datetime.now() + timedelta(minutes=10)
        
        cursor.execute(
            'INSERT INTO verification_codes (phone_number, code, expires_at) VALUES (%s, %s, %s)',
            (phone_number, code, expires_at)
        )
        g.db.commit()
        
        print(f'📱 New verification code for {phone_number}: {code}')
        
        return jsonify({
            'message': 'Code resent successfully',
            'code': code
        }), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    phone_number = data.get('phone_number')
    password = data.get('password')
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM users WHERE phone_number = %s', (phone_number,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not user['is_verified']:
            return jsonify({'error': 'Phone not verified'}), 401
        
        # Verificar password
        if password and user['password'] != password:
            return jsonify({'error': 'Invalid password'}), 401
        
        # Si no tiene token, generar uno nuevo
        current_token = user.get('token')
        if not current_token:
            token = generate_token()
            cursor.execute('UPDATE users SET token = %s WHERE id = %s', (token, user['id']))
            g.db.commit()
            user['token'] = token
        
        # Obtener perfil de conductor si existe
        driver_profile = None
        if user['is_driver']:
            cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
            driver_profile = cursor.fetchone()
        
        print(f'✅ User logged in: {user["full_name"]}')
        
        return jsonify({
            'data': {
                'access_token': user['token'],
                'token_type': 'bearer',
                'user': {
                    'id': str(user['id']),
                    'phone_number': user['phone_number'],
                    'full_name': user['full_name'],
                    'email': user['email'] if user['email'] else '',
                    'is_verified': bool(user['is_verified']),
                    'is_driver': bool(user['is_driver']),
                    'profile_image': user['profile_image'],
                    'rating': float(user['rating']) if user['rating'] else 5.0,
                    'total_trips': int(user['total_trips']) if user['total_trips'] else 0,
                    'wallet_balance': float(user['wallet_balance']) if user['wallet_balance'] else 0.00,
                    'referral_code': user['referral_code']
                },
                'driver_profile': driver_profile
            }
        }), 200
        
    except Exception as e:
        print(f"Error en login: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@auth_bp.route('/logout', methods=['POST'])
def logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    
    if not token:
        return jsonify({'message': 'No token provided'}), 200
    
    cursor = g.db.cursor()
    try:
        cursor.execute('UPDATE users SET token = NULL WHERE token = %s', (token,))
        g.db.commit()
        print('🔒 User logged out')
    except Exception as e:
        print(f"Error during logout: {e}")
    finally:
        cursor.close()
    
    return jsonify({'message': 'Logged out'}), 200

@auth_bp.route('/complete-registration', methods=['POST'])
def complete_registration():
    data = request.json
    phone_number = data.get('phone_number')
    full_name = data.get('full_name')
    email = data.get('email')
    password = data.get('password')
    
    if not phone_number or not full_name or not password:
        return jsonify({'error': 'Missing required fields'}), 400
    
    cursor = g.db.cursor()
    
    try:
        # Verificar si el teléfono ya está registrado
        cursor.execute('SELECT id FROM users WHERE phone_number = %s', (phone_number,))
        if cursor.fetchone():
            return jsonify({'error': 'Phone number already registered'}), 400
        
        # Generar token estático
        token = generate_token()
        
        # Crear usuario directamente (ya verificado)
        cursor.execute("""
            INSERT INTO users (phone_number, full_name, email, password, is_verified, token)
            VALUES (%s, %s, %s, %s, TRUE, %s)
        """, (phone_number, full_name, email, password, token))
        
        user_id = cursor.lastrowid
        g.db.commit()
        
        # Obtener usuario creado
        cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        user = cursor.fetchone()
        
        return jsonify({
            'data': {
                'access_token': token,
                'token_type': 'bearer',
                'user': {
                    'id': user['id'],
                    'phone_number': user['phone_number'],
                    'full_name': user['full_name'],
                    'email': user['email'],
                    'is_verified': user['is_verified'],
                    'is_driver': user['is_driver'],
                    'profile_image': user['profile_image'],
                    'rating': float(user['rating']),
                    'total_trips': user['total_trips'],
                    'wallet_balance': float(user['wallet_balance']),
                    'referral_code': user['referral_code']
                },
                'driver_profile': None
            }
        }), 201
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
