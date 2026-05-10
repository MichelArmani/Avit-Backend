from flask import Flask, request, make_response
from flask_cors import CORS
from config import Config
import pymysql
from pymysql.cursors import DictCursor

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], "allow_headers": ["*"], "expose_headers": ["*"]}})

# @app.after_request
# def after_request(response):
#     response.headers.add('Access-Control-Allow-Origin', '*')
#     response.headers.add('Access-Control-Allow-Headers', '*')
#     response.headers.add('Access-Control-Allow-Methods', '*')
#     response.headers.add('Access-Control-Allow-Credentials', 'false')
#     return response

# @app.before_request
# def handle_preflight():
#     if request.method == "OPTIONS":
#         response = make_response()
#         response.headers.add("Access-Control-Allow-Origin", "*")
#         response.headers.add('Access-Control-Allow-Headers', "*")
#         response.headers.add('Access-Control-Allow-Methods', "*")
#         return response

def get_db():
    return pymysql.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        port=Config.MYSQL_PORT,
        cursorclass=DictCursor
    )

def init_db():
    return

from routes.auth_routes import auth_bp
from routes.passenger_routes import passenger_bp
from routes.driver_routes import driver_bp
from routes.trip_routes import trips_bp
from routes.notifications import notifications_bp
from routes.wallet import wallet_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(passenger_bp, url_prefix='/passenger')
app.register_blueprint(driver_bp, url_prefix='/driver')
app.register_blueprint(trips_bp, url_prefix='/trips')
app.register_blueprint(notifications_bp, url_prefix='/notifications')
app.register_blueprint(wallet_bp, url_prefix='/wallet')

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Iniciando servidor Avit...")
    print("=" * 50)
    init_db()
    app.run(debug=True, port=3001, host='0.0.0.0')
