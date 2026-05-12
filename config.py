import os

class Config:
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'mysql-personal234.g.aivencloud.com')
    MYSQL_USER = os.environ.get('MYSQL_USER', 'avnadmin')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'AVNS_St6kUfEfT7IczRHOJZP')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'defaultdb')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 22750))

    # JWT Secret (sin encriptación, solo para firmar)
    JWT_SECRET = 'avit-secret-key-2024'
    
    # ✅ NUEVOS: Timeouts para evitar conexiones idle
    MYSQL_CONNECT_TIMEOUT = 10
    MYSQL_READ_TIMEOUT = 30
    MYSQL_WRITE_TIMEOUT = 30
    MYSQL_POOL_SIZE = 20
    MYSQL_POOL_RECYCLE = 700
