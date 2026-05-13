
from flask import Blueprint, request, jsonify, g
from utils.helpers import get_user_from_token, generate_trip_id
from datetime import datetime
import aiohttp
import polyline
import math
from math import radians, sin, cos, sqrt, atan2
import requests

trips_bp = Blueprint('trips', __name__)

class RouteService:
    def __init__(self):
        self.osrm_url = "https://router.project-osrm.org/route/v1/driving"
        self.route_cache = {}
        self.cache_ttl = 300

    def calculate_distance_haversine(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        lat1_rad = radians(lat1)
        lng1_rad = radians(lng1)
        lat2_rad = radians(lat2)
        lng2_rad = radians(lng2)
        dlat = lat2_rad - lat1_rad
        dlng = lng2_rad - lng1_rad
        a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlng/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        return 6371 * c

    def calculate_route_sync(self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> dict:
        cache_key = f"{origin_lat},{origin_lng}|{dest_lat},{dest_lng}"
        if cache_key in self.route_cache:
            cached = self.route_cache[cache_key]
            if datetime.now().timestamp() - cached["timestamp"] < self.cache_ttl:
                return cached["data"]
        route_data = self._fetch_osrm_route(origin_lat, origin_lng, dest_lat, dest_lng)
        if route_data:
            self.route_cache[cache_key] = {
                "timestamp": datetime.now().timestamp(),
                "data": route_data
            }
            return route_data
        return self._calculate_direct_route(origin_lat, origin_lng, dest_lat, dest_lng)

    def _fetch_osrm_route(self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> dict:
        try:
            url = f"{self.osrm_url}/{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
            params = {
                "overview": "full",
                "steps": "false",
                "geometries": "polyline"
            }
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    route = data["routes"][0]
                    geometry_polyline = route.get("geometry", "")
                    if geometry_polyline:
                        decoded = polyline.decode(geometry_polyline)
                        geometry_points = [[coord[0], coord[1]] for coord in decoded]
                    else:
                        geometry_points = [[origin_lat, origin_lng], [dest_lat, dest_lng]]
                    return {
                        "success": True,
                        "distance_km": round(route["distance"] / 1000, 2),
                        "duration_min": round(route["duration"] / 60, 2),
                        "distance_meters": route["distance"],
                        "duration_seconds": route["duration"],
                        "geometry": geometry_points,
                        "polyline": geometry_polyline,
                        "source": "osrm",
                        "is_estimate": False
                    }
            return None
        except Exception as e:
            print(f"Error fetching OSRM route: {e}")
            return None

    def _calculate_direct_route(self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> dict:
        direct_distance = self.calculate_distance_haversine(origin_lat, origin_lng, dest_lat, dest_lng)
        avg_speed_kmh = 30
        duration_hours = direct_distance / avg_speed_kmh
        duration_min = duration_hours * 60
        route_factor = 1.25
        adjusted_distance = direct_distance * route_factor
        adjusted_duration = duration_min * route_factor
        geometry_points = self._generate_intermediate_points(origin_lat, origin_lng, dest_lat, dest_lng, num_points=30)
        return {
            "success": True,
            "distance_km": round(adjusted_distance, 2),
            "duration_min": round(adjusted_duration, 2),
            "distance_meters": round(adjusted_distance * 1000, 2),
            "duration_seconds": round(adjusted_duration * 60, 2),
            "geometry": geometry_points,
            "polyline": None,
            "source": "direct",
            "is_estimate": True
        }

    def _generate_intermediate_points(self, lat1: float, lng1: float, lat2: float, lng2: float, num_points: int = 30) -> list:
        points = []
        for i in range(num_points + 1):
            t = i / num_points
            lat = lat1 + (lat2 - lat1) * t
            lng = lng1 + (lng2 - lng1) * t
            if 0 < t < 1:
                curve = math.sin(t * math.pi) * 0.002
                lat += curve * (1 if t < 0.5 else -1)
                lng += curve * 0.5
            points.append([lat, lng])
        return points

    def estimate_price(self, distance_km: float, duration_min: float, vehicle_type: str = "economy", surge_multiplier: float = 1.0) -> dict:
        service_pricing = {
            "economy": {"base": 1.50, "per_km": 0.25, "per_min": 0.10, "min": 2.50},
            "comfort": {"base": 2.50, "per_km": 0.35, "per_min": 0.15, "min": 4.00},
            "premium": {"base": 4.00, "per_km": 0.55, "per_min": 0.22, "min": 7.00}
        }
        pricing = service_pricing.get(vehicle_type, service_pricing["economy"])
        price = (pricing["base"] + (distance_km * pricing["per_km"]) + (duration_min * pricing["per_min"])) * surge_multiplier
        final_price = max(price, pricing["min"])
        return {
            "base_fare": round(pricing["base"], 2),
            "distance_fare": round(distance_km * pricing["per_km"], 2),
            "time_fare": round(duration_min * pricing["per_min"], 2),
            "surge_multiplier": surge_multiplier,
            "subtotal": round(price, 2),
            "total": round(final_price, 2),
            "min_fare": pricing["min"],
            "currency": "USD",
            "driver_earnings": round(final_price * 0.75, 2),
            "platform_fee": round(final_price * 0.25, 2)
        }

route_service = RouteService()

@trips_bp.route('/calculate-route', methods=['POST'])
def calculate_route():
    data = request.json
    origin_lat = data.get('origin_lat')
    origin_lng = data.get('origin_lng')
    dest_lat = data.get('dest_lat')
    dest_lng = data.get('dest_lng')
    vehicle_type = data.get('vehicle_type', 'economy')
    
    if origin_lat is None or origin_lng is None or dest_lat is None or dest_lng is None:
        origin = data.get('origin')
        destination = data.get('destination')
        if origin and destination:
            origin_lat = origin.get('lat')
            origin_lng = origin.get('lng')
            dest_lat = destination.get('lat')
            dest_lng = destination.get('lng')
    
    if origin_lat is None or origin_lng is None:
        return jsonify({'error': 'Coordenadas de origen inválidas'}), 400
    if dest_lat is None or dest_lng is None:
        return jsonify({'error': 'Coordenadas de destino inválidas'}), 400
    
    try:
        route_info = route_service.calculate_route_sync(float(origin_lat), float(origin_lng), float(dest_lat), float(dest_lng))
        if not route_info.get('success'):
            return jsonify({'error': 'Error al calcular la ruta'}), 500
        
        price_info = route_service.estimate_price(route_info['distance_km'], route_info['duration_min'], vehicle_type)
        geometry_for_map = route_info.get('geometry', [])
        
        response_data = {
            'distance_km': route_info['distance_km'],
            'duration_minutes': route_info['duration_min'],
            'price_estimate': price_info['total'],
            'base_price': price_info['base_fare'],
            'surge_multiplier': price_info['surge_multiplier'],
            'surge_applied': price_info['surge_multiplier'] > 1,
            'geometry': geometry_for_map,
            'polyline': route_info.get('polyline'),
            'source': route_info.get('source', 'unknown'),
            'is_estimate': route_info.get('is_estimate', True)
        }
        return jsonify({'data': response_data}), 200
    except Exception as e:
        print(f"Error calculating route: {e}")
        return jsonify({'error': f'Error al calcular ruta: {str(e)}'}), 500

@trips_bp.route('/calculate-route/direct', methods=['POST'])
def calculate_direct_distance():
    data = request.json
    origin = data.get('origin', {})
    destination = data.get('destination', {})
    origin_lat = origin.get('lat')
    origin_lng = origin.get('lng')
    dest_lat = destination.get('lat')
    dest_lng = destination.get('lng')
    
    if None in [origin_lat, origin_lng, dest_lat, dest_lng]:
        return jsonify({'error': 'Coordenadas inválidas'}), 400
    
    distance = route_service.calculate_distance_haversine(origin_lat, origin_lng, dest_lat, dest_lng)
    vehicle_type = data.get('vehicle_type', 'economy')
    estimated_duration_min = (distance / 30) * 60
    price_info = route_service.estimate_price(distance, estimated_duration_min, vehicle_type)
    geometry = route_service._generate_intermediate_points(origin_lat, origin_lng, dest_lat, dest_lng, num_points=20)
    
    return jsonify({
        'success': True,
        'data': {
            'distance_km': round(distance, 2),
            'duration_minutes': round(estimated_duration_min, 1),
            'geometry': [[p[0], p[1]] for p in geometry],
            'pricing': price_info
        }
    }), 200

@trips_bp.route('/trip/<trip_id>/route', methods=['GET'])
def get_trip_route(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT origin_lat, origin_lng, dest_lat, dest_lng, 
                   estimated_distance, estimated_duration
            FROM trips 
            WHERE id = %s AND (passenger_id = %s OR driver_id IN 
                (SELECT id FROM drivers WHERE user_id = %s))
        """, (trip_id, user['id'], user['id']))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Viaje no encontrado'}), 404
        
        route_info = route_service.calculate_route_sync(
            float(trip['origin_lat']),
            float(trip['origin_lng']),
            float(trip['dest_lat']),
            float(trip['dest_lng'])
        )
        
        return jsonify({
            'success': True,
            'data': {
                'origin': {
                    'lat': float(trip['origin_lat']),
                    'lng': float(trip['origin_lng'])
                },
                'destination': {
                    'lat': float(trip['dest_lat']),
                    'lng': float(trip['dest_lng'])
                },
                'distance_km': route_info.get('distance_km', float(trip['estimated_distance'] or 0)),
                'duration_minutes': route_info.get('duration_min', float(trip['estimated_duration'] or 0)),
                'geometry': route_info.get('geometry', [])
            }
        }), 200
    except Exception as e:
        print(f"Error getting trip route: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/request', methods=['POST'])
def request_trip():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    required_fields = ['origin_lat', 'origin_lng', 'dest_lat', 'dest_lng', 'origin_address', 'dest_address']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Campo requerido: {field}'}), 400
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT id, status FROM trips 
            WHERE passenger_id = %s AND status NOT IN ('completed', 'cancelled')
        """, (user['id'],))
        existing_trip = cursor.fetchone()
        
        if existing_trip:
            return jsonify({
                'error': 'Ya tienes un viaje activo. Completa o cancela el viaje actual antes de solicitar otro.',
                'data': {
                    'trip_id': existing_trip['id'],
                    'status': existing_trip['status']
                }
            }), 400
        
        origin_lat = float(data['origin_lat'])
        origin_lng = float(data['origin_lng'])
        dest_lat = float(data['dest_lat'])
        dest_lng = float(data['dest_lng'])
        
        if not (-90 <= origin_lat <= 90) or not (-180 <= origin_lng <= 180):
            return jsonify({'error': 'Coordenadas de origen inválidas'}), 400
        if not (-90 <= dest_lat <= 90) or not (-180 <= dest_lng <= 180):
            return jsonify({'error': 'Coordenadas de destino inválidas'}), 400
        if origin_lat == dest_lat and origin_lng == dest_lng:
            return jsonify({'error': 'El origen y el destino no pueden ser el mismo lugar'}), 400
        
        vehicle_type = data.get('vehicle_type', 'economy')
        payment_method = data.get('payment_method', 'cash')
        
        route_info = route_service.calculate_route_sync(origin_lat, origin_lng, dest_lat, dest_lng)
        price_info = route_service.estimate_price(route_info['distance_km'], route_info['duration_min'], vehicle_type)
        
        estimated_price = price_info['total']
        estimated_distance = route_info['distance_km']
        estimated_duration = route_info['duration_min']
        trip_id = generate_trip_id()
        
        cursor.execute("""
            INSERT INTO trips 
            (id, passenger_id, origin_lat, origin_lng, dest_lat, dest_lng,
             origin_address, dest_address, vehicle_type, payment_method,
             estimated_price, estimated_distance, estimated_duration, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            trip_id,
            user['id'],
            origin_lat,
            origin_lng,
            dest_lat,
            dest_lng,
            data['origin_address'],
            data['dest_address'],
            vehicle_type,
            payment_method,
            estimated_price,
            estimated_distance,
            estimated_duration,
            'searching'
        ))
        g.db.commit()
        
        print(f'🆕 New trip created: {trip_id} for passenger: {user["id"]}')
        
        cursor.execute("""
            SELECT t.*, 
                   u_driver.full_name as driver_name,
                   u_driver.phone_number as driver_phone,
                   d.id as driver_table_id,
                   d.rating as driver_rating,
                   d.current_lat as driver_lat,
                   d.current_lng as driver_lng,
                   d.vehicle_make, 
                   d.vehicle_model, 
                   d.vehicle_plate, 
                   d.vehicle_color
            FROM trips t
            LEFT JOIN drivers d ON t.driver_id = d.id
            LEFT JOIN users u_driver ON d.user_id = u_driver.id
            WHERE t.id = %s
        """, (trip_id,))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Error al recuperar los datos del viaje'}), 500
        
        response_data = {
            'trip_id': trip['id'],
            'status': trip['status'],
            'estimated_price': float(trip['estimated_price']) if trip['estimated_price'] else 0.0,
            'estimated_distance': float(trip['estimated_distance']) if trip['estimated_distance'] else 0.0,
            'estimated_duration': int(trip['estimated_duration']) if trip['estimated_duration'] else 0
        }
        return jsonify({'data': response_data}), 201
        
    except ValueError as e:
        g.db.rollback()
        print(f"Value error in request_trip: {e}")
        return jsonify({'error': 'Formato de coordenadas inválido'}), 400
    except Exception as e:
        g.db.rollback()
        print(f"Error creating trip: {e}")
        return jsonify({'error': f'Error al crear el viaje: {str(e)}'}), 500
    finally:
        cursor.close()

@trips_bp.route('/current', methods=['GET'])
def get_current_trip():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT t.*, 
                   u_driver.full_name as driver_name,
                   u_driver.phone_number as driver_phone,
                   d.id as driver_table_id,
                   d.rating as driver_rating,
                   d.current_lat as driver_lat,
                   d.current_lng as driver_lng,
                   d.vehicle_make, d.vehicle_model, d.vehicle_plate, d.vehicle_color,
                   d.pagomovil_phone, d.pagomovil_ci, d.pagomovil_bank,
                   t.passenger_payment_confirmed, t.driver_payment_confirmed,
                   t.passenger_rated_at, t.driver_rated_at
            FROM trips t
            LEFT JOIN drivers d ON t.driver_id = d.id
            LEFT JOIN users u_driver ON d.user_id = u_driver.id
            WHERE t.passenger_id = %s AND t.status NOT IN ('completed', 'cancelled')
            ORDER BY t.created_at DESC LIMIT 1
        """, (user['id'],))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'data': None}), 200
        
        driver_data = None
        if trip.get('driver_id') and trip.get('driver_name'):
            driver_data = {
                'id': str(trip['driver_table_id']) if trip.get('driver_table_id') else None,
                'name': trip['driver_name'],
                'phone': trip['driver_phone'] or '',
                'rating': float(trip['driver_rating']) if trip['driver_rating'] else 5.0,
                'vehicle': {
                    'make': trip['vehicle_make'] or 'Unknown',
                    'model': trip['vehicle_model'] or 'Unknown',
                    'plate': trip['vehicle_plate'] or 'Unknown',
                    'color': trip['vehicle_color'] or 'Unknown'
                }
            }
            if trip['driver_lat'] and trip['driver_lng']:
                driver_data['location'] = {
                    'lat': float(trip['driver_lat']),
                    'lng': float(trip['driver_lng'])
                }
                driver_data['eta'] = 5
            if trip.get('pagomovil_phone'):
                driver_data['pagomovil'] = {
                    'phone': trip['pagomovil_phone'],
                    'ci': trip['pagomovil_ci'],
                    'bank': trip['pagomovil_bank']
                }
        
        response_data = {
            'id': trip['id'],
            'status': trip['status'],
            'origin': {
                'lat': float(trip['origin_lat']),
                'lng': float(trip['origin_lng']),
                'address': trip['origin_address']
            },
            'destination': {
                'lat': float(trip['dest_lat']),
                'lng': float(trip['dest_lng']),
                'address': trip['dest_address']
            },
            'driver': driver_data,
            'price': float(trip['estimated_price']) if trip['estimated_price'] else 0.0,
            'distance_km': float(trip['estimated_distance']) if trip['estimated_distance'] else 0.0,
            'duration_minutes': int(trip['estimated_duration']) if trip['estimated_duration'] else 0,
            'created_at': str(trip['created_at']) if trip['created_at'] else '',
            'payment_method': trip.get('payment_method', 'cash'),
            'vehicle_type': trip.get('vehicle_type', 'economy'),
            'passenger_payment_confirmed': bool(trip.get('passenger_payment_confirmed')),
            'driver_payment_confirmed': bool(trip.get('driver_payment_confirmed')),
            'passenger_rated': trip.get('passenger_rated_at') is not None,
            'driver_rated': trip.get('driver_rated_at') is not None
        }
        return jsonify({'data': response_data}), 200
    except Exception as e:
        print(f"Error getting current trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/history', methods=['GET'])
def get_history():
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 20, type=int)
    status = request.args.get('status')
    
    cursor = g.db.cursor()
    
    try:
        query = """
            SELECT t.*,
                   u_driver.full_name as driver_name,
                   d.vehicle_make, d.vehicle_model, d.vehicle_plate
            FROM trips t
            LEFT JOIN drivers d ON t.driver_id = d.id
            LEFT JOIN users u_driver ON d.user_id = u_driver.id
            WHERE t.passenger_id = %s
        """
        params = [user['id']]
        
        if status:
            query += ' AND t.status = %s'
            params.append(status)
        
        query += ' ORDER BY t.created_at DESC LIMIT %s OFFSET %s'
        params.extend([limit, skip])
        
        cursor.execute(query, params)
        trips_data = cursor.fetchall()
        
        formatted_trips = []
        for trip in trips_data:
            formatted_trips.append({
                'trip_id': trip['id'],
                'status': trip['status'],
                'origin_address': trip['origin_address'],
                'destination_address': trip['dest_address'],
                'total_price': float(trip['estimated_price']) if trip['estimated_price'] else 0.0,
                'created_at': str(trip['created_at']) if trip['created_at'] else '',
                'passenger_rating': trip.get('passenger_rating'),
                'driver_rating': trip.get('driver_rating'),
                'driver': {
                    'name': trip['driver_name'] if trip['driver_name'] else 'Unknown',
                    'vehicle': f"{trip['vehicle_make']} {trip['vehicle_model']}" if trip['vehicle_make'] else 'Unknown'
                }
            })
        
        return jsonify({
            'data': {
                'trips': formatted_trips,
                'total': len(formatted_trips)
            }
        }), 200
    except Exception as e:
        print(f"Error getting history: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/<trip_id>/cancel', methods=['POST'])
def cancel_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    reason = data.get('reason', 'Cancelled by user')
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            UPDATE trips SET status = %s, cancellation_reason = %s, cancelled_at = NOW()
            WHERE id = %s AND passenger_id = %s AND status NOT IN ('completed', 'cancelled')
        """, ('cancelled', reason, trip_id, user['id']))
        g.db.commit()
        print(f'❌ Trip {trip_id} cancelled by passenger')
        return jsonify({'data': {'message': 'Trip cancelled'}}), 200
    except Exception as e:
        g.db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/<trip_id>/rate', methods=['POST'])
def rate_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    rating = data.get('rating')
    comment = data.get('comment')
    user_role = data.get('role', 'passenger')
    
    if rating is None or rating < 1 or rating > 5:
        return jsonify({'error': 'Rating must be between 1 and 5'}), 400
    
    cursor = g.db.cursor()
    
    try:
        if user_role == 'passenger':
            cursor.execute("""
                UPDATE trips 
                SET passenger_rating = %s, 
                    passenger_comment = %s,
                    passenger_rated_at = NOW()
                WHERE id = %s AND passenger_id = %s AND status IN ('completed', 'in_progress', 'pending_payment')
            """, (rating, comment, trip_id, user['id']))
            
            cursor.execute("""
                UPDATE drivers d
                SET rating = (
                    SELECT AVG(passenger_rating) 
                    FROM trips 
                    WHERE driver_id = d.id AND passenger_rating IS NOT NULL
                )
                WHERE d.id = (
                    SELECT driver_id FROM trips WHERE id = %s
                )
            """, (trip_id,))
        else:
            cursor.execute("""
                UPDATE trips 
                SET driver_rating = %s, 
                    driver_comment = %s,
                    driver_rated_at = NOW()
                WHERE id = %s AND driver_id IN (
                    SELECT id FROM drivers WHERE user_id = %s
                ) AND status IN ('completed', 'in_progress', 'pending_payment')
            """, (rating, comment, trip_id, user['id']))
        
        g.db.commit()
        
        cursor.execute("""
            SELECT status, passenger_rated_at, driver_rated_at
            FROM trips 
            WHERE id = %s
        """, (trip_id,))
        trip = cursor.fetchone()
        
        if trip['passenger_rated_at'] is not None and trip['driver_rated_at'] is not None:
            if trip['status'] != 'completed':
                cursor.execute("""
                    UPDATE trips 
                    SET status = 'completed', completed_at = NOW() 
                    WHERE id = %s
                """, (trip_id,))
                g.db.commit()
                print(f'✅ Trip {trip_id} fully completed after both ratings')
        
        return jsonify({'data': {'message': 'Rating submitted successfully'}}), 200
        
    except Exception as e:
        g.db.rollback()
        print(f"Error rating trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/driver/trips/<trip_id>/complete', methods=['POST'])
def driver_complete_trip(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT t.*, d.id as driver_table_id 
            FROM trips t
            JOIN drivers d ON t.driver_id = d.id
            WHERE t.id = %s AND d.user_id = %s
        """, (trip_id, user['id']))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Trip not found or not assigned to you'}), 404
        
        if trip['status'] != 'in_progress':
            return jsonify({'error': f'Cannot complete trip with status: {trip["status"]}'}), 400
        
        # Cambiar a 'pending_payment' para que el conductor confirme el pago
        cursor.execute("""
            UPDATE trips 
            SET status = 'pending_payment', 
                actual_end_time = NOW()
            WHERE id = %s
        """, (trip_id,))
        g.db.commit()
        
        print(f'✅ Trip {trip_id} completed, waiting for payment confirmation')
        
        return jsonify({
            'data': {
                'id': trip_id,
                'status': 'pending_payment',
                'message': 'Trip completed, waiting for payment confirmation'
            }
        }), 200
        
    except Exception as e:
        g.db.rollback()
        print(f"Error completing trip: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()


@trips_bp.route('/driver/trips/<trip_id>/confirm-payment', methods=['POST'])
def driver_confirm_payment(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT t.*, d.id as driver_table_id 
            FROM trips t
            JOIN drivers d ON t.driver_id = d.id
            WHERE t.id = %s AND d.user_id = %s
        """, (trip_id, user['id']))
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
        
        cursor.execute("SELECT passenger_payment_confirmed FROM trips WHERE id = %s", (trip_id,))
        trip_data = cursor.fetchone()
        
        if trip_data and trip_data.get('passenger_payment_confirmed'):
            cursor.execute("""
                UPDATE trips 
                SET status = 'waiting_for_rating' 
                WHERE id = %s
            """, (trip_id,))
            g.db.commit()
            print(f'💰 Both confirmed payment for trip {trip_id}, waiting for rating')
        else:
            print(f'💰 Driver confirmed payment for trip {trip_id}, waiting for passenger confirmation')
        
        return jsonify({
            'data': {
                'id': trip_id,
                'status': 'waiting_for_rating' if (trip_data and trip_data.get('passenger_payment_confirmed')) else 'pending_payment',
                'message': 'Payment confirmed by driver'
            }
        }), 200
        
    except Exception as e:
        g.db.rollback()
        print(f"Error confirming payment: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()


@trips_bp.route('/passenger/trips/<trip_id>/confirm-payment', methods=['POST'])
def passenger_confirm_payment(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT t.* 
            FROM trips t
            WHERE t.id = %s AND t.passenger_id = %s
        """, (trip_id, user['id']))
        trip = cursor.fetchone()
        
        if not trip:
            return jsonify({'error': 'Trip not found'}), 404
        
        if trip['status'] != 'pending_payment':
            return jsonify({'error': f'Invalid status for payment confirmation: {trip["status"]}'}), 400
        
        cursor.execute("""
            UPDATE trips 
            SET passenger_payment_confirmed = TRUE,
                passenger_payment_confirmed_at = NOW()
            WHERE id = %s
        """, (trip_id,))
        g.db.commit()
        
        cursor.execute("SELECT driver_payment_confirmed FROM trips WHERE id = %s", (trip_id,))
        trip_data = cursor.fetchone()
        
        if trip_data and trip_data.get('driver_payment_confirmed'):
            cursor.execute("""
                UPDATE trips 
                SET status = 'waiting_for_rating' 
                WHERE id = %s
            """, (trip_id,))
            g.db.commit()
            print(f'💰 Both confirmed payment for trip {trip_id}, waiting for rating')
        else:
            print(f'💰 Passenger confirmed payment for trip {trip_id}, waiting for driver confirmation')
        
        return jsonify({
            'data': {
                'id': trip_id,
                'status': 'waiting_for_rating' if (trip_data and trip_data.get('driver_payment_confirmed')) else 'pending_payment',
                'message': 'Payment confirmed by passenger'
            }
        }), 200
        
    except Exception as e:
        g.db.rollback()
        print(f"Error confirming passenger payment: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/passenger/payment-info/<trip_id>', methods=['GET'])
def get_passenger_payment_info(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
        cursor.execute("""
            SELECT d.pagomovil_phone, d.pagomovil_ci, d.pagomovil_bank,
                   t.estimated_price, t.driver_id, u.full_name as driver_name
            FROM trips t
            JOIN drivers d ON t.driver_id = d.id
            JOIN users u ON d.user_id = u.id
            WHERE t.id = %s AND t.passenger_id = %s
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
                'driver_name': payment_info['driver_name']
            }
        }), 200
        
    except Exception as e:
        print(f"Error getting payment info: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@trips_bp.route('/driver/payment-info/<trip_id>', methods=['GET'])
def get_driver_payment_info(trip_id):
    user = get_user_from_token(request.headers.get('Authorization'))
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    cursor = g.db.cursor()
    
    try:
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
