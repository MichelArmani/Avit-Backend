from flask import Blueprint, request, jsonify


notifications_bp = Blueprint('notifications', __name__)

def get_user_from_token():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return None
    from app import get_db
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute('SELECT * FROM users WHERE token = %s', (token,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()

@notifications_bp.route('', methods=['GET'])
def get_notifications():
    user = get_user_from_token()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 20, type=int)
    from app import get_db
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM notifications 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """, (user['id'], limit, skip))
        
        notifications = cursor.fetchall()
        
        return jsonify({
            'data': {
                'notifications': notifications,
                'total': len(notifications)
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@notifications_bp.route('/mark-read', methods=['POST'])
def mark_read():
    user = get_user_from_token()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    notification_id = data.get('notification_id')
    from app import get_db
    db = get_db()
    cursor = db.cursor()
    
    try:
        if notification_id:
            # Marcar una notificación específica
            cursor.execute(
                'UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s',
                (notification_id, user['id'])
            )
        else:
            # Marcar todas como leídas
            cursor.execute(
                'UPDATE notifications SET is_read = TRUE WHERE user_id = %s',
                (user['id'],)
            )
        
        db.commit()
        
        return jsonify({'data': {'message': 'Notifications marked as read'}}), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@notifications_bp.route('/register-token', methods=['POST'])
def register_token():
    user = get_user_from_token()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    device_token = data.get('device_token')
    device_type = data.get('device_type', 'web')
    app_version = data.get('app_version', '1.0.0')
    
    if not device_token:
        return jsonify({'error': 'Device token is required'}), 400
    from app import get_db
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Verificar si ya existe el token
        cursor.execute(
            'SELECT id FROM device_tokens WHERE device_token = %s AND user_id = %s',
            (device_token, user['id'])
        )
        
        existing = cursor.fetchone()
        
        if existing:
            # Actualizar token existente
            cursor.execute(
                'UPDATE device_tokens SET device_type = %s, app_version = %s, created_at = NOW() WHERE id = %s',
                (device_type, app_version, existing['id'])
            )
        else:
            # Insertar nuevo token
            cursor.execute(
                'INSERT INTO device_tokens (user_id, device_token, device_type, app_version) VALUES (%s, %s, %s, %s)',
                (user['id'], device_token, device_type, app_version)
            )
        
        db.commit()
        
        return jsonify({'data': {'message': 'Token registered successfully'}}), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()