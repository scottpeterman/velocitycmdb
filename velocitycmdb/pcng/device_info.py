# device_info.py
from enum import Enum, auto
from datetime import datetime
import json
from typing import Dict, List, Optional, Any


class DeviceType(Enum):
    """Enum representing different types of network devices"""
    Unknown = 0
    CiscoIOS = 1
    CiscoNXOS = 2
    CiscoASA = 3
    AristaEOS = 4
    JuniperJunOS = 5
    HPProCurve = 6
    FortiOS = 7
    PaloAltoOS = 8
    Linux = 9
    FreeBSD = 10
    Windows = 11
    GenericUnix = 12

    def get_disable_paging_command(self) -> str:
        """Get the appropriate command to disable paging for this device type"""
        commands = {
            DeviceType.CiscoIOS: "terminal length 0",
            DeviceType.CiscoNXOS: "terminal length 0",
            DeviceType.CiscoASA: "terminal pager 0",
            DeviceType.AristaEOS: "terminal length 0",
            DeviceType.JuniperJunOS: "set cli screen-length 0",
            DeviceType.HPProCurve: "no page",
            DeviceType.FortiOS: "config system console\nset output standard\nend",
            DeviceType.PaloAltoOS: "set cli pager off",
            DeviceType.Linux: "export TERM=xterm; stty rows 1000",
            DeviceType.FreeBSD: "export TERM=xterm; stty rows 1000",
            DeviceType.Windows: "",  # Windows doesn't typically need paging disabled
            DeviceType.GenericUnix: "export TERM=xterm; stty rows 1000",
        }
        return commands.get(self, "")

    def get_identification_commands(self) -> List[str]:
        """Get identification commands specific to this device type"""
        commands = {
            DeviceType.CiscoIOS: ["show version", "show inventory", "show running-config | include hostname"],
            DeviceType.CiscoNXOS: ["show version", "show inventory", "show hostname"],
            DeviceType.CiscoASA: ["show version", "show inventory", "show running-config | include hostname"],
            DeviceType.AristaEOS: ["show version", "show inventory", "show hostname"],
            DeviceType.JuniperJunOS: ["show version", "show chassis hardware", "show configuration system host-name"],
            DeviceType.HPProCurve: ["show system-information", "show system", "show version"],
            DeviceType.FortiOS: ["get system status", "get hardware status", "get system interface physical"],
            DeviceType.PaloAltoOS: ["show system info", "show chassis inventory"],
            DeviceType.Linux: ["uname -a", "cat /etc/os-release", "hostname"],
            DeviceType.FreeBSD: ["uname -a", "hostname"],
            DeviceType.Windows: ["systeminfo", "hostname"],
            DeviceType.GenericUnix: ["uname -a", "hostname"],
        }
        return commands.get(self, ["show version"])


