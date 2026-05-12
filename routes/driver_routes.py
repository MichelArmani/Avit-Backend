from flask import Blueprint, request, jsonify, g
from utils.helpers import get_user_from_token, calculate_distance
import json

driver_bp = Blueprint('driver', __name__)

@driver_bp.route('/register', methods=['POST'])
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
        
        print(f'✅ Driver registered for user {user["id"]}')
        
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver_profile = cursor.fetchone()
        
        return jsonify({'data': driver_profile}), 201
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/profile', methods=['GET', 'PUT'])
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
            
            return jsonify({'data': profile})
        
        else:
            data = request.json
            
            allowed_fields = [
                'license_number', 'license_expiry', 'vehicle_make', 'vehicle_model',
                'vehicle_year', 'vehicle_plate', 'vehicle_color',
                'pagomovil_phone', 'pagomovil_ci', 'pagomovil_bank'
            ]
            
            update_fields = []
            params = []
            
            for field in allowed_fields:
                if field in data and data[field] is not None:
                    update_fields.append(f"{field} = %s")
                    params.append(data[field])
            
            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400
            
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

@driver_bp.route('/toggle-online', methods=['POST'])
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
        
        status_text = "online" if new_status else "offline"
        print(f'✅ Driver {driver["id"]} is now {status_text}')
        
        return jsonify({'data': {'is_online': new_status}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/location', methods=['POST'])
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

@driver_bp.route('/available-trips', methods=['GET'])
def get_available_trips():
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

@driver_bp.route('/trips/<trip_id>/accept', methods=['POST'])
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
        
        print(f'✅ Trip {trip_id} accepted by driver {driver["id"]}')
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.phone_number as passenger_phone,
                   u.rating as passenger_rating,
                   d.pagomovil_phone, d.pagomovil_ci, d.pagomovil_bank
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            JOIN drivers d ON t.driver_id = d.id
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
            
            if trip_data.get('pagomovil_phone'):
                trip_data['pagomovil'] = {
                    'phone': trip_data['pagomovil_phone'],
                    'ci': trip_data['pagomovil_ci'],
                    'bank': trip_data['pagomovil_bank']
                }
            
            return jsonify({'data': trip_data}), 200
        
        return jsonify({'data': {'message': 'Trip accepted'}}), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/trips/<trip_id>/reject', methods=['POST'])
def reject_trip(trip_id):
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
        
        print(f'❌ Trip {trip_id} rejected by driver {driver["id"]}')
        
        return jsonify({'data': {'message': 'Trip rejected', 'trip_id': trip_id}}), 200
        
    except Exception as e:
        g.db.rollback()
        print(f"Error rejecting trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/trips/<trip_id>/start', methods=['POST'])
def start_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('UPDATE trips SET status = %s, started_at = NOW() WHERE id = %s', ('in_progress', trip_id))
        g.db.commit()
        
        cursor.execute("""
            SELECT t.*, u.full_name as passenger_name, u.phone_number as passenger_phone,
                   u.rating as passenger_rating,
                   d.pagomovil_phone, d.pagomovil_ci, d.pagomovil_bank
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            JOIN drivers d ON t.driver_id = d.id
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

@driver_bp.route('/trips/<trip_id>/complete', methods=['POST'])
def complete_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        cursor.execute('SELECT status FROM trips WHERE id = %s AND driver_id = %s', (trip_id, driver['id']))
        trip = cursor.fetchone()
        if not trip:
            return jsonify({'error': 'Trip not found or not assigned to you'}), 404
        
        if trip['status'] != 'in_progress':
            return jsonify({'error': f'Cannot complete trip with status: {trip["status"]}'}), 400
        
        cursor.execute('UPDATE trips SET status = %s, actual_end_time = NOW() WHERE id = %s', ('pending_payment', trip_id))
        g.db.commit()
        
        print(f'✅ Trip {trip_id} completed by driver, waiting for payment')
        
        return jsonify({
            'data': {
                'id': trip_id,
                'status': 'pending_payment',
                'message': 'Trip completed, waiting for payment confirmation'
            }
        }), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/trips/<trip_id>/confirm-payment', methods=['POST'])
def driver_confirm_payment(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        cursor.execute('SELECT status, passenger_payment_confirmed FROM trips WHERE id = %s AND driver_id = %s', (trip_id, driver['id']))
        trip = cursor.fetchone()
        if not trip:
            return jsonify({'error': 'Trip not found'}), 404
        
        if trip['status'] != 'pending_payment':
            return jsonify({'error': f'Invalid status for payment confirmation: {trip["status"]}'}), 400
        
        cursor.execute("""
            UPDATE trips 
            SET driver_payment_confirmed = TRUE,
                driver_payment_confirmed_at = NOW()
            WHERE id = %s
        """, (trip_id,))
        g.db.commit()
        
        cursor.execute('SELECT passenger_payment_confirmed FROM trips WHERE id = %s', (trip_id,))
        trip_data = cursor.fetchone()
        
        if trip_data and trip_data.get('passenger_payment_confirmed'):
            cursor.execute("""
                UPDATE trips 
                SET status = 'waiting_for_rating' 
                WHERE id = %s
            """, (trip_id,))
            g.db.commit()
            print(f'💰 Both confirmed payment for trip {trip_id}, waiting for rating')
        
        return jsonify({
            'data': {
                'id': trip_id,
                'status': 'waiting_for_rating' if (trip_data and trip_data.get('passenger_payment_confirmed')) else 'pending_payment',
                'message': 'Payment confirmed by driver'
            }
        }), 200
        
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/current-trip', methods=['GET'])
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
                   t.passenger_payment_confirmed, t.driver_payment_confirmed,
                   t.passenger_rated_at, t.driver_rated_at
            FROM trips t
            JOIN users u ON t.passenger_id = u.id
            WHERE t.driver_id = %s AND t.status IN ('driver_assigned', 'driver_arriving', 'in_progress', 'pending_payment', 'waiting_for_rating', 'waiting_for_other_rating')
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
            'created_at': str(trip['created_at']) if trip['created_at'] else '',
            'passenger_payment_confirmed': bool(trip.get('passenger_payment_confirmed')),
            'driver_payment_confirmed': bool(trip.get('driver_payment_confirmed')),
            'passenger_rated': trip.get('passenger_rated_at') is not None,
            'driver_rated': trip.get('driver_rated_at') is not None
        }
        
        return jsonify({'data': trip_data}), 200
        
    except Exception as e:
        print(f"Error getting current trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/earnings', methods=['GET'])
def get_earnings():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    period = request.args.get('period', 'week')
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT id FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({'data': None}), 200
        
        if period == 'today':
            date_filter = "DATE(completed_at) = CURDATE()"
        elif period == 'week':
            date_filter = "YEARWEEK(completed_at, 1) = YEARWEEK(CURDATE(), 1)"
        else:
            date_filter = "MONTH(completed_at) = MONTH(CURDATE()) AND YEAR(completed_at) = YEAR(CURDATE())"
        
        cursor.execute(f"""
            SELECT 
                COALESCE(SUM(estimated_price * 0.75), 0) as driver_earnings,
                COUNT(*) as total_trips,
                COALESCE(AVG(estimated_price * 0.75), 0) as avg_per_trip
            FROM trips 
            WHERE driver_id = %s AND status = 'completed' AND {date_filter}
        """, (driver['id'],))
        
        earnings_data = cursor.fetchone()
        
        cursor.execute(f"""
            SELECT 
                DATE(completed_at) as day,
                COALESCE(SUM(estimated_price * 0.75), 0) as earnings,
                COUNT(*) as trips
            FROM trips 
            WHERE driver_id = %s AND status = 'completed' AND {date_filter}
            GROUP BY DATE(completed_at)
            ORDER BY day DESC
        """, (driver['id'],))
        
        daily_breakdown = []
        for row in cursor.fetchall():
            daily_breakdown.append({
                'day': row['day'].strftime('%A') if row['day'] else '',
                'earnings': float(row['earnings']),
                'trips': row['trips']
            })
        
        return jsonify({
            'data': {
                'driver_earnings': float(earnings_data['driver_earnings']),
                'total_trips': earnings_data['total_trips'],
                'avg_per_trip': float(earnings_data['avg_per_trip']),
                'daily_breakdown': daily_breakdown
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting earnings: {e}")
        return jsonify({'data': None}), 200
    finally:
        cursor.close()

@driver_bp.route('/stats', methods=['GET'])
def get_stats():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        
        if not driver:
            return jsonify({
                'data': {
                    'total_trips': 0,
                    'avg_rating': 5.0,
                    'acceptance_rate': 100,
                    'cancellation_rate': 0
                }
            }), 200
        
        total_trips = driver['total_trips'] or 0
        total_accepted = total_trips
        total_rejected = 0
        
        try:
            cursor.execute("""
                SELECT COUNT(*) as total_accepted 
                FROM trips 
                WHERE driver_id = %s AND status IN ('completed', 'in_progress', 'driver_assigned')
            """, (driver['id'],))
            total_accepted = cursor.fetchone()['total_accepted'] or 0
            
            cursor.execute("""
                SELECT COUNT(*) as total_rejected 
                FROM trips 
                WHERE rejected_drivers IS NOT NULL AND JSON_CONTAINS(rejected_drivers, %s)
            """, (json.dumps(str(driver['id'])),))
            total_rejected = cursor.fetchone()['total_rejected'] or 0
        except:
            pass
        
        total_requests = total_accepted + total_rejected
        acceptance_rate = (total_accepted / total_requests * 100) if total_requests > 0 else 100
        
        return jsonify({
            'data': {
                'total_trips': int(driver['total_trips']) if driver['total_trips'] else 0,
                'avg_rating': float(driver['rating']) if driver['rating'] else 5.0,
                'acceptance_rate': round(acceptance_rate, 2),
                'cancellation_rate': float(driver['cancellation_rate']) if driver['cancellation_rate'] else 0.0
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@driver_bp.route('/scheduled-trips', methods=['GET'])
def get_scheduled_trips():
    return jsonify({'data': {'trips': []}}), 200

@driver_bp.route('/payment-info/<trip_id>', methods=['GET'])
def get_driver_payment_info(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute('SELECT * FROM drivers WHERE user_id = %s', (user['id'],))
        driver = cursor.fetchone()
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        cursor.execute("""
            SELECT d.pagomovil_phone, d.pagomovil_ci, d.pagomovil_bank,
                   t.estimated_price, t.passenger_id, u.full_name as passenger_name
            FROM trips t
            JOIN drivers d ON t.driver_id = d.id
            JOIN users u ON t.passenger_id = u.id
            WHERE t.id = %s AND d.user_id = %s
        """, (trip_id, user['id']))
        
        payment_info = cursor.fetchone()
        
        if not payment_info:
            return jsonify({'error': 'Trip not found or not assigned to you'}), 404
        
        return jsonify({
            'data': {
                'pagomovil': {
                    'phone': payment_info['pagomovil_phone'] or '',
                    'ci': payment_info['pagomovil_ci'] or '',
                    'bank': payment_info['pagomovil_bank'] or ''
                },
                'amount': float(payment_info['estimated_price']),
                'passenger_name': payment_info['passenger_name']
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting payment info: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
