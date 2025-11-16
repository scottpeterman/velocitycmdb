import ipaddress
import fnmatch


class SimpleSSHRouter:
    def __init__(self, rules):
        self.rules = rules

    def resolve_route(self, destination_host, destination_port=22):
        """
        Resolve routing decision for destination
        Returns: 'direct', 'proxy', or 'deny'
        """
        # Try to get IP address
        dest_ip = self._resolve_hostname(destination_host)

        for rule in self.rules:
            match_pattern = rule.get('match')
            if not match_pattern:
                continue

            if self._matches_rule(destination_host, dest_ip, match_pattern):
                action = rule.get('action', 'direct')
                print(f"Route matched: {match_pattern} -> {action}")
                return action

        # Default to direct if no rules match
        return 'direct'

    def _matches_rule(self, hostname, ip_addr, pattern):
        """Check if hostname/IP matches the pattern"""
        # IP network matching
        if '/' in pattern:
            try:
                if ip_addr and ipaddress.ip_address(ip_addr) in ipaddress.ip_network(pattern, strict=False):
                    return True
            except (ipaddress.AddressValueError, ValueError):
                pass

        # Hostname pattern matching
        if fnmatch.fnmatch(hostname.lower(), pattern.lower()):
            return True

        return False

    def _resolve_hostname(self, hostname):
        """Resolve hostname to IP address"""
        try:
            import socket
            return socket.gethostbyname(hostname)
        except socket.gaierror:
            return None