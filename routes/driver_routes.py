from flask import Blueprint, request, jsonify
from utils.helpers import get_user_from_token, calculate_distance

driver_bp = Blueprint('driver', __name__)

@driver_bp.route('/register', methods=['POST'])
def register_driver():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Verificar si ya tiene perfil
        cursor.execute('SELECT id FROM drivers WHERE user_id = %s', (user['id'],))
        if cursor.fetchone():
            return jsonify({'error': 'Driver profile already exists'}), 400
        
        cursor.execute("""
            INSERT INTO drivers 
            (user_id, license_number, license_expiry, vehicle_make, vehicle_model, 
             vehicle_year, vehicle_plate, vehicle_color)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user['id'],
            data['license_number'],
            data['license_expiry'],
            data['vehicle_make'],
            data['vehicle_model'],
            data['vehicle_year'],
            data['vehicle_plate'],
            data['vehicle_color']
        ))
        
        cursor.execute('UPDATE users SET is_driver = TRUE WHERE id = %s', (user['id'],))
        db.commit()
        
        print(f'✅ Driver registered for user {user["id"]}')
        
        return jsonify({'data': {'message': 'Driver registered successfully'}}), 201
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@driver_bp.route('/profile', methods=['GET', 'PUT'])
def driver_profile():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        profile = cursor.fetchone()
        
        if not profile:
            return jsonify({'data': None}), 200  # ✅ Cambiado de 404 a null
        
        if request.method == 'GET':
            return jsonify({'data': profile})
        else:
            # PUT - Actualizar perfil
            return jsonify({'data': {'message': 'Profile updated'}})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@driver_bp.route('/toggle-online', methods=['POST'])
def toggle_online():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'error': 'Driver profile not found'}), 404
        
        new_status = not driver['is_online']
        cursor.execute('UPDATE drivers SET is_online = %s WHERE id = %s', (new_status, driver['id']))
        db.commit()
        
        status_text = "online" if new_status else "offline"
        print(f'✅ Driver {driver["id"]} is now {status_text}')
        
        return jsonify({'data': {'is_online': new_status}}), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@driver_bp.route('/location', methods=['POST'])
def update_location():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if driver:
            cursor.execute(
                'UPDATE drivers SET current_lat = %s, current_lng = %s WHERE id = %s',
                (latitude, longitude, driver['id'])
            )
            db.commit()
        
        return jsonify({'data': {'message': 'Location updated'}}), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()


@driver_bp.route('/available-trips', methods=['GET'])
def get_available_trips():
    from app import get_db
    import json
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Obtener conductor
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
        
        # Obtener viajes buscando conductor, excluyendo los que ya fueron rechazados por este conductor
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
        
        # Ordenar por distancia (más cercano primero)
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
        db.close()  

@driver_bp.route('/trips/<trip_id>/accept', methods=['POST'])
def accept_trip(trip_id):
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'error': 'Driver profile not found'}), 404
        
        cursor.execute('SELECT * FROM trips WHERE id = %s AND status = "searching"', (trip_id,))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Trip not available'}), 404
        
        cursor.execute(
            'UPDATE trips SET driver_id = %s, status = "driver_assigned", driver_assigned_at = NOW() WHERE id = %s',
            (driver['id'], trip_id)
        )
        db.commit()
        
        print(f'✅ Trip {trip_id} accepted by driver {driver["id"]}')
        
        # ✅ Devolver el viaje actualizado
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
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@driver_bp.route('/trips/<trip_id>/reject', methods=['POST'])
def reject_trip(trip_id):
    from app import get_db
    import json
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Obtener el conductor
        cursor.execute('SELECT id FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        # Obtener el viaje
        cursor.execute('SELECT rejected_drivers FROM trips WHERE id = %s', (trip_id,))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Trip not found'}), 404
        
        # Actualizar la lista de conductores que rechazaron
        rejected_drivers = []
        if trip['rejected_drivers']:
            try:
                rejected_drivers = json.loads(trip['rejected_drivers'])
            except:
                rejected_drivers = []
        
        if str(driver['id']) not in rejected_drivers:
            rejected_drivers.append(str(driver['id']))
        
        # Guardar la lista actualizada
        cursor.execute(
            'UPDATE trips SET rejected_drivers = %s WHERE id = %s',
            (json.dumps(rejected_drivers), trip_id)
        )
        db.commit()
        
        print(f'❌ Trip {trip_id} rejected by driver {driver["id"]}')
        
        return jsonify({'data': {'message': 'Trip rejected', 'trip_id': trip_id}}), 200
        
    except Exception as e:
        db.rollback()
        print(f"Error rejecting trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()
    return jsonify({'data': {'message': 'Trip rejected'}}), 200

@driver_bp.route('/trips/<trip_id>/start', methods=['POST'])
def start_trip(trip_id):
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute(
            'UPDATE trips SET status = "in_progress" WHERE id = %s',
            (trip_id,)
        )
        db.commit()
        
        # ✅ Obtener el viaje actualizado
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
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@driver_bp.route('/trips/<trip_id>/complete', methods=['POST'])
def complete_trip(trip_id):
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute(
            'UPDATE trips SET status = "completed", completed_at = NOW() WHERE id = %s',
            (trip_id,)
        )
        db.commit()
        
        print(f'✅ Trip {trip_id} completed')
        
        # ✅ Devolver null para indicar que no hay viaje activo
        return jsonify({'data': None}), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        db.close()

@driver_bp.route('/current-trip', methods=['GET'])
def get_current_trip():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'data': None}), 200  # ✅ Devolver null
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.phone_number as passenger_phone,
                   u.rating as passenger_rating
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            WHERE t.driver_id = %s AND t.status IN ('driver_assigned', 'driver_arriving', 'in_progress')
            ORDER BY t.created_at DESC LIMIT 1
        """, (driver['id'],))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'data': None}), 200  # ✅ Devolver null, no 0
        
        # Formatear respuesta
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
        db.close()

@driver_bp.route('/earnings', methods=['GET'])
def get_earnings():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    period = request.args.get('period', 'week')
    
    # Versión simplificada - puede ser null si no hay datos
    return jsonify({'data': None}), 200

@driver_bp.route('/stats', methods=['GET'])
def get_stats():
    from app import get_db
    
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'data': {
                'total_trips': 0,
                'avg_rating': 5.0,
                'acceptance_rate': 100,
                'cancellation_rate': 0
            }}), 200  # ✅ Datos por defecto, no error
        
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
        db.close()

@driver_bp.route('/scheduled-trips', methods=['GET'])
def get_scheduled_trips():
    return jsonify({'data': {'trips': []}}), 200
