from flask import Blueprint, request, jsonify
from utils.helpers import get_user_from_token

passenger_bp = Blueprint('passenger', __name__)

@passenger_bp.route('/profile', methods=['GET', 'PUT'])
def profile():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        if request.method == 'GET':
            cursor.execute('SELECT * FROM users WHERE id = %s', (user['id'],))
            user_data = cursor.fetchone()
            
            return jsonify({
                'data': {
                    'id': str(user_data['id']),
                    'phone_number': user_data['phone_number'],
                    'full_name': user_data['full_name'],
                    'email': user_data.get('email', ''),
                    'is_verified': bool(user_data['is_verified']),
                    'is_driver': bool(user_data['is_driver']),
                    'profile_image': user_data.get('profile_image'),
                    'rating': float(user_data['rating']) if user_data['rating'] else 5.0,
                    'total_trips': int(user_data['total_trips']) if user_data['total_trips'] else 0,
                    'wallet_balance': float(user_data['wallet_balance']) if user_data['wallet_balance'] else 0.00
                }
            })
        
        elif request.method == 'PUT':
            data = request.json
            full_name = data.get('full_name', user['full_name'])
            email = data.get('email', user.get('email'))
            
            cursor.execute(
                'UPDATE users SET full_name = %s, email = %s WHERE id = %s',
                (full_name, email, user['id'])
            )
            db.commit()
            return jsonify({'data': {'message': 'Profile updated'}}), 200
            
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@passenger_bp.route('/favplace', methods=['PUT'])
def favplace():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()

    try:
        if request.method == 'PUT':
            data = request.json
            fav = data.get('fav', user['fav'])
            
            cursor.execute(
                'UPDATE users SET fav = %s WHERE id = %s',
                (fav, user['id'])
            )
            db.commit()
            return jsonify({'data': {'message': 'Profile updated'}}), 200
            
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()


@passenger_bp.route('/stats', methods=['GET'])
def stats():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM users WHERE id = %s', (user['id'],))
        user_data = cursor.fetchone()
        
        cursor.execute('SELECT COUNT(*) as total_trips FROM trips WHERE passenger_id = %s', (user['id'],))
        trips_data = cursor.fetchone()
        
        cursor.execute('SELECT COALESCE(SUM(estimated_price), 0) as total_spent FROM trips WHERE passenger_id = %s AND status = %s', (user['id'], 'completed'))
        spent_data = cursor.fetchone()
        
        return jsonify({
            'data': {
                'total_trips': int(trips_data['total_trips']),
                'avg_rating': float(user_data['rating']) if user_data['rating'] else 5.0,
                'total_spent': float(spent_data['total_spent'])
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@passenger_bp.route('/wallet', methods=['GET'])
def wallet():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT wallet_balance FROM users WHERE id = %s', (user['id'],))
        wallet_data = cursor.fetchone()
        
        return jsonify({
            'data': {
                'balance': float(wallet_data['wallet_balance']) if wallet_data and wallet_data['wallet_balance'] else 0.00
            }
        })
    finally:
        cursor.close()
        db.close()

@passenger_bp.route('/payment-methods', methods=['GET'])
def payment_methods():
    return jsonify({'data': {'methods': []}})

@passenger_bp.route('/add-payment-method', methods=['POST'])
def add_payment_method():
    return jsonify({'error': 'Cash only'}), 400
