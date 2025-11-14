#!/usr/bin/env python3
"""
Opengear Port Inventory Collector
Collects serial console port mappings from Opengear devices
"""

import paramiko
import re
import json
import csv
from pathlib import Path
from typing import Dict, List, Optional
import click
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OpengearPortInventory:
    """Collect port inventory from Opengear console servers"""

    def __init__(self, username: str, password: str, enable_password: Optional[str] = None):
        self.username = username
        self.password = password
        self.enable_password = enable_password

    def connect_ssh(self, host: str, port: int = 22, timeout: int = 10) -> Optional[paramiko.SSHClient]:
        """Establish SSH connection to Opengear device"""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            client.connect(
                host,
                port=port,
                username=self.username,
                password=self.password,
                timeout=timeout,
                look_for_keys=False,
                allow_agent=False
            )

            logger.info(f"Connected to {host}")
            return client

        except Exception as e:
            logger.error(f"Failed to connect to {host}: {e}")
            return None

    def execute_command(self, client: paramiko.SSHClient, command: str) -> str:
        """Execute command and return output"""
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=30)
            output = stdout.read().decode('utf-8', errors='ignore')
            return output
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return ""

    def get_config_ports(self, client: paramiko.SSHClient) -> List[Dict]:
        """
        Get port configuration from Opengear device
        Uses config -g command to get port settings
        """
        ports = []

        # Get list of serial ports
        output = self.execute_command(client, "config -g config.ports.port")

        if not output:
            return ports

        # Parse port list
        port_numbers = []
        for line in output.splitlines():
            # Looking for lines like: config.ports.port01.label
            match = re.search(r'config\.ports\.port(\d+)', line)
            if match:
                port_num = match.group(1)
                if port_num not in port_numbers:
                    port_numbers.append(port_num)

        logger.info(f"Found {len(port_numbers)} ports")

        # Get details for each port
        for port_num in sorted(port_numbers):
            port_data = self.get_port_details(client, port_num)
            if port_data:
                ports.append(port_data)

        return ports

    def get_port_details(self, client: paramiko.SSHClient, port_num: str) -> Optional[Dict]:
        """Get detailed configuration for a specific port"""
        try:
            port_info = {
                'port': f"port{port_num}",
                'port_number': int(port_num)
            }

            # Get port configuration fields
            fields = {
                'label': f'config.ports.port{port_num}.label',
                'mode': f'config.ports.port{port_num}.mode',
                'speed': f'config.ports.port{port_num}.speed',
                'databits': f'config.ports.port{port_num}.databits',
                'stopbits': f'config.ports.port{port_num}.stopbits',
                'parity': f'config.ports.port{port_num}.parity',
                'flowcontrol': f'config.ports.port{port_num}.flowcontrol',
                'protocol': f'config.ports.port{port_num}.protocol',
                'logging': f'config.ports.port{port_num}.logging',
            }

            for field, config_path in fields.items():
                output = self.execute_command(client, f"config -g {config_path}")
                if output and '=' in output:
                    value = output.split('=', 1)[1].strip().strip('"')
                    port_info[field] = value if value else None
                else:
                    port_info[field] = None

            return port_info

        except Exception as e:
            logger.error(f"Failed to get port{port_num} details: {e}")
            return None

    def get_port_status(self, client: paramiko.SSHClient) -> Dict[str, Dict]:
        """
        Get current port status (DCD signal state)
        Uses pmshell command if available
        """
        status_map = {}

        try:
            # Try to get port status using pmshell
            output = self.execute_command(client, "pmshell portstatus")

            for line in output.splitlines():
                # Parse lines like: port01: DCD=1
                match = re.match(r'(port\d+):\s+DCD=([01])', line)
                if match:
                    port_name = match.group(1)
                    dcd_state = "connected" if match.group(2) == "1" else "disconnected"
                    status_map[port_name] = {'dcd': dcd_state}

        except Exception as e:
            logger.warning(f"Could not get port status: {e}")

        return status_map

    def collect_inventory(self, host: str, device_name: str) -> Dict:
        """Collect complete port inventory from device"""
        logger.info(f"Collecting inventory from {device_name} ({host})")

        inventory = {
            'device_name': device_name,
            'host': host,
            'timestamp': datetime.now().isoformat(),
            'ports': [],
            'total_ports': 0
        }

        client = self.connect_ssh(host)
        if not client:
            return inventory

        try:
            # Get system info
            hostname_output = self.execute_command(client, "config -g config.system.name")
            if hostname_output and '=' in hostname_output:
                inventory['hostname'] = hostname_output.split('=', 1)[1].strip().strip('"')

            model_output = self.execute_command(client, "config -g config.system.model")
            if model_output and '=' in model_output:
                inventory['model'] = model_output.split('=', 1)[1].strip().strip('"')

            # Get port configurations
            ports = self.get_config_ports(client)

            # Get port status
            status_map = self.get_port_status(client)

            # Merge status into port data
            for port in ports:
                port_name = port['port']
                if port_name in status_map:
                    port.update(status_map[port_name])

            inventory['ports'] = ports
            inventory['total_ports'] = len(ports)

            logger.info(f"Collected {len(ports)} port configurations")

        finally:
            client.close()

        return inventory

    def save_json(self, inventory: Dict, output_file: Path):
        """Save inventory to JSON file"""
        output_file.write_text(json.dumps(inventory, indent=2))
        logger.info(f"Saved JSON to {output_file}")

    def save_csv(self, inventory: Dict, output_file: Path):
        """Save inventory to CSV file"""
        if not inventory['ports']:
            logger.warning("No ports to save")
            return

        fieldnames = ['device_name', 'host', 'port', 'port_number', 'label',
                      'mode', 'speed', 'databits', 'stopbits', 'parity',
                      'flowcontrol', 'protocol', 'logging', 'dcd']

        with output_file.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for port in inventory['ports']:
                row = {
                    'device_name': inventory['device_name'],
                    'host': inventory['host'],
                    **port
                }
                writer.writerow(row)

        logger.info(f"Saved CSV to {output_file}")

    def process_device_list(self, devices: List[Dict], output_dir: Path):
        """Process multiple devices and save inventories"""
        output_dir.mkdir(exist_ok=True, parents=True)

        all_inventories = []

        for device in devices:
            device_name = device.get('name', device['host'])
            host = device['host']

            inventory = self.collect_inventory(host, device_name)
            all_inventories.append(inventory)

            # Save individual device files
            device_json = output_dir / f"{device_name}_ports.json"
            self.save_json(inventory, device_json)

        # Save combined CSV
        combined_csv = output_dir / "all_opengear_ports.csv"
        self.save_combined_csv(all_inventories, combined_csv)

        logger.info(f"Processed {len(devices)} devices")

    def save_combined_csv(self, inventories: List[Dict], output_file: Path):
        """Save all inventories to a single CSV"""
        fieldnames = ['device_name', 'host', 'port', 'port_number', 'label',
                      'mode', 'speed', 'databits', 'stopbits', 'parity',
                      'flowcontrol', 'protocol', 'logging', 'dcd']

        with output_file.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for inventory in inventories:
                for port in inventory.get('ports', []):
                    row = {
                        'device_name': inventory['device_name'],
                        'host': inventory['host'],
                        **port
                    }
                    writer.writerow(row)

        logger.info(f"Saved combined CSV to {output_file}")


