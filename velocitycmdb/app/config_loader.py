import os
import yaml
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and manage application configuration"""

    DEFAULT_CONFIG_FILENAME = 'config.yaml'

    def __init__(self, config_path: str = None):
        """
        Initialize config loader

        Args:
            config_path: Optional path to config file. If None, looks for config.yaml in current directory
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_FILENAME
        self.config = None

    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration values with database auth as default"""
        return {
            'authentication': {
                'default_method': 'database',
                'use_ssh_fallback': True,
                'ssh_host': 'localhost',

                'database': {
                    'enabled': True,
                    'path': '~/.velocitycmdb/data/users.db'
                },

                'local': {
                    'enabled': True,
                    'domain_required': False,
                    'use_computer_name_as_domain': True
                },

                'ldap': {
                    'enabled': False,
                    'server': None,
                    'port': 389,
                    'use_ssl': False,
                    'base_dn': None,
                    'user_dn_template': None,
                    'search_groups': False,
                    'group_base_dn': None,
                    'group_filter': '(&(objectClass=group)(member={user_dn}))',
                    'timeout': 10,
                    'max_retries': 3
                }
            },
            'flask': {
                'secret_key': None,
                'session_timeout_minutes': 120
            },
            'server': {
                'host': '0.0.0.0',
                'port': 8086,
                'debug': False
            },
            'logging': {
                'level': 'INFO',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'file': None
            },
            # Directory paths
            'paths': {
                'data_dir': '~/.velocitycmdb/data',
                'capture_dir': '~/.velocitycmdb/data/capture',
                'jobs_dir': '~/.velocitycmdb/data/jobs',
                'fingerprints_dir': '~/.velocitycmdb/data/fingerprints',
                'discovery_dir': '~/.velocitycmdb/discovery',
                'scmaps_dir': '~/.velocitycmdb/discovery/maps',
                'maps_dir': '~/.velocitycmdb/data/maps'
            },
            # Legacy - kept for backwards compatibility
            'scmaps': {
                'data_dir': '~/.velocitycmdb/discovery/maps'
            }
        }

    def _create_default_config(self) -> None:
        """Create a default config.yaml file in the current directory"""
        defaults = self._get_defaults()

        config_with_comments = f"""# VelocityCMDB Configuration File
# Generated automatically - customize as needed
#
# Authentication Methods:
#   - database: Local SQLite database (recommended for small teams)
#   - local: OS-level authentication (Windows/Linux)
#   - ldap: LDAP/Active Directory (enterprise)
#
# Multiple methods can be enabled simultaneously

authentication:
  default_method: database
  use_ssh_fallback: true
  ssh_host: localhost

  # Database Authentication (Default)
  database:
    enabled: true
    path: ~/.velocitycmdb/data/users.db

  # Local OS Authentication
  local:
    enabled: true
    domain_required: false
    use_computer_name_as_domain: true

  # LDAP/Active Directory Authentication
  ldap:
    enabled: false
    server: null
    port: 389
    use_ssl: false
    base_dn: null
    user_dn_template: null
    search_groups: false
    group_base_dn: null
    group_filter: "(&(objectClass=group)(member={{user_dn}}))"
    timeout: 10
    max_retries: 3

# Flask Settings
flask:
  secret_key: null  # Auto-generated if not provided
  session_timeout_minutes: 120

# Server Settings
server:
  host: 0.0.0.0
  port: 8086
  debug: false

# Logging Configuration
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: null

# Directory Paths
# All paths support ~ for home directory expansion
paths:
  data_dir: ~/.velocitycmdb/data
  capture_dir: ~/.velocitycmdb/data/capture
  jobs_dir: ~/.velocitycmdb/data/jobs
  fingerprints_dir: ~/.velocitycmdb/data/fingerprints
  discovery_dir: ~/.velocitycmdb/discovery
  scmaps_dir: ~/.velocitycmdb/discovery/maps
  maps_dir: ~/.velocitycmdb/data/maps

