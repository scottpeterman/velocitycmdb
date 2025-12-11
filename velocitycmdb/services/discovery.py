"""
Discovery Service - Orchestrates network discovery pipeline
Wraps secure_cartography and collection tools
"""
import os
import subprocess
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Callable
import logging

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_BASE_DIR = '~/.velocitycmdb'
DEFAULT_DISCOVERY_DIR = '~/.velocitycmdb/discovery'


class DiscoveryOrchestrator:
    """Orchestrates network discovery and collection pipeline"""

    def __init__(self, output_dir: Path = None):
        """
        Initialize discovery orchestrator

        Args:
            output_dir: Where to store discovery results
                       Defaults to ~/.velocitycmdb/discovery
        """
        if output_dir:
            self.output_dir = Path(output_dir).expanduser()
        else:
            self.output_dir = Path(DEFAULT_DISCOVERY_DIR).expanduser()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Discovery output directory: {self.output_dir}")

    def run_topology_discovery(self,
                               seed_ip: str,
                               username: str = None,
                               password: str = None,
                               alternate_username: str = None,
                               alternate_password: str = None,
                               site_name: str = 'network',
                               max_devices: int = 100,
                               timeout: int = 30,
                               domain_name: str = '',
                               exclude_string: str = '',
                               layout_algo: str = 'kk',
                               progress_callback: Optional[Callable] = None) -> Dict:
        """
        Run Secure Cartography topology discovery

        Args:
            seed_ip: Starting IP address for CDP/LLDP discovery
            username: Primary SSH/device username (falls back to SC_USERNAME env var)
            password: Primary password (falls back to SC_PASSWORD env var)
            alternate_username: Fallback username (falls back to SC_ALT_USERNAME env var)
            alternate_password: Fallback password (falls back to SC_ALT_PASSWORD env var)
            site_name: Site name for map naming (e.g., 'lab', 'datacenter1')
            max_devices: Maximum devices to discover
            timeout: Connection timeout in seconds
            domain_name: Domain name for device resolution
            exclude_string: Comma-separated list of strings to exclude
            layout_algo: Layout algorithm (kk, spring, circular, random)
            progress_callback: Function to call with progress messages

        Returns:
            {
                'success': bool,
                'topology_file': Path,
                'device_count': int,
                'map_file': Path,
                'error': str (if failed)
            }
        """
        # Apply environment variable fallbacks
        username = username or os.getenv('SC_USERNAME', '')
        password = password or os.getenv('SC_PASSWORD', '')
        alternate_username = alternate_username or os.getenv('SC_ALT_USERNAME', '')
        alternate_password = alternate_password or os.getenv('SC_ALT_PASSWORD', '')

        # Validate required credentials
        if not username or not password:
            error_msg = "Missing required credentials. Provide via parameters or environment variables (SC_USERNAME/SC_PASSWORD)"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

        if progress_callback:
            progress_callback({
                'stage': 'discovery',
                'message': 'Starting network topology discovery...',
                'progress': 0
            })

        # Set environment variables for secure_cartography to use
        # Credentials are ONLY passed via environment variables, NOT in config file
        env = os.environ.copy()
        env['SC_USERNAME'] = username
        env['SC_PASSWORD'] = password
        if alternate_username:
            env['SC_ALT_USERNAME'] = alternate_username
        if alternate_password:
            env['SC_ALT_PASSWORD'] = alternate_password

        logger.info(f"Environment variables set: SC_USERNAME={username[:3]}*** (credentials hidden)")

        # Create YAML config file WITHOUT credentials
        config_data = {
            'seed_ip': seed_ip,
            'output_dir': str(self.output_dir),
            'max_devices': max_devices,
            'timeout': timeout,
            'map_name': site_name,
            'layout_algo': layout_algo
        }

        # Add optional fields only if provided
        if domain_name:
            config_data['domain_name'] = domain_name
        if exclude_string:
            config_data['exclude_string'] = exclude_string

        # Write config file
        config_file = self.output_dir / f'{site_name}_config.yaml'
        try:
            import yaml
            with open(config_file, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False)
            logger.info(f"Created config file: {config_file}")
            logger.info(f"Config contents:\n{yaml.dump(config_data, default_flow_style=False)}")
            logger.info(f"Credentials will be passed via environment variables SC_USERNAME/SC_PASSWORD")
        except Exception as e:
            logger.error(f"Failed to create config file: {e}")
            return {
                'success': False,
                'error': f"Failed to create config file: {str(e)}"
            }

        # Build secure_cartography command using config file
        cmd = [
            sys.executable,
            '-u',  # Unbuffered output
            '-m', 'secure_cartography.sc',
            '--config', str(config_file),
            '--map-name', site_name,
            '--layout-algo', layout_algo,
            '--seed-ip', seed_ip
        ]

        try:
            if progress_callback:
                progress_callback({
                    'stage': 'discovery',
                    'message': f'Discovering devices from seed: {seed_ip} (site: {site_name})',
                    'progress': 10
                })

            # Run discovery as subprocess with environment variables
            logger.info(f"Using Python: {sys.executable}")
            logger.info(f"Running command: {' '.join(cmd)}")
            logger.info(f"Working directory: {os.getcwd()}")
            logger.info(f"Output directory: {self.output_dir}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True,
                env=env  # Pass environment with credentials
            )

            # Stream output in real-time
            output_lines = []
            for line in iter(process.stdout.readline, ''):
                if line:
                    line = line.rstrip()
                    output_lines.append(line)
                    logger.info(f"SC OUTPUT: {line}")

                    if progress_callback:
                        # Update progress based on output
                        if 'discovered' in line.lower():
                            progress_callback({
                                'stage': 'discovery',
                                'message': line,
                                'progress': 50
                            })
                        elif 'complete' in line.lower():
                            progress_callback({
                                'stage': 'discovery',
                                'message': line,
                                'progress': 75
                            })

            # Wait for completion
            return_code = process.wait(timeout=600)  # 10 minute timeout

            logger.info(f"Process completed with return code: {return_code}")

            if return_code != 0:
                error_output = '\n'.join(output_lines[-20:])
                logger.error(f"Discovery failed. Last output:\n{error_output}")
                return {
                    'success': False,
                    'error': f"Discovery process failed (exit code {return_code}). Check logs for details.",
                    'output': error_output
                }

            # Find topology output file
            topology_file = self.output_dir / f'{site_name}.json'

            if not topology_file.exists():
                # Try alternate names
                for alt_name in ['topology.json', 'network.json']:
                    alt_file = self.output_dir / alt_name
                    if alt_file.exists():
                        topology_file = alt_file
                        break

            if not topology_file.exists():
                logger.error(f"Topology file not found. Output dir contents: {list(self.output_dir.iterdir())}")
                return {
                    'success': False,
                    'error': f"Topology file not found in {self.output_dir}"
                }

            # Load topology to get device count
            with open(topology_file) as f:
                topology_data = json.load(f)

            # Handle both list and dict formats
            if isinstance(topology_data, list):
                device_count = len(topology_data)
            elif isinstance(topology_data, dict):
                device_count = len(topology_data)

            # Find map files (named with site name)
            map_file = self.output_dir / f'{site_name}.html'
            svg_file = self.output_dir / f'{site_name}.svg'
            graphml_file = self.output_dir / f'{site_name}.graphml'
            drawio_file = self.output_dir / f'{site_name}.drawio'

            logger.info(f"Looking for map files with site name '{site_name}':")
            logger.info(f"  JSON: {topology_file} (exists: {topology_file.exists()})")
            logger.info(f"  HTML: {map_file} (exists: {map_file.exists()})")
            logger.info(f"  SVG: {svg_file} (exists: {svg_file.exists()})")
            logger.info(f"  GraphML: {graphml_file} (exists: {graphml_file.exists()})")
            logger.info(f"  DrawIO: {drawio_file} (exists: {drawio_file.exists()})")

            if progress_callback:
                progress_callback({
                    'stage': 'discovery',
                    'message': f'✓ Discovery complete! Found {device_count} devices',
                    'progress': 100
                })

            logger.info(f"Discovery successful: {device_count} devices found")
            logger.info(f"Map files created: {site_name}.{{html,svg,graphml,drawio}}")

            return {
                'success': True,
                'topology_file': topology_file,
                'device_count': device_count,
                'map_file': map_file if map_file.exists() else None,
                'svg_file': svg_file if svg_file.exists() else None,
                'graphml_file': graphml_file if graphml_file.exists() else None,
                'drawio_file': drawio_file if drawio_file.exists() else None,
                'topology_data': topology_data,
                'site_name': site_name
            }

        except subprocess.TimeoutExpired:
            logger.error("Discovery timeout exceeded")
            process.kill()
            return {
                'success': False,
                'error': 'Discovery timeout (>10 minutes). Check network connectivity.'
            }
        except Exception as e:
            logger.exception("Discovery failed with exception")
            return {
                'success': False,
                'error': f"Discovery error: {str(e)}"
            }

    def convert_to_inventory(self,
                            topology_file: Path,
                            progress_callback: Optional[Callable] = None) -> Dict:
        """
        Convert topology JSON to sessions.yaml inventory

        Args:
            topology_file: Path to topology.json from discovery
            progress_callback: Function to call with progress messages

        Returns:
            {
                'success': bool,
                'inventory_file': Path,
                'site_count': int,
                'device_count': int,
                'inventory_data': List[Dict],
                'error': str (if failed)
            }
        """
        if progress_callback:
            progress_callback({
                'stage': 'inventory',
                'message': 'Converting topology to inventory...',
                'progress': 0
            })

        try:
            # Import converter
            # NOTE: You'll need to move map_to_session.py into your package
            from velocitycmdb.scripts.map_to_session import TopologyToInventoryConverter

            converter = TopologyToInventoryConverter()

            if progress_callback:
                progress_callback({
                    'stage': 'inventory',
                    'message': 'Loading topology data...',
                    'progress': 20
                })

            # Load topology
            topology_data = converter.load_topology_json(str(topology_file))

            if progress_callback:
                progress_callback({
                    'stage': 'inventory',
                    'message': 'Analyzing devices and grouping by site...',
                    'progress': 50
                })

            # Convert to inventory
            inventory_data = converter.convert_topology_to_inventory(topology_data)

            # Save inventory
            inventory_file = self.output_dir / 'sessions.yaml'

            if progress_callback:
                progress_callback({
                    'stage': 'inventory',
                    'message': 'Saving inventory...',
                    'progress': 80
                })

            converter.save_inventory_yaml(inventory_data, str(inventory_file))

            # Count stats
            site_count = len(inventory_data)
            device_count = sum(len(site['sessions']) for site in inventory_data)

            if progress_callback:
                progress_callback({
                    'stage': 'inventory',
                    'message': f'✓ Inventory created: {device_count} devices in {site_count} sites',
                    'progress': 100
                })

            logger.info(f"Inventory created: {device_count} devices, {site_count} sites")

            return {
                'success': True,
                'inventory_file': inventory_file,
                'site_count': site_count,
                'device_count': device_count,
                'inventory_data': inventory_data
            }

        except Exception as e:
            logger.exception("Inventory conversion failed")
            return {
                'success': False,
                'error': f"Inventory conversion error: {str(e)}"
            }

    def run_full_discovery(self,
                          seed_ip: str,
                          username: str,
                          password: str,
                          **kwargs) -> Dict:
        """
        Run complete discovery workflow: topology + inventory

        Args:
            seed_ip: Starting IP address
            username: Device username
            password: Device password
            **kwargs: Additional arguments for topology discovery

        Returns:
            Combined results from topology and inventory stages
        """
        progress_callback = kwargs.pop('progress_callback', None)

        # Stage 1: Topology discovery
        topology_result = self.run_topology_discovery(
            seed_ip=seed_ip,
            username=username,
            password=password,
            progress_callback=progress_callback,
            **kwargs
        )

        if not topology_result['success']:
            return topology_result

        # Stage 2: Convert to inventory
        inventory_result = self.convert_to_inventory(
            topology_file=topology_result['topology_file'],
            progress_callback=progress_callback
        )

        if not inventory_result['success']:
            return inventory_result

        # Combine results
        return {
            'success': True,
            'topology_file': topology_result['topology_file'],
            'topology_data': topology_result.get('topology_data'),
            'map_file': topology_result.get('map_file'),
            'svg_file': topology_result.get('svg_file'),
            'graphml_file': topology_result.get('graphml_file'),
            'drawio_file': topology_result.get('drawio_file'),
            'inventory_file': inventory_result['inventory_file'],
            'inventory_data': inventory_result['inventory_data'],
            'device_count': topology_result['device_count'],
            'site_count': inventory_result['site_count'],
            'site_name': topology_result.get('site_name', 'network')
        }