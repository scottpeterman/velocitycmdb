#!/usr/bin/env python3
"""
Setup configuration for VelocityCMDB

Traditional setup.py approach for PyPI packaging.
Works with MANIFEST.in for file inclusion.
"""
from setuptools import setup, find_packages
from pathlib import Path
import os


# Read version from velocitycmdb/__init__.py or cli.py

VERSION = "0.11.4"

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
if readme_path.exists():
    with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
        long_description = f.read()
else:
    long_description = "Tactical network CMDB with automated discovery, change detection, and operational intelligence"

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    with open(requirements_path, 'r', encoding='utf-8') as f:
        requirements = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]

setup(
    name="velocitycmdb",
    version=VERSION,
    author="Scott Peterman",
    author_email="scottpeterman@gmail.com",
    description="Tactical network CMDB with automated discovery, change detection, and operational intelligence",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/scottpeterman/velocitycmdb",
    project_urls={
        "Documentation": "https://github.com/scottpeterman/velocitycmdb/blob/main/README.md",
        "Source": "https://github.com/scottpeterman/velocitycmdb",
        "Tracker": "https://github.com/scottpeterman/velocitycmdb/issues",
    },

    # Find all packages under velocitycmdb/
    packages=find_packages(exclude=['tests', 'tests.*', 'docs']),

    # Classifiers for PyPI
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Intended Audience :: Information Technology",
        "Topic :: System :: Networking",
        "Topic :: System :: Networking :: Monitoring",
        "Topic :: System :: Systems Administration",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Environment :: Web Environment",
        "Framework :: Flask",
    ],

    # Python version requirement
    python_requires=">=3.10",

    # Core dependencies
    install_requires=requirements,

    # Package data - files to include in the package
    # MANIFEST.in handles the actual file selection
    package_data={
        "velocitycmdb": [
            # Flask templates and static files
            "app/templates/**/*.html",
            "app/static/**/*.*",
            "app/static/**/**/*.*",

            # TextFSM templates database
            "pcng/tfsm_templates.db",
            "pcng/command_templates.json",

            # Job definition files
            "pcng/jobs/*.json",

            # Database schema files (if you have them)
            "db/schema/*.sql",
        ],
    },

    # Include files specified in MANIFEST.in
    include_package_data=True,

    # CLI entry points
    # This creates the 'velocitycmdb' command that calls cli.py:main()
    entry_points={
        "console_scripts": [
            "velocitycmdb=velocitycmdb.cli:main",
        ],
    },

    # Optional dependencies
    # Install with: pip install velocitycmdb[ldap]
    # Note: LDAP is actually included in base install, these are true extras
    extras_require={
        "windows": [
            # Windows-specific packages (automatically excluded on other platforms)
            "pywin32>=311",
            "WMI>=1.5.1",
        ],
        "linux": [
            # Linux-specific packages (for PAM authentication)
            "python-pam>=2.0.2",
        ],
        "all": [
            # All optional features with platform markers
            "pywin32>=311; sys_platform == 'win32'",
            "WMI>=1.5.1; sys_platform == 'win32'",
            "python-pam>=2.0.2; sys_platform == 'linux'",
        ],
        "dev": [
            # Development and testing tools
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
        "docs": [
            # Documentation generation
            "sphinx>=5.0.0",
            "sphinx-rtd-theme>=1.2.0",
        ],
    },

    # Keywords for PyPI search
    keywords=[
        "network", "cmdb", "discovery", "monitoring",
        "cisco", "arista", "juniper", "netbox", "automation",
        "network-management", "configuration-management",
        "network-discovery", "lldp", "cdp", "textfsm"
    ],

    # Don't create a zip file
    zip_safe=False,
)

print(f"\nVelocityCMDB v{VERSION} setup complete!")
print("\nAfter installation, run:")
print("  velocitycmdb init    # Initialize data directory and databases")
print("  velocitycmdb run     # Start web interface")