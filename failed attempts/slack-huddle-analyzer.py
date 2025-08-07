#!/usr/bin/env python3

import subprocess
import time
import sys
import json
import threading
import select
from collections import defaultdict, deque
from datetime import datetime

class SlackHuddleAnalyzer:
    def __init__(self):
        self.manual_huddle_state = False
        self.connection_history = defaultdict(lambda: deque(maxlen=20))
        self.baseline_data = {}
        self.huddle_data = {}
        self.collecting_baseline = True
        self.stdin_thread = None
        
    def get_all_slack_pids(self):
        """Get all Slack-related process IDs"""
        try:
            result = subprocess.run(['pgrep', '-f', 'Slack'], capture_output=True, text=True)
            pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
            
            # Get process names for each PID
            pid_info = {}
            for pid in pids:
                try:
                    name_result = subprocess.run(['ps', '-p', pid, '-o', 'comm='], 
                                               capture_output=True, text=True)
                    name = name_result.stdout.strip()
                    pid_info[pid] = name
                except:
                    pid_info[pid] = "Unknown"
            
            return pid_info
        except:
            return {}
    
    def get_udp_connections_for_pid(self, pid):
        """Get UDP connections for a specific PID"""
        try:
            result = subprocess.run(
                f'lsof -p {pid} -iUDP -P 2>/dev/null', 
                shell=True, 
                capture_output=True, 
                text=True
            )
            
            connections = []
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            
            for line in lines:
                if 'UDP' in line:
                    parts = line.split()
                    if len(parts) >= 9:
                        conn_str = parts[8] if len(parts) > 8 else ''
                        
                        # Parse connection
                        local_addr = ""
                        remote_addr = ""
                        local_port = 0
                        remote_port = 0
                        
                        if '->' in conn_str:
                            local, remote = conn_str.split('->')
                            local_addr = local.strip()
                            remote_addr = remote.strip()
                            
                            # Extract ports
                            if ':' in local_addr:
                                local_port = int(local_addr.split(':')[-1])
                            if ':' in remote_addr:
                                remote_port = int(remote_addr.split(':')[-1])
                        else:
                            local_addr = conn_str
                            if ':' in local_addr:
                                local_port = int(local_addr.split(':')[-1])
                        
                        connections.append({
                            'local': local_addr,
                            'remote': remote_addr,
                            'local_port': local_port,
                            'remote_port': remote_port,
                            'raw': conn_str
                        })
            
            return connections
        except Exception as e:
            return []
    
    def check_audio_for_pid(self, pid):
        """Check if a PID has audio devices open"""
        try:
            result = subprocess.run(
                f'lsof -p {pid} 2>/dev/null | grep -E "(coreaudio|AudioDevice|IOAudio)"', 
                shell=True, 
                capture_output=True, 
                text=True
            )
            return bool(result.stdout.strip())
        except:
            return False
    
    def analyze_connections(self, connections):
        """Analyze connection patterns"""
        analysis = {
            'total': len(connections),
            'stun_turn': 0,
            'google_stun': 0,
            'high_ports': 0,
            'unique_remotes': set(),
            'port_distribution': defaultdict(int)
        }
        
        for conn in connections:
            remote_port = conn['remote_port']
            local_port = conn['local_port']
            
            if conn['remote']:
                analysis['unique_remotes'].add(conn['remote'].split(':')[0] if ':' in conn['remote'] else conn['remote'])
            
            # Categorize ports
            if 3478 <= remote_port <= 3479:
                analysis['stun_turn'] += 1
            elif 19302 <= remote_port <= 19309:
                analysis['google_stun'] += 1
            elif remote_port > 10000:
                analysis['high_ports'] += 1
            
            if remote_port > 0:
                if remote_port < 1024:
                    analysis['port_distribution']['system'] += 1
                elif remote_port < 5000:
                    analysis['port_distribution']['low'] += 1
                elif remote_port < 32768:
                    analysis['port_distribution']['mid'] += 1
                else:
                    analysis['port_distribution']['high'] += 1
        
        return analysis
    
    def collect_all_data(self):
        """Collect data from all Slack processes"""
        pids = self.get_all_slack_pids()
        data = {
            'timestamp': time.time(),
            'processes': {},
            'total_udp': 0,
            'total_audio': False,
            'analysis': {}
        }
        
        for pid, name in pids.items():
            connections = self.get_udp_connections_for_pid(pid)
            has_audio = self.check_audio_for_pid(pid)
            analysis = self.analyze_connections(connections)
            
            data['processes'][pid] = {
                'name': name,
                'udp_count': len(connections),
                'has_audio': has_audio,
                'analysis': analysis,
                'connections': connections[:5]  # Store sample
            }
            
            data['total_udp'] += len(connections)
            data['total_audio'] = data['total_audio'] or has_audio
        
        # Combined analysis
        all_connections = []
        for proc_data in data['processes'].values():
            all_connections.extend(proc_data.get('connections', []))
        
        data['analysis'] = self.analyze_connections(all_connections)
        
        return data
    
    def record_baseline(self, data):
        """Record baseline data when not in huddle"""
        key = 'baseline'
        if key not in self.baseline_data:
            self.baseline_data[key] = []
        
        self.baseline_data[key].append({
            'total_udp': data['total_udp'],
            'audio': data['total_audio'],
            'stun_turn': data['analysis']['stun_turn'],
            'google_stun': data['analysis']['google_stun'],
            'unique_remotes': len(data['analysis']['unique_remotes']),
            'process_count': len(data['processes'])
        })
    
    def record_huddle(self, data):
        """Record huddle data when in huddle"""
        key = 'huddle'
        if key not in self.huddle_data:
            self.huddle_data[key] = []
        
        self.huddle_data[key].append({
            'total_udp': data['total_udp'],
            'audio': data['total_audio'],
            'stun_turn': data['analysis']['stun_turn'],
            'google_stun': data['analysis']['google_stun'],
            'unique_remotes': len(data['analysis']['unique_remotes']),
            'process_count': len(data['processes'])
        })
    
    def get_stats(self, data_dict):
        """Calculate statistics from collected data"""
        if not data_dict or 'baseline' not in data_dict:
            return None
        
        samples = data_dict.get('baseline', []) or data_dict.get('huddle', [])
        if not samples:
            return None
        
        stats = {
            'avg_udp': sum(s['total_udp'] for s in samples) / len(samples),
            'max_udp': max(s['total_udp'] for s in samples),
            'min_udp': min(s['total_udp'] for s in samples),
            'audio_percent': sum(1 for s in samples if s['audio']) * 100 / len(samples),
            'avg_stun': sum(s['stun_turn'] for s in samples) / len(samples),
            'samples': len(samples)
        }
        
        return stats
    
    def stdin_listener(self):
        """Listen for stdin commands in background"""
        print("\n💡 Commands: Type 'h' when huddle starts, 'n' when huddle ends, 's' for stats\n")
        
        while True:
            try:
                # Check if input is available
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline().strip().lower()
                    
                    if line == 'h':
                        self.manual_huddle_state = True
                        print(f"\n✅ HUDDLE MARKED AS STARTED - {datetime.now().strftime('%H:%M:%S')}")
                        print("Collecting huddle data...\n")
                    elif line == 'n':
                        self.manual_huddle_state = False
                        print(f"\n✅ HUDDLE MARKED AS ENDED - {datetime.now().strftime('%H:%M:%S')}")
                        print("Collecting baseline data...\n")
                    elif line == 's':
                        self.print_statistics()
                    elif line == 'q':
                        break
            except:
                pass
            time.sleep(0.1)
    
    def print_statistics(self):
        """Print comparison statistics"""
        print("\n" + "="*70)
        print("📊 COLLECTED STATISTICS")
        print("="*70)
        
        baseline_stats = self.get_stats(self.baseline_data)
        huddle_stats = self.get_stats(self.huddle_data)
        
        if baseline_stats:
            print("\n🔵 BASELINE (No Huddle):")
            print(f"  Samples: {baseline_stats['samples']}")
            print(f"  UDP Connections: {baseline_stats['avg_udp']:.1f} avg "
                  f"({baseline_stats['min_udp']}-{baseline_stats['max_udp']} range)")
            print(f"  Audio Active: {baseline_stats['audio_percent']:.1f}%")
            print(f"  STUN/TURN: {baseline_stats['avg_stun']:.1f} avg")
        
        if huddle_stats:
            print("\n🟢 HUDDLE:")
            print(f"  Samples: {huddle_stats['samples']}")
            print(f"  UDP Connections: {huddle_stats['avg_udp']:.1f} avg "
                  f"({huddle_stats['min_udp']}-{huddle_stats['max_udp']} range)")
            print(f"  Audio Active: {huddle_stats['audio_percent']:.1f}%")
            print(f"  STUN/TURN: {huddle_stats['avg_stun']:.1f} avg")
        
        if baseline_stats and huddle_stats:
            print("\n🎯 DIFFERENCES:")
            print(f"  UDP Change: {huddle_stats['avg_udp'] - baseline_stats['avg_udp']:+.1f}")
            print(f"  Audio Change: {huddle_stats['audio_percent'] - baseline_stats['audio_percent']:+.1f}%")
            print(f"  STUN/TURN Change: {huddle_stats['avg_stun'] - baseline_stats['avg_stun']:+.1f}")
        
        print("="*70 + "\n")
    
    def run(self):
        """Main loop"""
        print("🔬 Slack Huddle Analyzer - Multi-Process Monitor")
        print("="*70)
        print("Monitoring ALL Slack processes for connection patterns")
        
        # Start stdin listener in background
        self.stdin_thread = threading.Thread(target=self.stdin_listener, daemon=True)
        self.stdin_thread.start()
        
        last_detailed = 0
        detail_interval = 15  # Detailed output every 15 seconds
        
        while True:
            try:
                data = self.collect_all_data()
                
                # Record data based on manual state
                if self.manual_huddle_state:
                    self.record_huddle(data)
                    state_indicator = "🟢 HUDDLE"
                else:
                    self.record_baseline(data)
                    state_indicator = "⚪ BASELINE"
                
                # Status line
                process_summary = f"{len(data['processes'])} procs"
                audio_indicator = "🎧" if data['total_audio'] else "🔇"
                
                print(f"\r{state_indicator} | UDP: {data['total_udp']:3d} | "
                      f"STUN: {data['analysis']['stun_turn']} | "
                      f"{audio_indicator} | {process_summary} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", end="", flush=True)
                
                # Detailed output periodically
                if time.time() - last_detailed > detail_interval:
                    print("\n\n" + "-"*70)
                    print(f"PROCESS DETAILS - {datetime.now().strftime('%H:%M:%S')}")
                    print("-"*70)
                    
                    for pid, proc_data in data['processes'].items():
                        if proc_data['udp_count'] > 0 or proc_data['has_audio']:
                            print(f"\n📱 {proc_data['name']} (PID: {pid}):")
                            print(f"   UDP Connections: {proc_data['udp_count']}")
                            print(f"   Audio: {'Yes' if proc_data['has_audio'] else 'No'}")
                            print(f"   STUN/TURN: {proc_data['analysis']['stun_turn']}")
                            print(f"   Unique Remotes: {len(proc_data['analysis']['unique_remotes'])}")
                            
                            if proc_data['connections']:
                                print(f"   Sample connections:")
                                for conn in proc_data['connections'][:3]:
                                    if conn['remote']:
                                        print(f"     → {conn['remote']}")
                    
                    print("-"*70 + "\n")
                    last_detailed = time.time()
                
                time.sleep(2)  # Check every 2 seconds
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(2)
        
        print("\n\n📈 Final Statistics:")
        self.print_statistics()
        print("👋 Analysis complete")

if __name__ == "__main__":
    analyzer = SlackHuddleAnalyzer()
    analyzer.run()