@click.command()
@click.option('--host', help='Single Opengear host to inventory')
@click.option('--device-name', help='Device name for single host')
@click.option('--devices-file', type=click.Path(exists=True), help='JSON file with list of devices')
@click.option('--username', '-u', required=True, help='SSH username')
@click.option('--password', '-p', required=True, help='SSH password')
@click.option('--output-dir', default='opengear_inventory', help='Output directory for inventory files')
@click.option('--format', type=click.Choice(['json', 'csv', 'both']), default='both', help='Output format')
def main(host, device_name, devices_file, username, password, output_dir, format):
    """Collect port inventory from Opengear console servers"""

    output_path = Path(output_dir)
    collector = OpengearPortInventory(username, password)

    if host:
        # Single device
        device_name = device_name or host
        inventory = collector.collect_inventory(host, device_name)

        if format in ['json', 'both']:
            json_file = output_path / f"{device_name}_ports.json"
            output_path.mkdir(exist_ok=True, parents=True)
            collector.save_json(inventory, json_file)

        if format in ['csv', 'both']:
            csv_file = output_path / f"{device_name}_ports.csv"
            output_path.mkdir(exist_ok=True, parents=True)
            collector.save_csv(inventory, csv_file)

    elif devices_file:
        # Multiple devices from file
        devices = json.loads(Path(devices_file).read_text())
        collector.process_device_list(devices, output_path)

    else:
        logger.error("Must specify either --host or --devices-file")
        return 1

    logger.info("Inventory collection complete!")


if __name__ == '__main__':
    main()