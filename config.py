import os

class Config:
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'mysql-personal234.g.aivencloud.com')
    MYSQL_USER = os.environ.get('MYSQL_USER', 'avnadmin')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'AVNS_St6kUfEfT7IczRHOJZP')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'defaultdb')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 22750))
    
    # JWT Secret (sin encriptación, solo para firmar)
    JWT_SECRET = 'avit-secret-key-2024' 