# Legacy: SecureCartography Maps Directory (use paths.scmaps_dir instead)
scmaps:
  data_dir: ~/.velocitycmdb/discovery/maps

# Getting Started:
# 1. Run: python -m velocitycmdb.cli init
# 2. Run: velocitycmdb create-admin
# 3. Run: python -m velocitycmdb.app.run
# 4. Login with admin/admin (change password after first login)
"""

        try:
            # Get absolute path for logging
            abs_path = os.path.abspath(self.config_path)

            # Ensure parent directory exists
            parent_dir = os.path.dirname(abs_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            # Write the config file
            with open(self.config_path, 'w') as f:
                f.write(config_with_comments)

            logger.info(f"Created default configuration file: {abs_path}")
            print(f"✓ Created default configuration file: {abs_path}")
            print(f"✓ Default authentication method: database")
            print(f"✓ Next steps:")
            print(f"  1. Run: python -m velocitycmdb.cli init")
            print(f"  2. Run: velocitycmdb create-admin")
            print(f"  3. Run: python -m velocitycmdb.app.run")

        except Exception as e:
            logger.error(f"Failed to create default config file: {e}")
            raise RuntimeError(f"Could not create default config.yaml: {e}")

    def load(self) -> Dict[str, Any]:
        """
        Load configuration from file or create default if not found

        Returns:
            Configuration dictionary
        """
        # Get absolute path for better logging
        abs_path = os.path.abspath(self.config_path)

        # Check if config file exists
        if not os.path.exists(self.config_path):
            logger.warning(f"Configuration file not found: {abs_path}")
            print(f"⚠ Configuration file not found: {abs_path}")
            print(f"⚠ Creating default configuration...")

            # Create default config file
            self._create_default_config()

            # Return defaults for this session
            self.config = self._get_defaults()
            return self.config

        # Load existing config file
        try:
            with open(self.config_path, 'r') as f:
                loaded_config = yaml.safe_load(f) or {}

            # Merge with defaults (ensures new config keys exist)
            self.config = self._merge_with_defaults(loaded_config)

            # Log with FULL absolute path
            logger.info(f"Loaded configuration from: {abs_path}")
            print(f"✓ Loaded configuration from: {abs_path}")

            return self.config

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in config file: {e}")
            raise RuntimeError(f"Invalid YAML in {abs_path}: {e}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise RuntimeError(f"Failed to load configuration: {e}")

    def _merge_with_defaults(self, loaded: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively merge loaded config with defaults

        Args:
            loaded: Configuration loaded from file

        Returns:
            Merged configuration
        """
        defaults = self._get_defaults()
        return self._deep_merge(defaults, loaded)

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries, with override values taking precedence

        Args:
            base: Base dictionary (defaults)
            override: Override dictionary (loaded config)

        Returns:
            Merged dictionary
        """
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key

        Args:
            key: Configuration key (supports dot notation, e.g., 'authentication.default_method')
            default: Default value if key not found

        Returns:
            Configuration value
        """
        if self.config is None:
            self.load()

        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_path(self, key: str, default: str = None) -> str:
        """
        Get a path configuration value with ~ expansion

        Args:
            key: Configuration key (e.g., 'paths.capture_dir')
            default: Default value if key not found

        Returns:
            Expanded absolute path
        """
        path = self.get(key, default)
        if path:
            return os.path.expanduser(path)
        return default

    def reload(self) -> Dict[str, Any]:
        """Reload configuration from file"""
        self.config = None
        return self.load()


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    Convenience function to load configuration

    Args:
        config_path: Optional path to config file

    Returns:
        Configuration dictionary
    """
    loader = ConfigLoader(config_path)
    return loader.load()


def get_config_path() -> str:
    """
    Get the standard config file path

    Returns:
        Path to ~/.velocitycmdb/config.yaml
    """
    return os.path.join(os.path.expanduser('~'), '.velocitycmdb', 'config.yaml')