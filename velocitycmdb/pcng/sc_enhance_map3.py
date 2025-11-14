#!/usr/bin/env python3
"""
POC: Map Enhancement CLI
Takes a topology JSON file and creates icon-enriched GraphML, DrawIO, and Mermaid-based SVG maps.
"""

import argparse
import json
import sys
from pathlib import Path
import networkx as nx
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QEventLoop, QTimer

# Import the map exporters from secure_cartography
from secure_cartography.drawio_mapper2 import NetworkDrawioExporter
from secure_cartography.graphml_mapper4 import NetworkGraphMLExporter


class MermaidSVGGenerator:
    """Generate SVG from Mermaid diagram using Qt WebEngine"""

    def __init__(self, dark_mode=True, include_endpoints=True):
        self.dark_mode = dark_mode
        self.include_endpoints = include_endpoints
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)
        self.web_view = QWebEngineView()
        self.svg_content = None

    def analyze_topology(self, topology_data):
        """Analyze network topology using NetworkX"""
        G = nx.Graph()

        added_edges = set()
        for node, data in topology_data.items():
            G.add_node(node,
                       ip=data['node_details'].get('ip', ''),
                       platform=data['node_details'].get('platform', ''))

            for peer, peer_data in data['peers'].items():
                # Mark if this peer is a leaf (not in main topology)
                is_leaf = peer not in topology_data

                # Skip leaf nodes if include_endpoints is False
                if not self.include_endpoints and is_leaf:
                    continue

                if peer not in G:
                    G.add_node(peer,
                               ip=peer_data.get('ip', ''),
                               platform=peer_data.get('platform', ''),
                               is_leaf=is_leaf)

                edge_key = tuple(sorted([node, peer]))
                if edge_key not in added_edges:
                    connections = peer_data.get('connections', [])
                    label = f"{connections[0][0]} - {connections[0][1]}" if connections else ""
                    G.add_edge(node, peer, connection=label)
                    added_edges.add(edge_key)

        # Calculate topology metrics
        degrees = dict(G.degree())
        betweenness = nx.betweenness_centrality(G)
        clustering = nx.clustering(G)

        # Classify nodes
        for node in G.nodes():
            is_core = degrees[node] > 2 and betweenness[node] > 0.1
            is_edge = degrees[node] == 1 or clustering[node] == 0
            is_gateway = betweenness[node] > 0.15 and degrees[node] <= 3

            G.nodes[node]['role'] = 'core' if is_core else 'gateway' if is_gateway else 'edge'
            G.nodes[node]['metric_degree'] = degrees[node]
            G.nodes[node]['metric_betweenness'] = betweenness[node]
            G.nodes[node]['metric_clustering'] = clustering[node]

        return G

    def generate_mermaid(self, network_graph, layout='TD'):
        """Generate Mermaid diagram code"""
        if not network_graph:
            return "graph TD\nA[No data loaded]"

        lines = [f"graph {layout}"]

        processed_nodes = set()
        processed_connections = set()

        for node in network_graph.nodes():
            node_id = node.replace("-", "_").replace(".", "_").replace(" ", "_")
            node_data = network_graph.nodes[node]

            if node_id not in processed_nodes:
                if node_data.get('is_leaf', False):
                    # Simple label for leaf nodes - single line only
                    label = node
                else:
                    # Multi-line label using ` (backticks) instead of <br> for better compatibility
                    info_parts = [
                        node,
                        node_data.get('ip', 'N/A'),
                        node_data.get('platform', 'N/A')
                    ]
                    # Use \n for line breaks in backtick strings
                    label = '\\n'.join(info_parts)

                # Use backticks for multi-line labels - more reliable than quotes with <br>
                role = 'edge' if node_data.get('is_leaf', False) else node_data.get('role', 'core')
                lines.append(f'{node_id}["`{label}`"]:::{role}')
                processed_nodes.add(node_id)

            for neighbor in network_graph.neighbors(node):
                neighbor_id = neighbor.replace("-", "_").replace(".", "_").replace(" ", "_")
                connection_pair = tuple(sorted([node_id, neighbor_id]))

                if connection_pair not in processed_connections:
                    edge_data = network_graph.edges[node, neighbor]
                    connection_label = edge_data.get('connection', '')
                    if connection_label:
                        # Escape special characters in labels
                        clean_label = connection_label.replace('"', '\\"')
                        lines.append(f'{node_id} ---|"{clean_label}"| {neighbor_id}')
                    else:
                        lines.append(f'{node_id} --- {neighbor_id}')
                    processed_connections.add(connection_pair)

        return "\n".join(lines)

    def generate_html(self, mermaid_code):
        """Generate HTML with Mermaid diagram"""
        theme = "dark" if self.dark_mode else "default"
        bg_color = "#2a2a2a" if self.dark_mode else "#ffffff"  # Charcoal grey instead of pure black

        return f'''<!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
        <script>
            mermaid.initialize({{
                startOnLoad: true,
                theme: '{theme}',
                securityLevel: 'loose',
                themeVariables: {{
                    primaryColor: '#3a3a3a',
                    primaryTextColor: '#e0e0e0',
                    primaryBorderColor: '#555555',
                    lineColor: '#666666',
                    secondaryColor: '#2a2a2a',
                    tertiaryColor: '#1a1a1a',
                    background: '#2a2a2a',
                    mainBkg: '#3a3a3a',
                    secondBkg: '#2a2a2a',
                    tertiaryBkg: '#1a1a1a',
                    nodeBorder: '#555555',
                    clusterBkg: '#2a2a2a',
                    clusterBorder: '#555555',
                    edgeLabelBackground: '#2a2a2a',
                    fontFamily: 'Arial, sans-serif',
                    fontSize: '14px'
                }},
                flowchart: {{
                    curve: 'basis',
                    padding: 20,
                    nodeSpacing: 50,
                    rankSpacing: 50,
                    diagramPadding: 20,
                    htmlLabels: true,
                    useMaxWidth: true
                }}
            }});
        </script>
        <style>
            body {{ 
                margin: 0; 
                padding: 20px;
                background-color: {bg_color};
            }}
            /* Override Mermaid's default styling for rounded corners */
            .node rect {{
                rx: 8 !important;
                ry: 8 !important;
            }}
            /* Style adjustments for better visibility */
            .edgeLabel {{
                background-color: {bg_color} !important;
            }}
        </style>
    </head>
    <body>
        <div class="mermaid" id="diagram">
    {mermaid_code}
        </div>
        <script>
            function getSVG() {{
                const svgElement = document.querySelector("#diagram svg");
                if (svgElement) {{
                    // Apply rounded corners to all rect elements
                    svgElement.querySelectorAll('rect').forEach(rect => {{
                        rect.setAttribute('rx', '8');
                        rect.setAttribute('ry', '8');
                    }});
                    return svgElement.outerHTML;
                }}
                return '';
            }}
        </script>
    </body>
    </html>'''

    def render_and_save(self, topology_data, output_path, layout='TD'):
        """Generate SVG from topology data"""
        print(f"  Analyzing topology with NetworkX...")
        network_graph = self.analyze_topology(topology_data)

        print(f"  Generating Mermaid diagram (layout: {layout})...")
        mermaid_code = self.generate_mermaid(network_graph, layout)

        print(f"  Rendering SVG with WebEngine...")
        html_content = self.generate_html(mermaid_code)

        # Load HTML in web view
        self.web_view.setHtml(html_content)

        # Wait for page to load
        loop = QEventLoop()
        self.web_view.loadFinished.connect(loop.quit)

        # Give extra time for Mermaid to render
        QTimer.singleShot(10000, loop.quit)
        loop.exec()

        # Extract SVG content
        self.svg_content = None

        def handle_svg(content):
            self.svg_content = content

        self.web_view.page().runJavaScript("getSVG()", handle_svg)

        # Wait for JavaScript to execute
        loop = QEventLoop()
        QTimer.singleShot(1000, loop.quit)
        loop.exec()

        # Save SVG
        if self.svg_content:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(self.svg_content)
            return True
        else:
            print(f"  Warning: Failed to extract SVG content")
            return False


