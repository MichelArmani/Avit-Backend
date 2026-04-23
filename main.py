"""
Backend Principal - Sistema de Transporte Venezuela
Arquitectura basada en archivos JSON con operaciones atómicas
Incluye servicio de rutas con OSRM/GraphHopper
"""
import asyncio
import json
import os
import shutil
import uuid
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from contextlib import contextmanager
import sys
if sys.platform == 'win32':
    import portalocker
else:
    import fcntl
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import logging
import aiohttp
import polyline
from math import radians, sin, cos, sqrt, atan2

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import bcrypt
import uvicorn

# ============================================
# CONFIGURACIÓN
# ============================================

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    LOCKS_DIR = BASE_DIR / "locks"
    
    # APIs de rutas
    OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
    GRAPHHOPPER_KEY = os.environ.get("GRAPHHOPPER_KEY", "")
    GRAPHHOPPER_URL = "https://graphhopper.com/api/1/route"
    OPENROUTE_KEY = os.environ.get("OPENROUTE_KEY", "")
    OPENROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car"
    
    # Google Maps API Key
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "YOUR_GOOGLE_MAPS_API_KEY")
    
    @classmethod
    def setup_directories(cls):
        """Crear directorios necesarios"""
        dirs_to_create = [
            cls.DATA_DIR / "users" / "passengers" / "premium",
            cls.DATA_DIR / "users" / "passengers" / "normal",
            cls.DATA_DIR / "users" / "drivers",
            cls.DATA_DIR / "trips" / "pending",
            cls.DATA_DIR / "trips" / "active",
            cls.DATA_DIR / "trips" / "completed",
            cls.DATA_DIR / "trips" / "cancelled",
            cls.DATA_DIR / "vehicles",
            cls.DATA_DIR / "payments" / "pending",
            cls.DATA_DIR / "payments" / "completed",
            cls.DATA_DIR / "payments" / "failed",
            cls.DATA_DIR / "ratings",
            cls.DATA_DIR / "promotions",
            cls.DATA_DIR / "notifications",
            cls.DATA_DIR / "system" / "logs",
            cls.LOCKS_DIR
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Directorios inicializados en {cls.DATA_DIR}")

# Inicializar directorios
Config.setup_directories()

# ============================================
# UTILIDADES DE SISTEMA DE ARCHIVOS
# ============================================

class FileLock:
    """Lock basado en archivos para operaciones atómicas con soporte Windows/Linux"""
    
    def __init__(self, lock_name: str):
        safe_name = lock_name.replace('/', '_').replace('\\', '_').replace(':', '_')
        self.lock_file = Config.LOCKS_DIR / f"{safe_name}.lock"
        self.lock_fd = None
        self.is_windows = sys.platform == 'win32'
    
    def acquire(self, timeout: float = 5.0) -> bool:
        start_time = time.time()
        
        try:
            self.lock_fd = open(self.lock_file, 'w')
        except Exception as e:
            logger.error(f"Error abriendo archivo de lock {self.lock_file}: {e}")
            return False
        
        while True:
            try:
                if self.is_windows:
                    portalocker.lock(self.lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
                else:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except Exception:
                if time.time() - start_time > timeout:
                    try:
                        self.lock_fd.close()
                    except:
                        pass
                    self.lock_fd = None
                    return False
                time.sleep(0.1)
    
    def release(self):
        if self.lock_fd:
            try:
                if self.is_windows:
                    portalocker.unlock(self.lock_fd)
                else:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                try:
                    self.lock_fd.close()
                except Exception:
                    pass
                self.lock_fd = None

@contextmanager
def atomic_write(filepath: Path):
    temp_path = filepath.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            yield f
        os.replace(temp_path, filepath)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise e

class JSONStorage:
    """Manejador de almacenamiento JSON con operaciones atómicas"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=10)
    
    @staticmethod
    def generate_id(prefix: str = "") -> str:
        return f"{prefix}{uuid.uuid4().hex[:8]}"
    
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    @staticmethod
    def verify_password(password: str, hash_str: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), hash_str.encode())
        except Exception:
            return False
    
    def read_json(self, filepath: Path) -> Optional[Dict]:
        if not filepath.exists():
            return None
        
        lock = FileLock(str(filepath))
        try:
            if lock.acquire(timeout=2.0):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error leyendo {filepath}: {e}")
        finally:
            lock.release()
        return None
    
    def write_json(self, filepath: Path, data: Dict) -> bool:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        lock = FileLock(str(filepath))
        try:
            if lock.acquire(timeout=5.0):
                with atomic_write(filepath) as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                return True
        except Exception as e:
            logger.error(f"Error escribiendo {filepath}: {e}")
        finally:
            lock.release()
        return False
    
    def delete_json(self, filepath: Path) -> bool:
        if not filepath.exists():
            return False
        
        lock = FileLock(str(filepath))
        try:
            if lock.acquire():
                filepath.unlink()
                return True
        except Exception as e:
            logger.error(f"Error eliminando {filepath}: {e}")
        finally:
            lock.release()
        return False
    
    def find_files(self, directory: Path, pattern: str = "*.json") -> List[Path]:
        if not directory.exists():
            return []
        return list(directory.glob(pattern))
    
    def move_file(self, src: Path, dst: Path) -> bool:
        if not src.exists():
            return False
        
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        lock_src = FileLock(str(src))
        lock_dst = FileLock(str(dst))
        
        try:
            if lock_src.acquire() and lock_dst.acquire():
                os.rename(src, dst)
                return True
        except Exception as e:
            logger.error(f"Error moviendo {src} a {dst}: {e}")
        finally:
            lock_src.release()
            lock_dst.release()
        return False

# ============================================
# SERVICIO DE RUTAS
# ============================================

class RouteService:
    """Servicio para cálculo de rutas usando APIs gratuitas"""
    
    def __init__(self):
        self.route_cache = {}
        self.cache_ttl = 300
    
    async def calculate_route(self, origin: Dict, destination: Dict) -> Dict:
        """Calcula ruta entre dos puntos"""
        cache_key = f"{origin.get('lat')},{origin.get('lng')}|{destination.get('lat')},{destination.get('lng')}"
        
        if cache_key in self.route_cache:
            cached = self.route_cache[cache_key]
            if time.time() - cached["timestamp"] < self.cache_ttl:
                logger.info(f"Usando ruta en caché para {cache_key}")
                return cached["data"]
        
        try:
            route = await self._calculate_osrm(origin, destination)
            if route:
                self.route_cache[cache_key] = {"timestamp": time.time(), "data": route}
                return route
        except Exception as e:
            logger.warning(f"OSRM falló: {e}")
        
        if Config.GRAPHHOPPER_KEY:
            try:
                route = await self._calculate_graphhopper(origin, destination)
                if route:
                    self.route_cache[cache_key] = {"timestamp": time.time(), "data": route}
                    return route
            except Exception as e:
                logger.warning(f"GraphHopper falló: {e}")
        
        if Config.OPENROUTE_KEY:
            try:
                route = await self._calculate_openroute(origin, destination)
                if route:
                    self.route_cache[cache_key] = {"timestamp": time.time(), "data": route}
                    return route
            except Exception as e:
                logger.warning(f"OpenRouteService falló: {e}")
        
        logger.warning(f"Usando cálculo directo para {cache_key}")
        return self._calculate_direct_distance(origin, destination)
    
    async def _calculate_osrm(self, origin: Dict, destination: Dict) -> Optional[Dict]:
        url = f"{Config.OSRM_URL}/{origin['lng']},{origin['lat']};{destination['lng']},{destination['lat']}"
        params = {"overview": "full", "steps": "true", "geometries": "polyline"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == "Ok" and data.get("routes"):
                        route = data["routes"][0]
                        geometry = polyline.decode(route.get("geometry", ""))
                        return {
                            "distance_km": round(route["distance"] / 1000, 2),
                            "duration_min": round(route["duration"] / 60, 2),
                            "distance_meters": route["distance"],
                            "duration_seconds": route["duration"],
                            "geometry": geometry,
                            "source": "osrm"
                        }
        return None
    
    async def _calculate_graphhopper(self, origin: Dict, destination: Dict) -> Optional[Dict]:
        params = {
            "point": [f"{origin['lat']},{origin['lng']}", f"{destination['lat']},{destination['lng']}"],
            "vehicle": "car",
            "locale": "es",
            "key": Config.GRAPHHOPPER_KEY,
            "points_encoded": "true"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(Config.GRAPHHOPPER_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("paths"):
                        path = data["paths"][0]
                        points = polyline.decode(path.get("points", ""))
                        return {
                            "distance_km": round(path["distance"] / 1000, 2),
                            "duration_min": round(path["time"] / 60000, 2),
                            "distance_meters": path["distance"],
                            "duration_seconds": path["time"] / 1000,
                            "geometry": points,
                            "source": "graphhopper"
                        }
        return None
    
    async def _calculate_openroute(self, origin: Dict, destination: Dict) -> Optional[Dict]:
        url = f"{Config.OPENROUTE_URL}/{origin['lng']},{origin['lat']}|{destination['lng']},{destination['lat']}"
        headers = {"Authorization": Config.OPENROUTE_KEY, "Content-Type": "application/json"}
        params = {"format": "json", "geometry": "true", "instructions": "true"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("features"):
                        feature = data["features"][0]
                        properties = feature.get("properties", {})
                        segments = properties.get("segments", [{}])[0]
                        geometry = feature.get("geometry", {}).get("coordinates", [])
                        return {
                            "distance_km": round(segments.get("distance", 0) / 1000, 2),
                            "duration_min": round(segments.get("duration", 0) / 60, 2),
                            "distance_meters": segments.get("distance", 0),
                            "duration_seconds": segments.get("duration", 0),
                            "geometry": [(coord[1], coord[0]) for coord in geometry],
                            "source": "openroute"
                        }
        return None
    
    def _calculate_direct_distance(self, origin: Dict, destination: Dict) -> Dict:
        lat1 = radians(origin.get("lat", 0))
        lng1 = radians(origin.get("lng", 0))
        lat2 = radians(destination.get("lat", 0))
        lng2 = radians(destination.get("lng", 0))
        
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        distance_km = 6371 * c
        
        avg_speed_kmh = 30
        duration_min = (distance_km / avg_speed_kmh) * 60
        route_factor = 1.25
        
        return {
            "distance_km": round(distance_km * route_factor, 2),
            "duration_min": round(duration_min * route_factor, 2),
            "distance_meters": round(distance_km * route_factor * 1000, 2),
            "duration_seconds": round(duration_min * route_factor * 60, 2),
            "geometry": [[origin.get("lat", 0), origin.get("lng", 0)], [destination.get("lat", 0), destination.get("lng", 0)]],
            "source": "direct",
            "is_estimate": True
        }
    
    def estimate_price(self, route_info: Dict, service_type: str, surge_multiplier: float = 1.0) -> Dict:
        service_pricing = {
            "uberx": {"base": 1.50, "per_km": 0.25, "per_min": 0.10, "min": 2.50},
            "comfort": {"base": 2.50, "per_km": 0.35, "per_min": 0.15, "min": 4.00},
            "black": {"base": 4.00, "per_km": 0.50, "per_min": 0.20, "min": 6.50},
            "moto": {"base": 1.00, "per_km": 0.20, "per_min": 0.05, "min": 2.00}
        }
        
        pricing = service_pricing.get(service_type, service_pricing["uberx"])
        distance_km = route_info.get("distance_km", 0)
        duration_min = route_info.get("duration_min", 0)
        
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
            "currency": "USD"
        }

# ============================================
# SERVICIO DE GOOGLE MAPS
# ============================================

class GoogleMapsService:
    """Servicio para geocodificación y autocompletar usando Google Maps API"""
    
    def __init__(self):
        self.api_key = Config.GOOGLE_MAPS_API_KEY
        self.geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
        self.places_url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        self.place_details_url = "https://maps.googleapis.com/maps/api/place/details/json"
    
    async def geocode_address(self, address: str) -> Optional[Dict]:
        """Convierte una dirección en coordenadas"""
        params = {
            "address": address,
            "key": self.api_key
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.geocode_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK" and data.get("results"):
                        result = data["results"][0]
                        location = result["geometry"]["location"]
                        return {
                            "address": result["formatted_address"],
                            "coordinates": {
                                "lat": location["lat"],
                                "lng": location["lng"]
                            },
                            "place_id": result.get("place_id")
                        }
        return None
    
    async def reverse_geocode(self, lat: float, lng: float) -> Optional[Dict]:
        """Convierte coordenadas en una dirección"""
        params = {
            "latlng": f"{lat},{lng}",
            "key": self.api_key
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.geocode_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK" and data.get("results"):
                        result = data["results"][0]
                        return {
                            "address": result["formatted_address"],
                            "coordinates": {"lat": lat, "lng": lng},
                            "place_id": result.get("place_id")
                        }
        return None
    
    async def get_place_predictions(self, input_text: str, location: Dict = None) -> List[Dict]:
        """Obtiene predicciones de lugares para autocompletar"""
        params = {
            "input": input_text,
            "key": self.api_key,
            "language": "es"
        }
        
        if location:
            params["location"] = f"{location.get('lat')},{location.get('lng')}"
            params["radius"] = 50000
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.places_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK":
                        return data.get("predictions", [])
        return []
    
    async def get_place_details(self, place_id: str) -> Optional[Dict]:
        """Obtiene detalles de un lugar por su ID"""
        params = {
            "place_id": place_id,
            "key": self.api_key,
            "fields": "formatted_address,geometry,name,place_id"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.place_details_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK":
                        result = data["result"]
                        location = result["geometry"]["location"]
                        return {
                            "address": result["formatted_address"],
                            "name": result.get("name", ""),
                            "coordinates": {
                                "lat": location["lat"],
                                "lng": location["lng"]
                            },
                            "place_id": place_id
                        }
        return None

# ============================================
# SERVICIOS PRINCIPALES
# ============================================

class UserService:
    def __init__(self, storage: JSONStorage):
        self.storage = storage
    
    def create_passenger(self, phone: str, password: str, full_name: str, email: Optional[str] = None) -> Dict:
        if self._phone_exists(phone):
            raise ValueError("Teléfono ya registrado")
        
        user_id = self.storage.generate_id("pax_")
        
        user_data = {
            "user_id": user_id,
            "phone": phone,
            "email": email,
            "password_hash": self.storage.hash_password(password),
            "full_name": full_name,
            "tier": "normal",
            "created_at": datetime.utcnow().isoformat(),
            "verified": False,
            "profile": {"photo_url": None, "preferred_language": "es", "preferred_payment": "cash"},
            "stats": {
                "total_trips": 0, "total_spent": 0.0, "avg_rating": 0.0,
                "member_since": datetime.utcnow().strftime("%Y-%m-%d"),
                "trips_this_month": 0, "spent_this_month": 0.0, "saved_this_year": 0.0,
                "cancellation_rate": 0.0, "favorite_drivers": [], "most_used_service": None
            },
            "payment_methods": [{"id": self.storage.generate_id("pay_"), "type": "cash", "is_default": True}],
            "wallet": {"balance": 0.0, "currency": "USD", "transactions": []},
            "favorite_places": [],
            "recent_places": [],
            "promotions_used": [],
            "settings": {
                "notifications": {"trip_updates": True, "promotions": True, "news": False, "email": True, "push": True},
                "privacy": {"share_location": True, "share_trip_details": False},
                "language": "es", "currency": "USD"
            },
            "last_active": datetime.utcnow().isoformat(),
            "device_tokens": [],
            "account_status": "active"
        }
        
        filepath = Config.DATA_DIR / "users" / "passengers" / "normal" / f"{user_id}.json"
        if self.storage.write_json(filepath, user_data):
            return self._sanitize_user(user_data)
        raise Exception("Error al crear usuario")
    
    def _phone_exists(self, phone: str) -> bool:
        for tier in ["premium", "normal"]:
            passenger_dir = Config.DATA_DIR / "users" / "passengers" / tier
            for file in self.storage.find_files(passenger_dir):
                user = self.storage.read_json(file)
                if user and user.get("phone") == phone:
                    return True
        
        driver_dir = Config.DATA_DIR / "users" / "drivers"
        for file in self.storage.find_files(driver_dir):
            user = self.storage.read_json(file)
            if user and user.get("phone") == phone:
                return True
        return False
    
    def authenticate(self, phone: str, password: str) -> Optional[Dict]:
        for tier in ["premium", "normal"]:
            passenger_dir = Config.DATA_DIR / "users" / "passengers" / tier
            for file in self.storage.find_files(passenger_dir):
                user = self.storage.read_json(file)
                if user and user.get("phone") == phone:
                    if self.storage.verify_password(password, user.get("password_hash", "")):
                        return self._sanitize_user(user)
        
        driver_dir = Config.DATA_DIR / "users" / "drivers"
        for file in self.storage.find_files(driver_dir):
            user = self.storage.read_json(file)
            if user and user.get("phone") == phone:
                if self.storage.verify_password(password, user.get("password_hash", "")):
                    return self._sanitize_user(user)
        return None
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        for tier in ["premium", "normal"]:
            filepath = Config.DATA_DIR / "users" / "passengers" / tier / f"{user_id}.json"
            if filepath.exists():
                return self.storage.read_json(filepath)
        
        filepath = Config.DATA_DIR / "users" / "drivers" / f"{user_id}.json"
        if filepath.exists():
            return self.storage.read_json(filepath)
        return None
    
    def update_user(self, user_id: str, updates: Dict) -> bool:
        user = self.get_user(user_id)
        if not user:
            return False
        
        protected_fields = ["user_id", "created_at", "password_hash"]
        for key, value in updates.items():
            if key not in protected_fields:
                user[key] = value
        
        user["last_active"] = datetime.utcnow().isoformat()
        
        filepath = self._get_user_filepath(user_id, user.get("tier"))
        if filepath:
            return self.storage.write_json(filepath, user)
        return False
    
    def _get_user_filepath(self, user_id: str, tier: str = None) -> Optional[Path]:
        if user_id.startswith("pax_"):
            if tier:
                return Config.DATA_DIR / "users" / "passengers" / tier / f"{user_id}.json"
            for t in ["premium", "normal"]:
                fp = Config.DATA_DIR / "users" / "passengers" / t / f"{user_id}.json"
                if fp.exists():
                    return fp
        elif user_id.startswith("drv_"):
            return Config.DATA_DIR / "users" / "drivers" / f"{user_id}.json"
        return None
    
    def _sanitize_user(self, user: Dict) -> Dict:
        if user:
            user = user.copy()
            user.pop("password_hash", None)
        return user

class TripService:
    def __init__(self, storage: JSONStorage, user_service: UserService):
        self.storage = storage
        self.user_service = user_service
        self.route_service = RouteService()
    
    async def create_trip_with_route(self, passenger_id: str, pickup: Dict, dropoff: Dict, service_type: str, payment_method: str = "cash") -> Dict:
        trip_id = self.storage.generate_id("trip_")
        
        origin_coords = pickup.get("coordinates", {})
        dest_coords = dropoff.get("coordinates", {})
        
        route_info = await self.route_service.calculate_route(origin_coords, dest_coords)
        price_info = self.route_service.estimate_price(route_info, service_type)
        
        trip_data = {
            "trip_id": trip_id,
            "passenger_id": passenger_id,
            "driver_id": None,
            "service_type": service_type,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "timeline": {
                "requested": datetime.utcnow().isoformat(),
                "accepted": None, "arrived_at_pickup": None,
                "started": None, "completed": None, "cancelled": None
            },
            "locations": {"pickup": pickup, "dropoff": dropoff},
            "route": {
                "distance_km": route_info["distance_km"],
                "duration_minutes": route_info["duration_min"],
                "calculated_at": datetime.utcnow().isoformat(),
                "source": route_info.get("source", "unknown"),
                "is_estimate": route_info.get("is_estimate", False)
            },
            "pricing": {
                "base_fare": price_info["base_fare"],
                "distance_fare": price_info["distance_fare"],
                "time_fare": price_info["time_fare"],
                "surge_multiplier": price_info["surge_multiplier"],
                "subtotal": price_info["subtotal"],
                "total": price_info["total"],
                "currency": price_info["currency"],
                "payment_method": payment_method,
                "payment_status": "pending",
                "promo_code": None,
                "promo_discount": 0.0,
                "tip": 0.0
            },
            "rating": None,
            "cancellation": None,
            "notes": ""
        }
        
        return trip_data
    
    def find_nearby_drivers(self, lat: float, lng: float, max_distance_km: float = 5.0) -> List[Dict]:
        drivers = []
        driver_dir = Config.DATA_DIR / "users" / "drivers"
        
        for file in self.storage.find_files(driver_dir):
            driver = self.storage.read_json(file)
            if not driver:
                continue
            
            status = driver.get("status", {})
            if not status.get("online"):
                continue
            if status.get("current_state") != "available":
                continue
            
            driver_loc = status.get("last_location")
            if driver_loc:
                distance = self._calculate_distance({"lat": lat, "lng": lng}, driver_loc)
                if distance <= max_distance_km:
                    driver_copy = driver.copy()
                    driver_copy["_distance_km"] = round(distance, 2)
                    drivers.append(driver_copy)
        
        drivers.sort(key=lambda x: x["_distance_km"])
        return drivers[:10]
    
    def accept_trip(self, trip_id: str, driver_id: str) -> bool:
        trip = self._get_trip(trip_id)
        if not trip or trip["status"] != "pending":
            return False
        
        driver = self.user_service.get_user(driver_id)
        if not driver:
            return False
        
        trip["driver_id"] = driver_id
        trip["status"] = "active"
        trip["timeline"]["accepted"] = datetime.utcnow().isoformat()
        
        if "status" not in driver:
            driver["status"] = {}
        driver["status"]["current_state"] = "on_trip"
        driver["status"]["current_trip"] = trip_id
        
        src = Config.DATA_DIR / "trips" / "pending" / f"{trip_id}.json"
        dst = Config.DATA_DIR / "trips" / "active" / f"{trip_id}.json"
        
        if self.storage.move_file(src, dst):
            self.user_service.update_user(driver_id, driver)
            return True
        
        return False
    
    def update_trip_status(self, trip_id: str, status: str, location: Dict = None) -> bool:
        trip = self._get_trip(trip_id)
        if not trip:
            return False
        
        now = datetime.utcnow().isoformat()
        
        if status == "arrived":
            trip["timeline"]["arrived_at_pickup"] = now
        elif status == "started":
            trip["timeline"]["started"] = now
        elif status == "completed":
            trip["status"] = "completed"
            trip["timeline"]["completed"] = now
            self._complete_trip(trip)
        elif status == "cancelled":
            trip["status"] = "cancelled"
            trip["timeline"]["cancelled"] = now
            self._cancel_trip(trip)
        
        if location:
            if "path" not in trip["route"]:
                trip["route"]["path"] = []
            trip["route"]["path"].append({**location, "timestamp": now})
        
        filepath = self._get_trip_filepath(trip_id)
        if filepath:
            return self.storage.write_json(filepath, trip)
        return False
    
    def _complete_trip(self, trip: Dict):
        passenger = self.user_service.get_user(trip["passenger_id"])
        if passenger:
            passenger.setdefault("stats", {})["total_trips"] = passenger.get("stats", {}).get("total_trips", 0) + 1
            passenger["stats"]["total_spent"] = passenger.get("stats", {}).get("total_spent", 0.0) + trip["pricing"]["total"]
            passenger.setdefault("recent_places", []).insert(0, {
                "id": self.storage.generate_id("rec_"),
                "name": trip["locations"]["dropoff"].get("address", "Destino").split(",")[0],
                "address": trip["locations"]["dropoff"].get("address", ""),
                "coordinates": trip["locations"]["dropoff"].get("coordinates", {}),
                "last_used": datetime.utcnow().isoformat(),
                "frequency": 1
            })
            passenger["recent_places"] = passenger["recent_places"][:10]
            self.user_service.update_user(trip["passenger_id"], passenger)
        
        if trip["driver_id"]:
            driver = self.user_service.get_user(trip["driver_id"])
            if driver:
                driver.setdefault("stats", {})["total_trips"] = driver.get("stats", {}).get("total_trips", 0) + 1
                earnings = round(trip["pricing"]["total"] * 0.75, 2)
                driver["stats"]["total_earned"] = driver.get("stats", {}).get("total_earned", 0.0) + earnings
                driver.setdefault("wallet", {"balance": 0.0, "pending": 0.0, "total_earned": 0.0})
                driver["wallet"]["balance"] = driver["wallet"].get("balance", 0.0) + earnings
                driver.setdefault("status", {})["current_state"] = "available"
                driver["status"]["current_trip"] = None
                self.user_service.update_user(trip["driver_id"], driver)
        
        src = Config.DATA_DIR / "trips" / "active" / f"{trip['trip_id']}.json"
        dst = Config.DATA_DIR / "trips" / "completed" / f"{trip['trip_id']}.json"
        self.storage.move_file(src, dst)
    
    def _cancel_trip(self, trip: Dict):
        src = self._get_trip_filepath(trip["trip_id"])
        if src:
            dst = Config.DATA_DIR / "trips" / "cancelled" / f"{trip['trip_id']}.json"
            self.storage.move_file(src, dst)
        
        if trip.get("driver_id"):
            driver = self.user_service.get_user(trip["driver_id"])
            if driver:
                driver.setdefault("status", {})["current_state"] = "available"
                driver["status"]["current_trip"] = None
                self.user_service.update_user(trip["driver_id"], driver)
    
    def _get_trip(self, trip_id: str) -> Optional[Dict]:
        for status in ["pending", "active", "completed", "cancelled"]:
            filepath = Config.DATA_DIR / "trips" / status / f"{trip_id}.json"
            if filepath.exists():
                return self.storage.read_json(filepath)
        return None
    
    def _get_trip_filepath(self, trip_id: str) -> Optional[Path]:
        for status in ["pending", "active", "completed", "cancelled"]:
            filepath = Config.DATA_DIR / "trips" / status / f"{trip_id}.json"
            if filepath.exists():
                return filepath
        return None
    
    def _calculate_distance(self, point1: Dict, point2: Dict) -> float:
        if not point1 or not point2:
            return 0.0
        
        try:
            lat1 = radians(point1.get("lat", 0))
            lng1 = radians(point1.get("lng", 0))
            lat2 = radians(point2.get("lat", 0))
            lng2 = radians(point2.get("lng", 0))
            dlat = lat2 - lat1
            dlng = lng2 - lng1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            return round(6371 * c, 2)
        except Exception:
            return 0.0

class NotificationService:
    def __init__(self, storage: JSONStorage):
        self.storage = storage
    
    def send_notification(self, user_id: str, title: str, message: str, notification_type: str, data: Dict = None) -> bool:
        filepath = Config.DATA_DIR / "notifications" / f"{user_id}_notifications.json"
        
        notifications_data = self.storage.read_json(filepath) or {
            "user_id": user_id, "notifications": [], "unread_count": 0,
            "last_updated": datetime.utcnow().isoformat()
        }
        
        notification = {
            "id": self.storage.generate_id("notif_"),
            "type": notification_type, "title": title, "message": message,
            "data": data or {}, "read": False,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat()
        }
        
        notifications_data["notifications"].insert(0, notification)
        notifications_data["notifications"] = notifications_data["notifications"][:50]
        notifications_data["unread_count"] = sum(1 for n in notifications_data["notifications"] if not n.get("read", False))
        notifications_data["last_updated"] = datetime.utcnow().isoformat()
        
        return self.storage.write_json(filepath, notifications_data)
    
    def get_notifications(self, user_id: str) -> Dict:
        filepath = Config.DATA_DIR / "notifications" / f"{user_id}_notifications.json"
        if filepath.exists():
            data = self.storage.read_json(filepath)
            if data:
                return data
        return {"user_id": user_id, "notifications": [], "unread_count": 0, "last_updated": datetime.utcnow().isoformat()}
    
    def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        filepath = Config.DATA_DIR / "notifications" / f"{user_id}_notifications.json"
        data = self.storage.read_json(filepath)
        if not data:
            return False
        
        for notif in data.get("notifications", []):
            if notif.get("id") == notification_id:
                notif["read"] = True
                break
        
        data["unread_count"] = sum(1 for n in data.get("notifications", []) if not n.get("read", False))
        data["last_updated"] = datetime.utcnow().isoformat()
        return self.storage.write_json(filepath, data)

# ============================================
# CONNECTION MANAGER PARA WEBSOCKETS
# ============================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.driver_locations: Dict[str, Dict] = {}
        self._lock = threading.Lock()
    
    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self.active_connections[user_id] = websocket
        logger.info(f"Usuario {user_id} conectado. Total: {len(self.active_connections)}")
    
    def disconnect(self, user_id: str):
        with self._lock:
            self.active_connections.pop(user_id, None)
            self.driver_locations.pop(user_id, None)
        logger.info(f"Usuario {user_id} desconectado. Total: {len(self.active_connections)}")
    
    async def send_message(self, user_id: str, message: Dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error enviando mensaje a {user_id}: {e}")
                self.disconnect(user_id)
        return False
    
    def update_driver_location(self, driver_id: str, location: Dict):
        with self._lock:
            self.driver_locations[driver_id] = {**location, "updated_at": datetime.utcnow().isoformat()}
    
    def get_driver_location(self, driver_id: str) -> Optional[Dict]:
        return self.driver_locations.get(driver_id)
    
    async def broadcast_to_drivers(self, message: Dict):
        with self._lock:
            drivers = [(uid, ws) for uid, ws in self.active_connections.items() if uid.startswith("drv_")]
        for user_id, ws in drivers:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(user_id)

# ============================================
# FASTAPI APP
# ============================================

app = FastAPI(title="Transporte Venezuela API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = JSONStorage()
user_service = UserService(storage)
trip_service = TripService(storage, user_service)
notification_service = NotificationService(storage)
connection_manager = ConnectionManager()
route_service = RouteService()
google_maps_service = GoogleMapsService()

# ============================================
# MODELOS Pydantic
# ============================================

class LoginRequest(BaseModel):
    phone: str
    password: str

class RegisterRequest(BaseModel):
    phone: str
    password: str
    full_name: str
    email: Optional[str] = None

class TripRequest(BaseModel):
    passenger_id: str
    pickup: Dict
    dropoff: Dict
    service_type: str
    payment_method: str = "cash"
    promo_code: Optional[str] = None

class RouteRequest(BaseModel):
    origin: Dict
    destination: Dict
    service_type: str = "uberx"

class LocationUpdate(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None

class RatingRequest(BaseModel):
    trip_id: str
    rating: int
    user_type: str
    comment: Optional[str] = None

class TripStatusUpdate(BaseModel):
    status: str
    location: Optional[LocationUpdate] = None

class AcceptTripRequest(BaseModel):
    driver_id: str

class GeocodeRequest(BaseModel):
    address: str

class ReverseGeocodeRequest(BaseModel):
    lat: float
    lng: float

class AutocompleteRequest(BaseModel):
    input: str
    lat: Optional[float] = None
    lng: Optional[float] = None

class PlaceDetailsRequest(BaseModel):
    place_id: str

# ============================================
# ENDPOINTS REST
# ============================================

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat(), "active_connections": len(connection_manager.active_connections)}

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    user = user_service.authenticate(request.phone, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = storage.generate_id("token_")
    return {"success": True, "token": token, "user": user}

@app.post("/api/auth/register")
async def register(request: RegisterRequest):
    try:
        user = user_service.create_passenger(request.phone, request.password, request.full_name, request.email)
        return {"success": True, "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error en registro: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.get("/api/user/{user_id}")
async def get_user(user_id: str):
    user = user_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user

@app.put("/api/user/{user_id}")
async def update_user(user_id: str, updates: Dict):
    success = user_service.update_user(user_id, updates)
    if not success:
        raise HTTPException(status_code=400, detail="Error al actualizar")
    return {"success": True}

@app.post("/api/trips/request")
async def request_trip(request: TripRequest, background_tasks: BackgroundTasks):
    try:
        trip = await trip_service.create_trip_with_route(
            request.passenger_id,
            request.pickup,
            request.dropoff,
            request.service_type,
            request.payment_method
        )
        
        if request.promo_code:
            trip["pricing"]["promo_code"] = request.promo_code
        
        filepath = Config.DATA_DIR / "trips" / "pending" / f"{trip['trip_id']}.json"
        storage.write_json(filepath, trip)
        
        background_tasks.add_task(
            find_and_notify_drivers,
            trip["trip_id"],
            request.pickup.get("coordinates", {"lat": 0, "lng": 0})
        )
        
        return {"success": True, "trip": trip}
    except Exception as e:
        logger.error(f"Error creando viaje: {e}")
        raise HTTPException(status_code=500, detail=f"Error al crear viaje: {str(e)}")

@app.post("/api/routes/calculate")
async def calculate_route_endpoint(request: RouteRequest):
    try:
        route_info = await route_service.calculate_route(request.origin, request.destination)
        price_info = route_service.estimate_price(route_info, request.service_type)
        
        geometry_encoded = None
        if route_info.get("geometry"):
            geometry_encoded = polyline.encode(route_info["geometry"])
        
        return {
            "success": True,
            "route": {
                "distance_km": route_info["distance_km"],
                "duration_min": route_info["duration_min"],
                "source": route_info.get("source", "unknown"),
                "is_estimate": route_info.get("is_estimate", False)
            },
            "pricing": price_info,
            "polyline": geometry_encoded
        }
    except Exception as e:
        logger.error(f"Error calculando ruta: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trips/{trip_id}/accept")
async def accept_trip(trip_id: str, request: AcceptTripRequest):
    success = trip_service.accept_trip(trip_id, request.driver_id)
    if not success:
        raise HTTPException(status_code=400, detail="No se pudo aceptar el viaje")
    
    trip = trip_service._get_trip(trip_id)
    if trip:
        await connection_manager.send_message(trip["passenger_id"], {
            "type": "trip_accepted",
            "data": {"trip_id": trip_id, "driver_id": request.driver_id}
        })
    
    return {"success": True}

@app.post("/api/trips/{trip_id}/status")
async def update_trip_status(trip_id: str, request: TripStatusUpdate):
    location_dict = request.location.dict() if request.location else None
    success = trip_service.update_trip_status(trip_id, request.status, location_dict)
    
    if not success:
        raise HTTPException(status_code=400, detail="Error al actualizar estado")
    
    trip = trip_service._get_trip(trip_id)
    if trip:
        notify_user_id = trip["driver_id"] if request.status != "completed" else trip["passenger_id"]
        if notify_user_id:
            await connection_manager.send_message(notify_user_id, {
                "type": "trip_update",
                "data": {"trip_id": trip_id, "status": request.status}
            })
    
    return {"success": True}

@app.get("/api/trips/{trip_id}")
async def get_trip(trip_id: str):
    trip = trip_service._get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Viaje no encontrado")
    return trip

@app.get("/api/drivers/nearby")
async def get_nearby_drivers(lat: float, lng: float, radius: float = 5.0):
    drivers = trip_service.find_nearby_drivers(lat, lng, radius)
    return {"drivers": drivers, "count": len(drivers)}

@app.post("/api/trips/{trip_id}/rate")
async def rate_trip(trip_id: str, request: RatingRequest):
    trip = trip_service._get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Viaje no encontrado")
    
    if not trip.get("rating"):
        trip["rating"] = {}
    
    if request.user_type == "passenger":
        trip["rating"]["driver_rating"] = request.rating
        trip["rating"]["passenger_comment"] = request.comment
    elif request.user_type == "driver":
        trip["rating"]["passenger_rating"] = request.rating
        trip["rating"]["driver_comment"] = request.comment
    else:
        raise HTTPException(status_code=400, detail="user_type debe ser 'passenger' o 'driver'")
    
    trip["rating"]["rated_at"] = datetime.utcnow().isoformat()
    
    filepath = trip_service._get_trip_filepath(trip_id)
    if filepath:
        storage.write_json(filepath, trip)
    
    return {"success": True}

@app.get("/api/notifications/{user_id}")
async def get_notifications(user_id: str):
    logger.info(f"Solicitando notificaciones para: {user_id}")
    result = notification_service.get_notifications(user_id)
    logger.info(f"Notificaciones encontradas: {len(result.get('notifications', []))}")
    return result

@app.post("/api/notifications/{user_id}/read/{notification_id}")
async def mark_notification_read(user_id: str, notification_id: str):
    success = notification_service.mark_as_read(user_id, notification_id)
    return {"success": success}

@app.get("/api/stats/system")
async def get_system_stats():
    stats_file = Config.DATA_DIR / "system" / "stats.json"
    stats = storage.read_json(stats_file)
    if not stats:
        stats = generate_system_stats()
        storage.write_json(stats_file, stats)
    return stats

@app.get("/api/user/{user_id}/trips")
async def get_user_trips(user_id: str):
    trips = []
    for status in ["completed", "cancelled"]:
        trip_dir = Config.DATA_DIR / "trips" / status
        for file in storage.find_files(trip_dir):
            trip = storage.read_json(file)
            if trip and (trip.get("passenger_id") == user_id or trip.get("driver_id") == user_id):
                trips.append(trip)
    trips.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"trips": trips}

# ============================================
# ENDPOINTS DE GOOGLE MAPS
# ============================================

@app.post("/api/geocode")
async def geocode_address(request: GeocodeRequest):
    """Convierte una dirección en coordenadas"""
    try:
        result = await google_maps_service.geocode_address(request.address)
        if result:
            return {"success": True, "data": result}
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    except Exception as e:
        logger.error(f"Error en geocodificación: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reverse-geocode")
async def reverse_geocode(request: ReverseGeocodeRequest):
    """Convierte coordenadas en una dirección"""
    try:
        result = await google_maps_service.reverse_geocode(request.lat, request.lng)
        if result:
            return {"success": True, "data": result}
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    except Exception as e:
        logger.error(f"Error en geocodificación inversa: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/places/autocomplete")
async def autocomplete_places(request: AutocompleteRequest):
    """Obtiene predicciones de lugares para autocompletar"""
    try:
        location = None
        if request.lat and request.lng:
            location = {"lat": request.lat, "lng": request.lng}
        
        predictions = await google_maps_service.get_place_predictions(request.input, location)
        return {"success": True, "predictions": predictions}
    except Exception as e:
        logger.error(f"Error en autocompletar: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/places/details")
async def get_place_details(request: PlaceDetailsRequest):
    """Obtiene detalles de un lugar por su ID"""
    try:
        result = await google_maps_service.get_place_details(request.place_id)
        if result:
            return {"success": True, "data": result}
        raise HTTPException(status_code=404, detail="Lugar no encontrado")
    except Exception as e:
        logger.error(f"Error obteniendo detalles del lugar: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# WEBSOCKETS PARA TIEMPO REAL
# ============================================

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await connection_manager.connect(user_id, websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "location_update":
                location = data.get("location", {})
                connection_manager.update_driver_location(user_id, location)
                
                if user_id.startswith("drv_"):
                    driver = user_service.get_user(user_id)
                    if driver:
                        driver.setdefault("status", {})["last_location"] = location
                        user_service.update_user(user_id, driver)
                
                if user_id.startswith("drv_"):
                    driver = user_service.get_user(user_id)
                    if driver and driver.get("status", {}).get("current_trip"):
                        trip_id = driver["status"]["current_trip"]
                        trip = trip_service._get_trip(trip_id)
                        if trip:
                            await connection_manager.send_message(trip["passenger_id"], {
                                "type": "driver_location",
                                "data": location
                            })
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
    
    except WebSocketDisconnect:
        connection_manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"Error en WebSocket {user_id}: {e}")
        connection_manager.disconnect(user_id)

# ============================================
# TAREAS EN BACKGROUND
# ============================================

async def find_and_notify_drivers(trip_id: str, pickup_location: Dict):
    trip = trip_service._get_trip(trip_id)
    if not trip:
        return
    
    drivers = trip_service.find_nearby_drivers(pickup_location.get("lat", 0), pickup_location.get("lng", 0))
    
    for driver in drivers[:5]:
        await connection_manager.send_message(driver["user_id"], {
            "type": "new_trip_request",
            "data": {
                "trip_id": trip_id,
                "pickup": trip["locations"]["pickup"],
                "dropoff": trip["locations"]["dropoff"],
                "estimated_fare": trip["pricing"]["total"],
                "distance_km": driver.get("_distance_km", 0)
            }
        })
        
        notification_service.send_notification(
            driver["user_id"],
            "Nuevo viaje disponible",
            f"Recogida en {trip['locations']['pickup'].get('address', 'Ubicación cercana')}",
            "new_trip",
            {"trip_id": trip_id}
        )

def generate_system_stats() -> Dict:
    stats = {
        "updated_at": datetime.utcnow().isoformat(),
        "totals": {"users": 0, "drivers": 0, "trips_today": 0, "active_drivers": 0, "active_trips": 0, "pending_requests": 0}
    }
    
    for tier in ["premium", "normal"]:
        passenger_dir = Config.DATA_DIR / "users" / "passengers" / tier
        if passenger_dir.exists():
            stats["totals"]["users"] += len(list(passenger_dir.glob("*.json")))
    
    driver_dir = Config.DATA_DIR / "users" / "drivers"
    if driver_dir.exists():
        stats["totals"]["drivers"] = len(list(driver_dir.glob("*.json")))
    
    active_dir = Config.DATA_DIR / "trips" / "active"
    pending_dir = Config.DATA_DIR / "trips" / "pending"
    
    if active_dir.exists():
        stats["totals"]["active_trips"] = len(list(active_dir.glob("*.json")))
    if pending_dir.exists():
        stats["totals"]["pending_requests"] = len(list(pending_dir.glob("*.json")))
    
    if driver_dir.exists():
        for file in driver_dir.glob("*.json"):
            driver = storage.read_json(file)
            if driver and driver.get("status", {}).get("online"):
                stats["totals"]["active_drivers"] += 1
    
    return stats

# ============================================
# INICIO DEL SERVIDOR
# ============================================

if __name__ == "__main__":
    logger.info("Iniciando servidor en http://0.0.0.0:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)