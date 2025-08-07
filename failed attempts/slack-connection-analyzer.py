#!/usr/bin/env python3

import subprocess
import time
import sys
import json
from datetime import datetime
from collections import defaultdict, Counter

class DetailedConnectionAnalyzer:
    def __init__(self):
        self.baseline_data = None
        self.huddle_data = None
        
    def get_detailed_connections(self):
        """Get very detailed connection information"""
        data = {
            'connections': [],
            'by_process': defaultdict(list),
            'by_port': defaultdict(list),
            'by_host': defaultdict(int),
            'raw_output': []
        }
        
        try:
            # Get all Slack PIDs with process names
            ps_cmd = "ps aux | grep -E 'Slack' | grep -v grep | grep -v slack-"
            ps_result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True)
            
            pid_to_name = {}
            for line in ps_result.stdout.strip().split('\n'):
                if line:
                    parts = line.split(None, 10)
                    if len(parts) > 10:
                        pid = parts[1]
                        cmd = parts[10]
                        if 'Renderer' in cmd:
                            pid_to_name[pid] = 'Renderer'
                        elif 'GPU' in cmd:
                            pid_to_name[pid] = 'GPU'
                        elif 'Plugin' in cmd:
                            pid_to_name[pid] = 'Plugin'
                        elif 'Slack Helper' in cmd:
                            pid_to_name[pid] = 'Helper'
                        elif 'Slack' in cmd:
                            pid_to_name[pid] = 'Main'
            
            # Get connections for each PID
            for pid, process_name in pid_to_name.items():
                # Use lsof with very detailed output
                lsof_cmd = f"sudo lsof -p {pid} -i -n -P 2>/dev/null"
                lsof_result = subprocess.run(lsof_cmd, shell=True, capture_output=True, text=True)
                
                for line in lsof_result.stdout.strip().split('\n')[1:]:
                    if line:
                        data['raw_output'].append(line)
                        parts = line.split()
                        
                        if len(parts) >= 9 and ('TCP' in parts[7] or 'UDP' in parts[7]):
                            protocol = 'TCP' if 'TCP' in parts[7] else 'UDP'
                            state = parts[9] if len(parts) > 9 else ''
                            connection_str = parts[8]
                            
                            conn = {
                                'pid': pid,
                                'process': process_name,
                                'protocol': protocol,
                                'connection': connection_str,
                                'state': state
                            }
                            
                            # Parse connection details
                            if '->' in connection_str:
                                local, remote = connection_str.split('->')
                                conn['local'] = local
                                conn['remote'] = remote
                                
                                # Extract remote host and port
                                if ':' in remote:
                                    parts = remote.rsplit(':', 1)
                                    conn['remote_host'] = parts[0]
                                    conn['remote_port'] = parts[1]
                                    
                                    # Track by host
                                    data['by_host'][parts[0]] += 1
                                    
                                    # Track by port
                                    data['by_port'][parts[1]].append({
                                        'process': process_name,
                                        'host': parts[0]
                                    })
                            else:
                                conn['local'] = connection_str
                                if ':' in connection_str:
                                    conn['local_port'] = connection_str.split(':')[-1]
                            
                            data['connections'].append(conn)
                            data['by_process'][process_name].append(conn)
            
            # Also get netstat for UDP specifically
            netstat_cmd = "sudo netstat -anup 2>/dev/null | grep -E '(Slack|UDP)'"
            netstat_result = subprocess.run(netstat_cmd, shell=True, capture_output=True, text=True)
            data['netstat_udp'] = len(netstat_result.stdout.strip().split('\n'))
            
        except Exception as e:
            print(f"Error: {e}")
        
        return data
    
    def analyze_differences(self):
        """Deep analysis of connection differences"""
        if not self.baseline_data or not self.huddle_data:
            return
        
        print("\n" + "="*80)
        print("🔬 DETAILED CONNECTION ANALYSIS")
        print("="*80)
        
        # 1. Process-level analysis
        print("\n📱 PER-PROCESS CHANGES:")
        for process_name in set(list(self.baseline_data['by_process'].keys()) + 
                               list(self.huddle_data['by_process'].keys())):
            baseline_conns = self.baseline_data['by_process'].get(process_name, [])
            huddle_conns = self.huddle_data['by_process'].get(process_name, [])
            
            baseline_udp = sum(1 for c in baseline_conns if c['protocol'] == 'UDP')
            huddle_udp = sum(1 for c in huddle_conns if c['protocol'] == 'UDP')
            baseline_tcp = sum(1 for c in baseline_conns if c['protocol'] == 'TCP')
            huddle_tcp = sum(1 for c in huddle_conns if c['protocol'] == 'TCP')
            
            udp_diff = huddle_udp - baseline_udp
            tcp_diff = huddle_tcp - baseline_tcp
            
            if abs(udp_diff) > 5 or abs(tcp_diff) > 5:
                print(f"\n  {process_name}:")
                print(f"    UDP: {baseline_udp} → {huddle_udp} ({udp_diff:+d})")
                print(f"    TCP: {baseline_tcp} → {huddle_tcp} ({tcp_diff:+d})")
        
        # 2. New remote hosts
        print("\n🌐 REMOTE HOST CHANGES:")
        baseline_hosts = set(self.baseline_data['by_host'].keys())
        huddle_hosts = set(self.huddle_data['by_host'].keys())
        new_hosts = huddle_hosts - baseline_hosts
        
        if new_hosts:
            print("  New hosts during huddle:")
            for host in sorted(new_hosts)[:10]:
                count = self.huddle_data['by_host'][host]
                print(f"    • {host} ({count} connections)")
        
        # Changed connection counts to existing hosts
        print("\n  Increased connections to existing hosts:")
        for host in baseline_hosts & huddle_hosts:
            baseline_count = self.baseline_data['by_host'][host]
            huddle_count = self.huddle_data['by_host'][host]
            diff = huddle_count - baseline_count
            if diff > 5:
                print(f"    • {host}: {baseline_count} → {huddle_count} ({diff:+d})")
        
        # 3. Port analysis
        print("\n🔌 PORT USAGE CHANGES:")
        baseline_ports = set(self.baseline_data['by_port'].keys())
        huddle_ports = set(self.huddle_data['by_port'].keys())
        new_ports = huddle_ports - baseline_ports
        
        if new_ports:
            print("  New ports during huddle:")
            for port in sorted(new_ports, key=lambda x: int(x) if x.isdigit() else 0)[:20]:
                connections = self.huddle_data['by_port'][port]
                processes = set(c['process'] for c in connections)
                print(f"    • Port {port}: {', '.join(processes)} ({len(connections)} conns)")
        
        # 4. Look for specific patterns
        print("\n🎯 PATTERN DETECTION:")
        
        # Check for UDP on port 443 increase (QUIC)
        baseline_quic = sum(1 for c in self.baseline_data['connections'] 
                           if c['protocol'] == 'UDP' and c.get('remote_port') == '443')
        huddle_quic = sum(1 for c in self.huddle_data['connections'] 
                         if c['protocol'] == 'UDP' and c.get('remote_port') == '443')
        
        if huddle_quic > baseline_quic:
            print(f"  • QUIC/HTTP3 increase: {baseline_quic} → {huddle_quic} ({huddle_quic-baseline_quic:+d})")
        
        # Check for established TCP connections
        baseline_established = sum(1 for c in self.baseline_data['connections'] 
                                 if c.get('state') == 'ESTABLISHED')
        huddle_established = sum(1 for c in self.huddle_data['connections'] 
                               if c.get('state') == 'ESTABLISHED')
        
        if huddle_established > baseline_established:
            print(f"  • TCP ESTABLISHED: {baseline_established} → {huddle_established} ({huddle_established-baseline_established:+d})")
        
        # Look for media-related ports
        media_ports = []
        for port, conns in self.huddle_data['by_port'].items():
            try:
                port_num = int(port)
                if 4000 <= port_num <= 9000 or 30000 <= port_num <= 65000:
                    if port not in self.baseline_data['by_port']:
                        media_ports.append((port, len(conns)))
            except:
                pass
        
        if media_ports:
            print(f"  • Potential media ports (4000-9000, 30000-65000):")
            for port, count in sorted(media_ports)[:10]:
                print(f"      Port {port}: {count} connections")
        
        # 5. Connection string patterns
        print("\n📝 CONNECTION STRING ANALYSIS:")
        
        # Look for unique connection patterns in huddle
        huddle_patterns = Counter()
        for conn in self.huddle_data['connections']:
            if 'remote' in conn:
                # Extract domain/IP pattern
                remote = conn['remote']
                if ':' in remote:
                    host = remote.rsplit(':', 1)[0]
                    # Group by domain pattern
                    if '.slack.com' in host:
                        huddle_patterns['slack.com'] += 1
                    elif '.amazonaws.com' in host:
                        huddle_patterns['amazonaws.com'] += 1
                    elif '.cloudfront' in host:
                        huddle_patterns['cloudfront'] += 1
                    elif host.startswith('[') or ':' in host:
                        huddle_patterns['IPv6'] += 1
                    elif host.replace('.', '').isdigit():
                        huddle_patterns['IPv4'] += 1
        
        baseline_patterns = Counter()
        for conn in self.baseline_data['connections']:
            if 'remote' in conn:
                remote = conn['remote']
                if ':' in remote:
                    host = remote.rsplit(':', 1)[0]
                    if '.slack.com' in host:
                        baseline_patterns['slack.com'] += 1
                    elif '.amazonaws.com' in host:
                        baseline_patterns['amazonaws.com'] += 1
                    elif '.cloudfront' in host:
                        baseline_patterns['cloudfront'] += 1
                    elif host.startswith('[') or ':' in host:
                        baseline_patterns['IPv6'] += 1
                    elif host.replace('.', '').isdigit():
                        baseline_patterns['IPv4'] += 1
        
        print("  Connection patterns (baseline → huddle):")
        for pattern in set(list(huddle_patterns.keys()) + list(baseline_patterns.keys())):
            baseline_count = baseline_patterns.get(pattern, 0)
            huddle_count = huddle_patterns.get(pattern, 0)
            diff = huddle_count - baseline_count
            if abs(diff) > 5:
                print(f"    • {pattern}: {baseline_count} → {huddle_count} ({diff:+d})")
        
        print("="*80)
        
        # Save detailed data
        self.save_detailed_data()
    
    def save_detailed_data(self):
        """Save detailed connection data for manual analysis"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"detailed_connections_{timestamp}.json"
        
        # Prepare serializable data
        save_data = {
            'baseline': {
                'total_connections': len(self.baseline_data['connections']),
                'by_process': {k: len(v) for k, v in self.baseline_data['by_process'].items()},
                'top_ports': dict(Counter(self.baseline_data['by_port'].keys()).most_common(20)),
                'top_hosts': dict(Counter(self.baseline_data['by_host']).most_common(20))
            },
            'huddle': {
                'total_connections': len(self.huddle_data['connections']),
                'by_process': {k: len(v) for k, v in self.huddle_data['by_process'].items()},
                'top_ports': dict(Counter(self.huddle_data['by_port'].keys()).most_common(20)),
                'top_hosts': dict(Counter(self.huddle_data['by_host']).most_common(20))
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(save_data, f, indent=2)
        
        print(f"\n💾 Saved detailed analysis to {filename}")
    
    def run(self):
        """Run the detailed analysis"""
        print("🔬 Slack Connection Deep Analyzer")
        print("="*80)
        print("This will perform deep analysis of connection patterns")
        
        # Check sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("\n🔐 Requesting sudo access...")
            subprocess.run("sudo true", shell=True)
        
        # Capture baseline
        input("\n📸 Press ENTER to capture BASELINE (NOT in huddle)...")
        print("Capturing baseline (this may take a few seconds)...")
        self.baseline_data = self.get_detailed_connections()
        print(f"✅ Captured {len(self.baseline_data['connections'])} baseline connections")
        
        # Capture huddle
        input("\n📸 START A HUDDLE and press ENTER...")
        print("Capturing huddle connections...")
        self.huddle_data = self.get_detailed_connections()
        print(f"✅ Captured {len(self.huddle_data['connections'])} huddle connections")
        
        # Analyze
        self.analyze_differences()

if __name__ == "__main__":
    analyzer = DetailedConnectionAnalyzer()
    analyzer.run()