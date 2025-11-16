# app/blueprints/auth/routes.py
from flask import render_template, redirect, url_for, request, session, flash, jsonify
from functools import wraps
import logging
from . import auth_bp
from velocitycmdb.app.blueprints.auth.auth_manager import AuthenticationManager

logger = logging.getLogger(__name__)

# Initialize authentication manager (will be configured in create_app)
auth_manager = None


def init_auth_manager(config):
    """Initialize authentication manager with application config"""
    global auth_manager
    auth_manager = AuthenticationManager(config)
    logger.info("Authentication manager initialized")
    return auth_manager


def login_required(f):
    """Decorator to require login for protected routes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page with multi-method authentication and password change support"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        auth_method = request.form.get('auth_method', 'local')
        domain = request.form.get('domain')
        change_password = request.form.get('change_password') == 'on'
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not username or not password:
            flash('Username and password required', 'error')
            return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

        # Handle password change request
        if change_password:
            if auth_method != 'database':
                flash('Password change is only available for database authentication', 'error')
                return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

            if not new_password or not confirm_password:
                flash('New password and confirmation required', 'error')
                return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

            if len(new_password) < 8:
                flash('New password must be at least 8 characters', 'error')
                return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

            # Verify old password first
            result = auth_manager.authenticate(
                username=username,
                password=password,
                auth_method='database'
            )

            if not result.success:
                flash('Current password is incorrect', 'error')
                logger.warning(f"Failed password change attempt for {username}: invalid current password")
                return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

            # Change the password
            try:
                success, message = auth_manager.change_password(username, new_password)
                if success:
                    flash('Password changed successfully. Please log in with your new password.', 'success')
                    logger.info(f"Password changed for user: {username}")
                    return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())
                else:
                    flash(f'Password change failed: {message}', 'error')
                    logger.error(f"Password change failed for {username}: {message}")
                    return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())
            except Exception as e:
                flash('An error occurred while changing password', 'error')
                logger.error(f"Password change error for {username}: {e}")
                return render_template('auth/login.html', auth_info=auth_manager.get_available_methods())

        # Normal authentication flow
        try:
            result = auth_manager.authenticate(
                username=username,
                password=password,
                auth_method=auth_method,
                domain=domain
            )

            if result.success:
                # Set session variables
                session['logged_in'] = True
                session['username'] = result.username
                session['auth_method'] = result.auth_method
                session['groups'] = result.groups or []
                session['is_admin'] = 'admin' in (result.groups or [])

                logger.info(f"User {result.username} logged in via {result.auth_method}")

                # Redirect to dashboard or requested page
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('dashboard.index'))
            else:
                flash(f'Authentication failed: {result.error}', 'error')
                logger.warning(f"Failed login attempt for {username}: {result.error}")

        except Exception as e:
            logger.error(f"Login error for {username}: {e}")
            flash('An error occurred during login', 'error')

    # Get available authentication methods
    auth_info = auth_manager.get_available_methods() if auth_manager else {}

    return render_template('auth/login.html', auth_info=auth_info)


@auth_bp.route('/logout')
def logout():
    """Logout and clear session"""
    username = session.get('username', 'Unknown')
    session.clear()
    logger.info(f"User {username} logged out")
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/api/auth/methods', methods=['GET'])
def get_auth_methods():
    """API endpoint to get available authentication methods"""
    if not auth_manager:
        return jsonify({'error': 'Authentication manager not initialized'}), 500

    return jsonify(auth_manager.get_available_methods())


@auth_bp.route('/api/auth/validate', methods=['POST'])
def validate_session():
    """API endpoint to validate current session"""
    if 'logged_in' in session:
        return jsonify({
            'valid': True,
            'username': session.get('username'),
            'auth_method': session.get('auth_method'),
            'groups': session.get('groups', [])
        })
    else:
        return jsonify({'valid': False}), 401

