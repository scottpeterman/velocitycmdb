# create_test_user.py
from app.blueprints.auth.auth_manager import AuthenticationManager

config = {
    'database': {
        'enabled': True,
        'path': 'app/users.db'
    }
}

auth_manager = AuthenticationManager(config)

# Create admin user
success, message = auth_manager.create_user(
    username='admin',
    email='admin@localhost',
    password='admin123',
    is_admin=True,
    display_name='Administrator',
    groups=['admin', 'network-ops']
)

print(message)