def enhance_maps(json_path: Path,
                 output_dir: Path = None,
                 layout: str = 'tree',
                 include_endpoints: bool = True,
                 svg_include_endpoints: bool = True,
                 icons_dir: str = None,
                 svg_layout: str = 'TD',
                 dark_mode: bool = True,
                 skip_svg: bool = False):
    """
    Generate enhanced network maps with vendor icons from JSON topology.

    Args:
        json_path: Path to JSON topology file
        output_dir: Output directory (defaults to same dir as JSON)
        layout: Layout algorithm for GraphML/DrawIO (grid, tree, balloon)
        include_endpoints: Include endpoint devices in GraphML/DrawIO
        svg_include_endpoints: Include endpoint devices in SVG
        icons_dir: Custom icon library directory
        svg_layout: Mermaid layout (TD=top-down, LR=left-right)
        dark_mode: Use dark theme for SVG
        skip_svg: Skip SVG generation (faster if you only want GraphML/DrawIO)
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
        script_dir = Path(__file__).parent
        if (script_dir / 'icons_lib').exists():
            icons_dir = str(script_dir / 'icons_lib')
        elif (Path.cwd() / 'icons_lib').exists():
            icons_dir = str(Path.cwd() / 'icons_lib')
        else:
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
        svg_output = output_dir / f"{base_name}.svg"

        # Common export parameters
        common_params = {
            'include_endpoints': include_endpoints,
            'use_icons': True,
            'layout_type': layout,
            'icons_dir': icons_dir
        }

        print(f"\nConfiguration:")
        print(f"  Layout: {layout}")
        print(f"  GraphML/DrawIO Endpoints: {'included' if include_endpoints else 'excluded'}")
        print(f"  SVG Endpoints: {'included' if svg_include_endpoints else 'excluded'}")
        print(f"  Icons: enabled")
        print(f"  SVG Layout: {svg_layout}")
        print(f"  Dark Mode: {dark_mode}")

        # Generate GraphML
        print(f"\n[1/3] Generating GraphML...")
        try:
            graphml_exporter = NetworkGraphMLExporter(**common_params)
            graphml_exporter.export_to_graphml(network_data, graphml_output)
            print(f"Created: {graphml_output}")
        except Exception as e:
            print(f"  ✗ GraphML export failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False

        # Generate DrawIO
        print(f"\n[2/3] Generating Draw.io...")
        try:
            drawio_exporter = NetworkDrawioExporter(**common_params)
            drawio_exporter.export_to_drawio(network_data, drawio_output)
            print(f"Created: {drawio_output}")
        except Exception as e:
            print(f"Draw.io export failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False

        # Generate SVG (unless skipped)
        if not skip_svg:
            print(f"\n[3/3] Generating enhanced SVG with Mermaid...")
            try:
                svg_gen = MermaidSVGGenerator(dark_mode=dark_mode, include_endpoints=svg_include_endpoints)
                success = svg_gen.render_and_save(network_data, svg_output, svg_layout)
                if success:
                    print(f"Created: {svg_output}")
                else:
                    print(f"SVG generation failed", file=sys.stderr)
            except Exception as e:
                print(f"SVG export failed: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
        else:
            print(f"\n[3/3] Skipping SVG generation (--skip-svg)")

        print(f"\n Enhancement complete!")
        print(f"\nOutput files:")
        print(f"  {graphml_output}")
        print(f"  {drawio_output}")
        if not skip_svg:
            print(f"  {svg_output}")

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
        description='Enhance network topology maps with vendor-specific icons and improved SVG',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Basic usage - enhance all formats with full detail
  %(prog)s network_topology.json

  # Specify output directory and layouts
  %(prog)s topology.json --output-dir ./enhanced_maps --layout tree --svg-layout LR

  # Exclude endpoints from SVG only (keep them in GraphML/DrawIO for detailed work)
  %(prog)s topology.json --svg-no-endpoints

  # Exclude endpoints from everything
  %(prog)s topology.json --no-endpoints --svg-no-endpoints

  # Clean SVG for presentation, full GraphML/DrawIO for engineering
  %(prog)s topology.json --svg-no-endpoints --light-mode

  # Skip SVG for faster processing
  %(prog)s topology.json --skip-svg

Available layouts:
  GraphML/DrawIO: grid, tree, balloon
  SVG (Mermaid): TD (top-down), LR (left-right)
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
        help='Layout algorithm for GraphML/DrawIO (default: tree)'
    )

    parser.add_argument(
        '--svg-layout',
        choices=['TD', 'LR'],
        default='TD',
        help='Mermaid layout for SVG: TD (top-down) or LR (left-right) (default: TD)'
    )

    parser.add_argument(
        '--no-endpoints',
        action='store_true',
        help='Exclude endpoint devices from GraphML/DrawIO visualization'
    )

    parser.add_argument(
        '--svg-no-endpoints',
        action='store_true',
        help='Exclude endpoint devices from SVG visualization (useful for cleaner web views)'
    )

    parser.add_argument(
        '--light-mode',
        action='store_true',
        help='Use light theme for SVG (default: dark mode)'
    )

    parser.add_argument(
        '--skip-svg',
        action='store_true',
        help='Skip SVG generation for faster processing'
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
        not args.svg_no_endpoints,
        args.icons_dir,
        args.svg_layout,
        not args.light_mode,
        args.skip_svg
    )

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())