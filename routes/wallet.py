from flask import Blueprint, request, jsonify


wallet_bp = Blueprint('wallet', __name__)

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

@wallet_bp.route('/add-funds', methods=['POST'])
def add_funds():
    user = get_user_from_token()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    amount = data.get('amount', 0)
    
    if amount <= 0:
        return jsonify({'error': 'Invalid amount'}), 400
    from app import get_db
    db = get_db()
    cursor = db.cursor()
    
    try:
        new_balance = float(user['wallet_balance']) + amount
        
        cursor.execute(
            'UPDATE users SET wallet_balance = %s WHERE id = %s',
            (new_balance, user['id'])
        )
        db.commit()
        
        return jsonify({
            'data': {
                'new_balance': new_balance,
                'message': f'${amount} added to wallet'
            }
        }), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@wallet_bp.route('/withdraw', methods=['POST'])
def withdraw():
    user = get_user_from_token()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    amount = data.get('amount', 0)
    
    if amount <= 0:
        return jsonify({'error': 'Invalid amount'}), 400
    from app import get_db
    db = get_db()
    cursor = db.cursor()
    
    try:
        current_balance = float(user['wallet_balance'])
        
        if current_balance < amount:
            return jsonify({'error': 'Insufficient funds'}), 400
        
        new_balance = current_balance - amount
        
        cursor.execute(
            'UPDATE users SET wallet_balance = %s WHERE id = %s',
            (new_balance, user['id'])
        )
        db.commit()
        
        return jsonify({
            'data': {
                'new_balance': new_balance,
                'message': f'${amount} withdrawn from wallet'
            }
        }), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()