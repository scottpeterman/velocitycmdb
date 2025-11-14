#!/usr/bin/env python3
"""
POC: Map Enhancement CLI
Takes a topology JSON file and creates icon-enriched GraphML and DrawIO maps.
"""

import argparse
import json
import sys
from pathlib import Path

# Import the map exporters from secure_cartography
from secure_cartography.drawio_mapper2 import NetworkDrawioExporter
from secure_cartography.graphml_mapper4 import NetworkGraphMLExporter


def enhance_maps(json_path: Path,
                 output_dir: Path = None,
                 layout: str = 'tree',
                 include_endpoints: bool = True,
                 icons_dir: str = None):
    """
    Generate enhanced network maps with vendor icons from JSON topology.

    Args:
        json_path: Path to JSON topology file
        output_dir: Output directory (defaults to same dir as JSON)
        layout: Layout algorithm (grid, tree, balloon)
        include_endpoints: Include endpoint devices in visualization
        icons_dir: Custom icon library directory
    """

    # Validate input file
    if not json_path.exists():
        print(f"Error: Input file not found: {json_path}", file=sys.stderr)
        return False

    # Set output directory
    if output_dir is None:
        output_dir = json_path.parent
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Determine icons directory
    if icons_dir is None:
        # Try to find icons_lib relative to script or in current directory
        script_dir = Path(__file__).parent
        if (script_dir / 'icons_lib').exists():
            icons_dir = str(script_dir / 'icons_lib')
        elif (Path.cwd() / 'icons_lib').exists():
            icons_dir = str(Path.cwd() / 'icons_lib')
        else:
            # Check secure_cartography package location
            try:
                from secure_cartography import __file__ as sc_file
                sc_dir = Path(sc_file).parent
                if (sc_dir / 'icons_lib').exists():
                    icons_dir = str(sc_dir / 'icons_lib')
            except:
                pass

    if icons_dir:
        print(f"Using icons from: {icons_dir}")
    else:
        print("Warning: No icons directory found, using default icons")
        icons_dir = './icons_lib'

    try:
        # Load topology data
        print(f"Loading topology from: {json_path}")
        with open(json_path, 'r') as f:
            network_data = json.load(f)

        node_count = len(network_data)
        print(f"Loaded topology with {node_count} nodes")

        # Determine output file names
        base_name = json_path.stem
        graphml_output = output_dir / f"{base_name}.graphml"
        drawio_output = output_dir / f"{base_name}.drawio"

        # Common export parameters
        common_params = {
            'include_endpoints': include_endpoints,
            'use_icons': True,
            'layout_type': layout,
            'icons_dir': icons_dir
        }

        print(f"\nConfiguration:")
        print(f"  Layout: {layout}")
        print(f"  Endpoints: {'included' if include_endpoints else 'excluded'}")
        print(f"  Icons: enabled")

        # Generate GraphML
        print(f"\n[1/2] Generating GraphML...")
        try:
            graphml_exporter = NetworkGraphMLExporter(**common_params)
            graphml_exporter.export_to_graphml(network_data, graphml_output)
            print(f"  ✓ Created: {graphml_output}")
        except Exception as e:
            print(f"  ✗ GraphML export failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False

        # Generate DrawIO
        print(f"\n[2/2] Generating Draw.io...")
        try:
            drawio_exporter = NetworkDrawioExporter(**common_params)
            drawio_exporter.export_to_drawio(network_data, drawio_output)
            print(f"  ✓ Created: {drawio_output}")
        except Exception as e:
            print(f"  ✗ Draw.io export failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False

        print(f"\n✓ Enhancement complete!")
        print(f"\nOutput files:")
        print(f"  {graphml_output}")
        print(f"  {drawio_output}")

        return True

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {json_path}: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Enhance network topology maps with vendor-specific icons',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Basic usage - enhance maps in same directory as JSON
  %(prog)s network_topology.json

  # Specify output directory and layout
  %(prog)s topology.json --output-dir ./enhanced_maps --layout tree

  # Exclude endpoints and use balloon layout
  %(prog)s topology.json --no-endpoints --layout balloon

  # Use custom icon library
  %(prog)s topology.json --icons-dir /path/to/custom/icons

Available layouts:
  grid    - Grid layout (default)
  tree    - Hierarchical tree layout (top-down)
  balloon - Radial/balloon layout (center-out)
        '''
    )

    parser.add_argument(
        'json_file',
        type=Path,
        help='JSON topology file from Secure Cartography'
    )

    parser.add_argument(
        '--output-dir',
        type=Path,
        help='Output directory (default: same as input file)'
    )

    parser.add_argument(
        '--layout',
        choices=['grid', 'tree', 'balloon'],
        default='tree',
        help='Layout algorithm (default: tree)'
    )

    parser.add_argument(
        '--no-endpoints',
        action='store_true',
        help='Exclude endpoint devices from visualization'
    )

    parser.add_argument(
        '--icons-dir',
        type=str,
        help='Custom icon library directory (default: auto-detect)'
    )

    args = parser.parse_args()

    success = enhance_maps(
        args.json_file,
        args.output_dir,
        args.layout,
        not args.no_endpoints,
        args.icons_dir
    )

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())