from flask import Blueprint, request, jsonify, g
from utils.helpers import get_user_from_token, calculate_distance
import re

# ✅ CORREGIDO: Nombre correcto del Blueprint
passenger_bp = Blueprint('passenger', __name__)

def validate_pagomovil_data(phone, ci, bank):
    errors = []
    phone_pattern = r'^(0412|0414|0416|0424|0426|0410|0420)\d{7}$'
    if not phone:
        errors.append('El teléfono de PagoMóvil es obligatorio')
    elif not re.match(phone_pattern, phone.replace('-', '')):
        errors.append('Formato de teléfono inválido. Ejemplo: 04121234567')
    ci_pattern = r'^[VEJPG]\d{6,8}$'
    if not ci:
        errors.append('La cédula de PagoMóvil es obligatoria')
    elif not re.match(ci_pattern, ci.upper()):
        errors.append('Formato de cédula inválido. Ejemplo: V12345678')
    valid_banks = [
        'Banco de Venezuela', 'Banesco', 'Mercantil', 'Provincial',
        'Banco Nacional de Crédito', 'Banco del Tesoro', 'Banco Exterior',
        'Banco Caroní', 'Banco Plaza', 'Banco Activo', 'Banco Bicentenario',
        'Banco de la Fuerza Armada', 'Banco Sofitasa', 'Banco del Sur'
    ]
    if not bank:
        errors.append('El banco de PagoMóvil es obligatorio')
    elif bank not in valid_banks:
        errors.append('Banco inválido')
    return errors

