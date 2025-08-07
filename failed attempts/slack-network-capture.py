#!/usr/bin/env python3

import subprocess
import time
import sys
import json
from datetime import datetime
from collections import defaultdict

class NetworkCapture:
    def __init__(self):
        self.baseline_connections = {}
        self.huddle_connections = {}
        self.is_capturing_huddle = False
        
    def get_all_connections(self):
        """Capture ALL network connections for Slack processes"""
        connections = defaultdict(list)
        
        try:
            # Get all Slack PIDs
            pids_cmd = "pgrep -f Slack"
            pids_result = subprocess.run(pids_cmd, shell=True, capture_output=True, text=True)
            pids = [p.strip() for p in pids_result.stdout.strip().split('\n') if p.strip()]
            
            for pid in pids:
                # Get process name
                name_cmd = f"ps -p {pid} -o comm="
                name_result = subprocess.run(name_cmd, shell=True, capture_output=True, text=True)
                process_name = name_result.stdout.strip()
                
                # Get ALL network connections (not just UDP)
                lsof_cmd = f"sudo lsof -p {pid} -i -n -P 2>/dev/null"
                lsof_result = subprocess.run(lsof_cmd, shell=True, capture_output=True, text=True)
                
                for line in lsof_result.stdout.strip().split('\n')[1:]:  # Skip header
                    if line and ('TCP' in line or 'UDP' in line):
                        parts = line.split()
                        if len(parts) >= 9:
                            protocol = 'TCP' if 'TCP' in parts[7] else 'UDP'
                            connection = parts[8]
                            
                            # Parse connection details
                            conn_info = {
                                'protocol': protocol,
                                'connection': connection,
                                'process': process_name,
                                'pid': pid
                            }
                            
                            # Extract ports if present
                            if '->' in connection:
                                local, remote = connection.split('->')
                                if ':' in local:
                                    conn_info['local_port'] = local.split(':')[-1]
                                if ':' in remote:
                                    conn_info['remote_port'] = remote.split(':')[-1]
                                    conn_info['remote_host'] = ':'.join(remote.split(':')[:-1])
                            elif ':' in connection:
                                conn_info['local_port'] = connection.split(':')[-1]
                            
                            connections[protocol].append(conn_info)
                
                # Also try netstat for additional info
                netstat_cmd = f"sudo netstat -anp 2>/dev/null | grep {pid}"
                netstat_result = subprocess.run(netstat_cmd, shell=True, capture_output=True, text=True)
                
                # Count connections by state
                established = netstat_result.stdout.count('ESTABLISHED')
                listen = netstat_result.stdout.count('LISTEN')
                if established > 0 or listen > 0:
                    connections['stats'].append({
                        'pid': pid,
                        'process': process_name,
                        'established': established,
                        'listening': listen
                    })
        
        except Exception as e:
            print(f"Error capturing: {e}")
        
        return dict(connections)
    
    def analyze_differences(self):
        """Analyze differences between baseline and huddle connections"""
        if not self.baseline_connections or not self.huddle_connections:
            return None
        
        print("\n" + "="*80)
        print("📊 NETWORK CONNECTION ANALYSIS")
        print("="*80)
        
        # UDP Analysis
        baseline_udp = self.baseline_connections.get('UDP', [])
        huddle_udp = self.huddle_connections.get('UDP', [])
        
        print(f"\n🔷 UDP CONNECTIONS:")
        print(f"  Baseline: {len(baseline_udp)} connections")
        print(f"  Huddle: {len(huddle_udp)} connections")
        print(f"  Difference: {len(huddle_udp) - len(baseline_udp):+d}")
        
        # Find new UDP connections in huddle
        baseline_ports = set()
        for conn in baseline_udp:
            if 'remote_port' in conn:
                baseline_ports.add(conn['remote_port'])
            if 'local_port' in conn:
                baseline_ports.add(conn['local_port'])
        
        huddle_ports = set()
        new_connections = []
        for conn in huddle_udp:
            if 'remote_port' in conn:
                huddle_ports.add(conn['remote_port'])
                if conn['remote_port'] not in baseline_ports:
                    new_connections.append(conn)
            if 'local_port' in conn:
                huddle_ports.add(conn['local_port'])
        
        if new_connections:
            print(f"\n  📍 NEW UDP connections during huddle:")
            for conn in new_connections[:10]:  # Show first 10
                port = conn.get('remote_port', conn.get('local_port', 'unknown'))
                host = conn.get('remote_host', 'local')
                print(f"    • Port {port} to {host}")
        
        # TCP Analysis
        baseline_tcp = self.baseline_connections.get('TCP', [])
        huddle_tcp = self.huddle_connections.get('TCP', [])
        
        print(f"\n🔷 TCP CONNECTIONS:")
        print(f"  Baseline: {len(baseline_tcp)} connections")
        print(f"  Huddle: {len(huddle_tcp)} connections")
        print(f"  Difference: {len(huddle_tcp) - len(baseline_tcp):+d}")
        
        # Port range analysis
        print(f"\n🔷 PORT ANALYSIS:")
        
        def analyze_ports(connections, label):
            port_ranges = defaultdict(int)
            for conn in connections:
                if 'remote_port' in conn:
                    try:
                        port = int(conn['remote_port'])
                        if port == 443:
                            port_ranges['HTTPS'] += 1
                        elif port == 80:
                            port_ranges['HTTP'] += 1
                        elif 3478 <= port <= 3479:
                            port_ranges['STUN/TURN'] += 1
                        elif 19302 <= port <= 19309:
                            port_ranges['Google STUN'] += 1
                        elif 5000 <= port <= 5100:
                            port_ranges['Media (5000-5100)'] += 1
                        elif 8801 <= port <= 8810:
                            port_ranges['Slack Voice (8801-8810)'] += 1
                        elif 10000 <= port <= 20000:
                            port_ranges['Dynamic (10K-20K)'] += 1
                        elif 20000 <= port <= 30000:
                            port_ranges['Dynamic (20K-30K)'] += 1
                        elif 30000 <= port <= 40000:
                            port_ranges['Dynamic (30K-40K)'] += 1
                        elif 40000 <= port <= 50000:
                            port_ranges['Dynamic (40K-50K)'] += 1
                        elif 50000 <= port <= 60000:
                            port_ranges['Dynamic (50K-60K)'] += 1
                        elif port > 60000:
                            port_ranges['High (>60K)'] += 1
                    except:
                        pass
            
            print(f"\n  {label}:")
            for range_name, count in sorted(port_ranges.items(), key=lambda x: x[1], reverse=True):
                if count > 0:
                    print(f"    {range_name}: {count}")
        
        analyze_ports(baseline_udp, "Baseline UDP Ports")
        analyze_ports(huddle_udp, "Huddle UDP Ports")
        
        # Look for patterns
        print(f"\n🎯 POTENTIAL HUDDLE INDICATORS:")
        indicators = []
        
        # Check for new high-numbered ports
        huddle_high_ports = set()
        for conn in huddle_udp:
            if 'remote_port' in conn:
                try:
                    port = int(conn['remote_port'])
                    if port > 30000:
                        huddle_high_ports.add(port)
                except:
                    pass
        
        baseline_high_ports = set()
        for conn in baseline_udp:
            if 'remote_port' in conn:
                try:
                    port = int(conn['remote_port'])
                    if port > 30000:
                        baseline_high_ports.add(port)
                except:
                    pass
        
        new_high_ports = huddle_high_ports - baseline_high_ports
        if new_high_ports:
            indicators.append(f"New high UDP ports (>30000): {sorted(new_high_ports)[:5]}")
        
        # Check for specific port ranges
        for conn in huddle_udp:
            if 'remote_port' in conn:
                port = conn['remote_port']
                if port in ['3478', '3479']:
                    indicators.append(f"STUN/TURN port detected: {port}")
                elif port.startswith('1930'):
                    indicators.append(f"Google STUN port detected: {port}")
                elif port.startswith('88'):
                    indicators.append(f"Possible Slack voice port: {port}")
        
        if indicators:
            for indicator in indicators:
                print(f"  • {indicator}")
        else:
            print("  • No clear indicators found - might need different detection approach")
        
        print("="*80)
    
    def run(self):
        """Interactive capture mode"""
        print("🎬 Slack Network Connection Capture Tool")
        print("="*80)
        print("This tool will capture network connections to find huddle patterns")
        print("\nInstructions:")
        print("1. Press ENTER to capture baseline (when NOT in huddle)")
        print("2. Start a huddle")
        print("3. Press ENTER to capture huddle state")
        print("4. Analysis will show the differences")
        print("="*80)
        
        # Check sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("\n🔐 Requesting sudo access...")
            subprocess.run("sudo true", shell=True)
        
        # Capture baseline
        input("\n📸 Press ENTER to capture BASELINE (make sure you're NOT in a huddle)...")
        print("Capturing baseline connections...")
        self.baseline_connections = self.get_all_connections()
        baseline_total = sum(len(v) if isinstance(v, list) else 0 for v in self.baseline_connections.values())
        print(f"✅ Captured {baseline_total} baseline connections")
        
        # Capture huddle
        input("\n📸 Now START A HUDDLE and press ENTER to capture huddle state...")
        print("Capturing huddle connections...")
        self.huddle_connections = self.get_all_connections()
        huddle_total = sum(len(v) if isinstance(v, list) else 0 for v in self.huddle_connections.values())
        print(f"✅ Captured {huddle_total} huddle connections")
        
        # Analyze
        self.analyze_differences()
        
        # Save for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"network_capture_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump({
                'baseline': [str(c) for c in self.baseline_connections.get('UDP', [])],
                'huddle': [str(c) for c in self.huddle_connections.get('UDP', [])]
            }, f, indent=2)
        print(f"\n💾 Saved capture data to {filename}")

if __name__ == "__main__":
    capture = NetworkCapture()
    capture.run()