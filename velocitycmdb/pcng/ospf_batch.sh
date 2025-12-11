# OSPFv2 only
python ospf_to_topology_v2.py -i ./capture/ospf_analytics --overview-dir ./capture/ospf_process -o topo_v2.json --protocol 2 -v
python ospf_to_interactive_v2.py -i ./capture/ospf_analytics --overview-dir ./capture/ospf_process -o data_v2.json --protocol 2 -v

# OSPFv3 only
python ospf_to_topology_v2.py -i ./capture/ospfv3_analytics --overview-dir ./capture/ospf_process -o topo_v3.json --protocol 3 -v
python ospf_to_interactive_v2.py -i ./capture/ospfv3_analytics --overview-dir ./capture/ospf_process -o data_v3.json --protocol 3 -v