@passenger_bp.route('/register', methods=['POST'])  # ✅ CORREGIDO
def register_driver():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT id FROM drivers WHERE user_id = %s', (user['id'],))
        if cursor.fetchone():
            return jsonify({'error': 'Driver profile already exists'}), 400
        
        pagomovil_errors = validate_pagomovil_data(
            data.get('pagomovil_phone', ''),
            data.get('pagomovil_ci', ''),
            data.get('pagomovil_bank', '')
        )
        if pagomovil_errors:
            return jsonify({'error': ' | '.join(pagomovil_errors)}), 400
        
        cursor.execute("""
            INSERT INTO drivers 
            (user_id, license_number, license_expiry, vehicle_make, vehicle_model, 
             vehicle_year, vehicle_plate, vehicle_color, 
             pagomovil_phone, pagomovil_ci, pagomovil_bank)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user['id'],
            data['license_number'],
            data['license_expiry'],
            data['vehicle_make'],
            data['vehicle_model'],
            data['vehicle_year'],
            data['vehicle_plate'],
            data['vehicle_color'],
            data['pagomovil_phone'],
            data['pagomovil_ci'],
            data['pagomovil_bank']
        ))
        
        cursor.execute('UPDATE users SET is_driver = TRUE WHERE id = %s', (user['id'],))
        g.db.commit()
        
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver_profile = cursor.fetchone()
        
        return jsonify({'data': dict(driver_profile)}), 201
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/profile', methods=['GET', 'PUT'])  # ✅ CORREGIDO
def driver_profile():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        if request.method == 'GET':
            cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
            profile = cursor.fetchone()
            if not profile:
                return jsonify({'data': None}), 200
            if 'pagomovil_phone' not in profile:
                profile['pagomovil_phone'] = ''
                profile['pagomovil_ci'] = ''
                profile['pagomovil_bank'] = ''
            return jsonify({'data': profile}), 200
        else:
            data = request.json
            update_fields = []
            params = []
            allowed_fields = [
                'license_number', 'license_expiry', 'vehicle_make', 'vehicle_model',
                'vehicle_year', 'vehicle_plate', 'vehicle_color',
                'pagomovil_phone', 'pagomovil_ci', 'pagomovil_bank'
            ]
            for field in allowed_fields:
                if field in data:
                    if field == 'pagomovil_phone' and data[field]:
                        phone_pattern = r'^(0412|0414|0416|0424|0426|0410|0420)\d{7}$'
                        if not re.match(phone_pattern, data[field].replace('-', '')):
                            return jsonify({'error': 'Formato de teléfono inválido'}), 400
                    if field == 'pagomovil_ci' and data[field]:
                        ci_pattern = r'^[VEJPG]\d{6,8}$'
                        if not re.match(ci_pattern, data[field].upper()):
                            return jsonify({'error': 'Formato de cédula inválido'}), 400
                    if field == 'pagomovil_bank' and data[field]:
                        valid_banks = [
                            'Banco de Venezuela', 'Banesco', 'Mercantil', 'Provincial',
                            'Banco Nacional de Crédito', 'Banco del Tesoro', 'Banco Exterior',
                            'Banco Caroní', 'Banco Plaza', 'Banco Activo', 'Banco Bicentenario',
                            'Banco de la Fuerza Armada', 'Banco Sofitasa', 'Banco del Sur'
                        ]
                        if data[field] not in valid_banks:
                            return jsonify({'error': 'Banco inválido'}), 400
                    update_fields.append(f"{field} = %s")
                    params.append(data[field])
            
            if not update_fields:
                return jsonify({'data': {'message': 'No fields to update'}}), 200
            
            params.append(user['id'])
            query = f"UPDATE drivers SET {', '.join(update_fields)} WHERE user_id = %s"
            cursor.execute(query, params)
            g.db.commit()
            
            cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
            updated_profile = cursor.fetchone()
            return jsonify({'data': updated_profile}), 200
            
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/toggle-online', methods=['POST'])  # ✅ CORREGIDO
def toggle_online():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'error': 'Driver profile not found'}), 404
        
        new_status = not driver['is_online']
        cursor.execute('UPDATE drivers SET is_online = %s WHERE id = %s', (new_status, driver['id']))
        g.db.commit()
        
        return jsonify({'data': {'is_online': new_status}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/location', methods=['POST'])  # ✅ CORREGIDO
def update_location():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if driver:
            cursor.execute(
                'UPDATE drivers SET current_lat = %s, current_lng = %s WHERE id = %s',
                (latitude, longitude, driver['id'])
            )
            g.db.commit()
        
        return jsonify({'data': {'message': 'Location updated'}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/available-trips', methods=['GET'])  # ✅ CORREGIDO
def get_available_trips():
    import json
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s AND is_online = TRUE', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({
                'data': {
                    'trips': [],
                    'count': 0,
                    'driver_online': False
                }
            }), 200
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.rating as passenger_rating,
                   u.phone_number as passenger_phone
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            WHERE t.status = 'searching' 
              AND t.driver_id IS NULL
              AND (t.rejected_drivers IS NULL 
                   OR NOT JSON_CONTAINS(t.rejected_drivers, %s))
        """, (json.dumps(str(driver['id'])),))
        
        available_trips = cursor.fetchall()
        
        trips_with_distance = []
        for trip in available_trips:
            if driver['current_lat'] and driver['current_lng']:
                distance = calculate_distance(
                    driver['current_lat'], driver['current_lng'],
                    trip['origin_lat'], trip['origin_lng']
                )
                trip['distance_to_pickup'] = round(distance, 2)
                trip['pickup_eta_minutes'] = max(1, int(distance * 3))
            else:
                trip['distance_to_pickup'] = 0
                trip['pickup_eta_minutes'] = 0
            
            trip['trip_id'] = trip['id']
            trip['price'] = float(trip['estimated_price'])
            trip['trip_distance'] = float(trip['estimated_distance'])
            trip['trip_duration'] = trip['estimated_duration']
            
            trip['passenger'] = {
                'name': trip['passenger_name'],
                'rating': float(trip['passenger_rating']) if trip['passenger_rating'] else 5.0,
                'phone': trip['passenger_phone']
            }
            
            trip['origin'] = {
                'address': trip['origin_address'],
                'lat': float(trip['origin_lat']),
                'lng': float(trip['origin_lng'])
            }
            
            trip['destination'] = {
                'address': trip['dest_address'],
                'lat': float(trip['dest_lat']),
                'lng': float(trip['dest_lng'])
            }
            
            trips_with_distance.append(trip)
        
        trips_with_distance.sort(key=lambda x: x['distance_to_pickup'])
        
        return jsonify({
            'data': {
                'trips': trips_with_distance,
                'count': len(trips_with_distance),
                'driver_online': driver['is_online']
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting available trips: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/trips/<trip_id>/accept', methods=['POST'])  # ✅ CORREGIDO
def accept_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'error': 'Driver profile not found'}), 404
        
        cursor.execute('SELECT * FROM trips WHERE id = %s AND status = %s', (trip_id, 'searching'))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Trip not available'}), 404
        
        cursor.execute(
            'UPDATE trips SET driver_id = %s, status = %s, driver_assigned_at = NOW() WHERE id = %s',
            (driver['id'], 'driver_assigned', trip_id)
        )
        g.db.commit()
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.phone_number as passenger_phone,
                   u.rating as passenger_rating
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            WHERE t.id = %s
        """, (trip_id,))
        
        updated_trip = cursor.fetchone()
        
        if updated_trip:
            trip_data = dict(updated_trip)
            trip_data['trip_id'] = trip_data['id']
            trip_data['price'] = float(trip_data['estimated_price'])
            
            trip_data['passenger'] = {
                'name': trip_data['passenger_name'],
                'phone': trip_data['passenger_phone'],
                'rating': float(trip_data['passenger_rating']) if trip_data['passenger_rating'] else 5.0
            }
            
            trip_data['origin'] = {
                'address': trip_data['origin_address'],
                'lat': float(trip_data['origin_lat']),
                'lng': float(trip_data['origin_lng'])
            }
            
            trip_data['destination'] = {
                'address': trip_data['dest_address'],
                'lat': float(trip_data['dest_lat']),
                'lng': float(trip_data['dest_lng'])
            }
            
            return jsonify({'data': trip_data}), 200
        
        return jsonify({'data': {'message': 'Trip accepted'}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/trips/<trip_id>/reject', methods=['POST'])  # ✅ CORREGIDO
def reject_trip(trip_id):
    import json
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT id FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        cursor.execute('SELECT rejected_drivers FROM trips WHERE id = %s', (trip_id,))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Trip not found'}), 404
        
        rejected_drivers = []
        if trip['rejected_drivers']:
            try:
                rejected_drivers = json.loads(trip['rejected_drivers'])
            except:
                rejected_drivers = []
        
        if str(driver['id']) not in rejected_drivers:
            rejected_drivers.append(str(driver['id']))
        
        cursor.execute(
            'UPDATE trips SET rejected_drivers = %s WHERE id = %s',
            (json.dumps(rejected_drivers), trip_id)
        )
        g.db.commit()
        
        return jsonify({'data': {'message': 'Trip rejected', 'trip_id': trip_id}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/trips/<trip_id>/start', methods=['POST'])  # ✅ CORREGIDO
def start_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('UPDATE trips SET status = %s WHERE id = %s', ('in_progress', trip_id))
        g.db.commit()
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.phone_number as passenger_phone,
                   u.rating as passenger_rating
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            WHERE t.id = %s
        """, (trip_id,))
        
        updated_trip = cursor.fetchone()
        
        if updated_trip:
            trip_data = dict(updated_trip)
            trip_data['trip_id'] = trip_data['id']
            trip_data['price'] = float(trip_data['estimated_price'])
            
            trip_data['passenger'] = {
                'name': trip_data['passenger_name'],
                'phone': trip_data['passenger_phone'],
                'rating': float(trip_data['passenger_rating']) if trip_data['passenger_rating'] else 5.0
            }
            
            trip_data['origin'] = {
                'address': trip_data['origin_address'],
                'lat': float(trip_data['origin_lat']),
                'lng': float(trip_data['origin_lng'])
            }
            
            trip_data['destination'] = {
                'address': trip_data['dest_address'],
                'lat': float(trip_data['dest_lat']),
                'lng': float(trip_data['dest_lng'])
            }
            
            return jsonify({'data': trip_data}), 200
        
        return jsonify({'data': {'message': 'Trip started'}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/trips/<trip_id>/complete', methods=['POST'])  # ✅ CORREGIDO
def complete_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('UPDATE trips SET status = %s, completed_at = NOW() WHERE id = %s', ('completed', trip_id))
        g.db.commit()
        
        return jsonify({'data': None}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/current-trip', methods=['GET'])  # ✅ CORREGIDO
def get_current_trip():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'data': None}), 200
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.phone_number as passenger_phone,
                   u.rating as passenger_rating,
                   d.pagomovil_phone, d.pagomovil_ci, d.pagomovil_bank
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            JOIN drivers d ON t.driver_id = d.id
            WHERE t.driver_id = %s AND t.status IN ('driver_assigned', 'driver_arriving', 'in_progress')
            ORDER BY t.created_at DESC LIMIT 1
        """, (driver['id'],))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'data': None}), 200
        
        trip_data = {
            'id': trip['id'],
            'trip_id': trip['id'],
            'status': trip['status'],
            'price': float(trip['estimated_price']),
            'estimated_price': float(trip['estimated_price']),
            'estimated_distance': float(trip['estimated_distance']),
            'estimated_duration': trip['estimated_duration'],
            'origin_address': trip['origin_address'],
            'destination_address': trip['dest_address'],
            'passenger': {
                'name': trip['passenger_name'],
                'phone': trip['passenger_phone'],
                'rating': float(trip['passenger_rating']) if trip['passenger_rating'] else 5.0
            },
            'driver': {
                'name': user.get('full_name', 'Conductor'),
                'phone': user.get('phone_number', ''),
                'rating': float(driver['rating']) if driver['rating'] else 5.0,
                'vehicle': {
                    'make': driver['vehicle_make'],
                    'model': driver['vehicle_model'],
                    'plate': driver['vehicle_plate'],
                    'color': driver['vehicle_color']
                },
                'location': {
                    'lat': float(driver['current_lat']) if driver['current_lat'] else None,
                    'lng': float(driver['current_lng']) if driver['current_lng'] else None
                },
                'pagomovil': {
                    'phone': driver.get('pagomovil_phone', ''),
                    'ci': driver.get('pagomovil_ci', ''),
                    'bank': driver.get('pagomovil_bank', '')
                }
            },
            'origin': {
                'address': trip['origin_address'],
                'lat': float(trip['origin_lat']),
                'lng': float(trip['origin_lng'])
            },
            'destination': {
                'address': trip['dest_address'],
                'lat': float(trip['dest_lat']),
                'lng': float(trip['dest_lng'])
            },
            'created_at': str(trip['created_at']) if trip['created_at'] else ''
        }
        
        return jsonify({'data': trip_data}), 200
        
    except Exception as e:
        print(f"Error getting current trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/earnings', methods=['GET'])  # ✅ CORREGIDO
def get_earnings():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    period = request.args.get('period', 'week')
    return jsonify({'data': None}), 200

@passenger_bp.route('/stats', methods=['GET'])  # ✅ CORREGIDO
def get_stats():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'data': {
                'total_trips': 0,
                'avg_rating': 5.0,
                'acceptance_rate': 100,
                'cancellation_rate': 0
            }}), 200
        
        return jsonify({
            'data': {
                'total_trips': int(driver['total_trips']) if driver['total_trips'] else 0,
                'avg_rating': float(driver['rating']) if driver['rating'] else 5.0,
                'acceptance_rate': float(driver['acceptance_rate']) if driver['acceptance_rate'] else 100.0,
                'cancellation_rate': float(driver['cancellation_rate']) if driver['cancellation_rate'] else 0.0
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@passenger_bp.route('/scheduled-trips', methods=['GET'])  # ✅ CORREGIDO
def get_scheduled_trips():
    return jsonify({'data': {'trips': []}}), 200