class DeviceInfo:
    """Class to store comprehensive information about a network device"""

    def __init__(self, host: str = "", port: int = 22, username: str = ""):
        # Basic connection information
        self.host: str = host
        self.port: int = port
        self.username: str = username

        # Device identification
        self.device_type: DeviceType = DeviceType.Unknown
        self.detected_prompt: Optional[str] = None
        self.disable_paging_command: Optional[str] = None

        # Device details
        self.hostname: Optional[str] = None
        self.password: Optional[str] = None
        self.model: Optional[str] = None
        self.version: Optional[str] = None
        self.serial_number: Optional[str] = None

        # Additional properties for extended information
        self.is_virtual_device: bool = False
        self.platform: Optional[str] = None
        self.uptime: Optional[str] = None
        self.additional_info: Dict[str, str] = {}

        # Network information
        self.interfaces: Dict[str, str] = {}
        self.ip_addresses: List[str] = []

        # Hardware information
        self.cpu_info: Optional[str] = None
        self.memory_info: Optional[str] = None
        self.storage_info: Optional[str] = None

        # Raw output and command results
        self.raw_output: Optional[str] = None
        self.command_outputs: Dict[str, str] = {}

        # Timestamp of when the fingerprint was created
        self.fingerprint_time: datetime = datetime.now()

    @property
    def success(self) -> bool:
        """Check if the fingerprinting was successful"""
        return self.device_type != DeviceType.Unknown and self.detected_prompt is not None

    def get_interface_summary(self) -> str:
        """Get interface/IP information as a formatted string"""
        if not self.interfaces:
            return "No interface information available"

        result = ["Interface Information:"]
        for iface, details in self.interfaces.items():
            result.append(f"  {iface}: {details}")

        return "\n".join(result)

    def get_summary(self) -> str:
        """Get a summary of the device"""
        result = [
            f"Device: {self.host}:{self.port}",
            f"Type: {self.device_type.name}"
        ]

        if self.hostname:
            result.append(f"Hostname: {self.hostname}")

        if self.model:
            result.append(f"Model: {self.model}")

        if self.version:
            result.append(f"Version: {self.version}")

        if self.serial_number:
            result.append(f"Serial Number: {self.serial_number}")

        if self.disable_paging_command:
            result.append(f"Disable Paging Command: {self.disable_paging_command}")

        if self.ip_addresses:
            result.append("IP Addresses:")
            for ip in self.ip_addresses:
                result.append(f"  {ip}")

        result.append(f"Fingerprint Time: {self.fingerprint_time}")

        return "\n".join(result)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the device info to a dictionary (for JSON serialization)"""
        return {
            "host": self.host,
            "port": self.port,
            "device_type": self.device_type.value,
            "detected_prompt": self.detected_prompt,
            "disable_paging_command": self.disable_paging_command,
            "hostname": self.hostname,
            "model": self.model,
            "version": self.version,
            "serial_number": self.serial_number,
            "is_virtual_device": self.is_virtual_device,
            "platform": self.platform,
            "uptime": self.uptime,
            "additional_info": self.additional_info,
            "interfaces": self.interfaces,
            "ip_addresses": self.ip_addresses,
            "cpu_info": self.cpu_info,
            "memory_info": self.memory_info,
            "storage_info": self.storage_info,
            "command_outputs": self.command_outputs,
            "fingerprint_time": self.fingerprint_time.isoformat(),
            "success": self.success
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert the device info to a JSON string"""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeviceInfo':
        """Create a DeviceInfo object from a dictionary"""
        device_info = cls()

        device_info.host = data.get("host", "")
        device_info.port = data.get("port", 22)
        device_info.device_type = DeviceType(data.get("device_type", 0))
        device_info.detected_prompt = data.get("detected_prompt")
        device_info.disable_paging_command = data.get("disable_paging_command")
        device_info.hostname = data.get("hostname")
        device_info.model = data.get("model")
        device_info.version = data.get("version")
        device_info.serial_number = data.get("serial_number")
        device_info.is_virtual_device = data.get("is_virtual_device", False)
        device_info.platform = data.get("platform")
        device_info.uptime = data.get("uptime")
        device_info.additional_info = data.get("additional_info", {})
        device_info.interfaces = data.get("interfaces", {})
        device_info.ip_addresses = data.get("ip_addresses", [])
        device_info.cpu_info = data.get("cpu_info")
        device_info.memory_info = data.get("memory_info")
        device_info.storage_info = data.get("storage_info")
        device_info.command_outputs = data.get("command_outputs", {})

        if "fingerprint_time" in data:
            try:
                device_info.fingerprint_time = datetime.fromisoformat(data["fingerprint_time"])
            except (ValueError, TypeError):
                device_info.fingerprint_time = datetime.now()

        return device_info

    @classmethod
    def from_json(cls, json_str: str) -> 'DeviceInfo':
        """Create a DeviceInfo object from a JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    # Add this method to the DeviceInfo class in device_info.py

    def to_c_sharp_compatible_json(self, indent: int = 2) -> str:
        """Convert the device info to a JSON string that matches the C# format"""
        data = {
            "Host": self.host,
            "Port": self.port,
            "DeviceType": self.device_type.value,
            "DetectedPrompt": self.detected_prompt,
            "DisablePagingCommand": self.disable_paging_command,
            "Hostname": self.hostname,
            "Password": None,  # Always null for security
            "Model": self.model,
            "Version": self.version,
            "SerialNumber": self.serial_number,
            "IsVirtualDevice": self.is_virtual_device,
            "Platform": self.platform,
            "UpTime": self.uptime,
            "AdditionalInfo": self.additional_info,
            "Interfaces": self.interfaces,
            "IPAddresses": self.ip_addresses,
            "CPUInfo": self.cpu_info,
            "MemoryInfo": self.memory_info,
            "StorageInfo": self.storage_info,
            "CommandOutputs": self.command_outputs,
            "FingerprintTime": self.fingerprint_time.isoformat(),
            "Success": self.success
        }
        return json.dumps(data, indent=indent)