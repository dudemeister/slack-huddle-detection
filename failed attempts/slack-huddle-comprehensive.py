#!/usr/bin/env python3

import subprocess
import time
import sys
import threading
import select
from datetime import datetime
from collections import defaultdict, deque

class ComprehensiveSlackMonitor:
    def __init__(self):
        self.manual_huddle_state = False
        self.baseline_data = []
        self.huddle_data = []
        
    def get_all_slack_pids(self):
        """Get all Slack-related process IDs with names"""
        try:
            # Use ps to get all Slack processes with more detail
            result = subprocess.run(
                "ps aux | grep -i slack | grep -v grep | grep -v slack-huddle",
                shell=True,
                capture_output=True,
                text=True
            )
            
            processes = {}
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split()
                    if len(parts) > 10:
                        pid = parts[1]
                        cpu = parts[2]
                        mem = parts[3]
                        # Extract process name from command
                        cmd = ' '.join(parts[10:])
                        if 'Slack Helper (Renderer)' in cmd:
                            name = 'Slack Helper (Renderer)'
                        elif 'Slack Helper (GPU)' in cmd:
                            name = 'Slack Helper (GPU)'
                        elif 'Slack Helper (Plugin)' in cmd:
                            name = 'Slack Helper (Plugin)'
                        elif 'Slack Helper' in cmd:
                            name = 'Slack Helper'
                        elif 'Slack' in cmd:
                            name = 'Slack'
                        else:
                            name = 'Slack Process'
                        
                        processes[pid] = {
                            'name': name,
                            'cpu': float(cpu),
                            'mem': float(mem),
                            'cmd': cmd[:100]
                        }
            
            return processes
        except Exception as e:
            print(f"Error getting processes: {e}")
            return {}
    
    def check_network_connections(self, pid):
        """Check all network connections for a PID using netstat"""
        try:
            # Try netstat first (doesn't require special permissions)
            result = subprocess.run(
                f"netstat -anv | grep {pid}",
                shell=True,
                capture_output=True,
                text=True
            )
            
            udp_count = result.stdout.count('udp')
            tcp_count = result.stdout.count('tcp')
            
            # Extract some connection details
            connections = []
            for line in result.stdout.strip().split('\n'):
                if 'udp' in line.lower():
                    connections.append(line[:100])
            
            return {
                'udp': udp_count,
                'tcp': tcp_count,
                'samples': connections[:3]
            }
        except:
            return {'udp': 0, 'tcp': 0, 'samples': []}
    
    def check_lsof_connections(self, pid):
        """Try lsof with sudo if available"""
        try:
            # First try without sudo
            result = subprocess.run(
                f"lsof -p {pid} -i 2>/dev/null | grep -E '(UDP|TCP)'",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if not result.stdout:
                # Try with sudo (will prompt for password once)
                result = subprocess.run(
                    f"sudo lsof -p {pid} -i 2>/dev/null | grep -E '(UDP|TCP)'",
                    shell=True,
                    capture_output=True,
                    text=True
                )
            
            udp_count = result.stdout.count('UDP')
            tcp_count = result.stdout.count('TCP')
            
            # Look for specific ports
            stun_turn = 0
            webrtc_ports = 0
            for line in result.stdout.split('\n'):
                if any(port in line for port in ['3478', '3479', '19302', '19303', '19304', '19305']):
                    stun_turn += 1
                if 'UDP' in line and any(p in line for p in [':4', ':5', ':6', ':7', ':8', ':9']):
                    webrtc_ports += 1
            
            return {
                'udp': udp_count,
                'tcp': tcp_count,
                'stun_turn': stun_turn,
                'webrtc_likely': webrtc_ports
            }
        except:
            return {'udp': 0, 'tcp': 0, 'stun_turn': 0, 'webrtc_likely': 0}
    
    def check_audio_activity(self, pid):
        """Check for audio device usage"""
        try:
            # Check if process has audio devices open
            result = subprocess.run(
                f"lsof -p {pid} 2>/dev/null | grep -iE '(coreaudio|audiodevice|sound|speaker|microphone)'",
                shell=True,
                capture_output=True,
                text=True
            )
            
            has_audio = bool(result.stdout.strip())
            
            # Also check system audio
            audio_check = subprocess.run(
                "system_profiler SPAudioDataType | grep -i 'input source'",
                shell=True,
                capture_output=True,
                text=True
            )
            
            system_audio_active = 'Input Source:' in audio_check.stdout
            
            return has_audio, system_audio_active
        except:
            return False, False
    
    def check_cpu_changes(self, processes):
        """Analyze CPU usage patterns"""
        high_cpu_processes = []
        for pid, info in processes.items():
            if info['cpu'] > 5.0:  # More than 5% CPU
                high_cpu_processes.append(f"{info['name']} ({info['cpu']}%)")
        return high_cpu_processes
    
    def collect_comprehensive_data(self):
        """Collect all available data"""
        processes = self.get_all_slack_pids()
        
        data = {
            'timestamp': datetime.now(),
            'process_count': len(processes),
            'total_udp': 0,
            'total_tcp': 0,
            'has_audio': False,
            'high_cpu': [],
            'process_details': {}
        }
        
        for pid, info in processes.items():
            # Try multiple detection methods
            netstat_data = self.check_network_connections(pid)
            lsof_data = self.check_lsof_connections(pid)
            audio, system_audio = self.check_audio_activity(pid)
            
            # Use the maximum values from different methods
            udp = max(netstat_data['udp'], lsof_data['udp'])
            tcp = max(netstat_data['tcp'], lsof_data['tcp'])
            
            data['process_details'][pid] = {
                'name': info['name'],
                'cpu': info['cpu'],
                'mem': info['mem'],
                'udp': udp,
                'tcp': tcp,
                'audio': audio,
                'stun_turn': lsof_data.get('stun_turn', 0),
                'webrtc_likely': lsof_data.get('webrtc_likely', 0)
            }
            
            data['total_udp'] += udp
            data['total_tcp'] += tcp
            data['has_audio'] = data['has_audio'] or audio
            
            if info['cpu'] > 5.0:
                data['high_cpu'].append(f"{info['name']} ({info['cpu']}%)")
        
        return data
    
    def stdin_listener(self):
        """Listen for stdin commands"""
        print("\n💡 Commands: 'h' = huddle start, 'n' = normal/no huddle, 's' = stats, 'q' = quit\n")
        
        while True:
            try:
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline().strip().lower()
                    
                    if line == 'h':
                        self.manual_huddle_state = True
                        print(f"\n✅ HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                        print("Recording huddle patterns...\n")
                    elif line == 'n':
                        self.manual_huddle_state = False
                        print(f"\n✅ HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                        print("Recording baseline patterns...\n")
                    elif line == 's':
                        self.print_analysis()
                    elif line == 'q':
                        return
            except:
                pass
            time.sleep(0.1)
    
    def print_analysis(self):
        """Print detailed analysis"""
        print("\n" + "="*80)
        print("📊 HUDDLE DETECTION ANALYSIS")
        print("="*80)
        
        if self.baseline_data:
            print("\n🔵 BASELINE (No Huddle) - {} samples".format(len(self.baseline_data)))
            avg_udp = sum(d['total_udp'] for d in self.baseline_data) / len(self.baseline_data)
            avg_tcp = sum(d['total_tcp'] for d in self.baseline_data) / len(self.baseline_data)
            audio_pct = sum(1 for d in self.baseline_data if d['has_audio']) * 100 / len(self.baseline_data)
            
            print(f"  Average UDP: {avg_udp:.1f}")
            print(f"  Average TCP: {avg_tcp:.1f}")
            print(f"  Audio Active: {audio_pct:.1f}%")
            
            # Process-specific baseline
            process_stats = defaultdict(lambda: {'cpu': [], 'udp': [], 'tcp': []})
            for data in self.baseline_data:
                for pid, details in data['process_details'].items():
                    process_stats[details['name']]['cpu'].append(details['cpu'])
                    process_stats[details['name']]['udp'].append(details['udp'])
                    process_stats[details['name']]['tcp'].append(details['tcp'])
            
            print("\n  Per-Process Baseline:")
            for name, stats in process_stats.items():
                if stats['cpu']:
                    avg_cpu = sum(stats['cpu']) / len(stats['cpu'])
                    avg_udp = sum(stats['udp']) / len(stats['udp'])
                    print(f"    {name}: CPU={avg_cpu:.1f}%, UDP={avg_udp:.1f}")
        
        if self.huddle_data:
            print("\n🟢 HUDDLE - {} samples".format(len(self.huddle_data)))
            avg_udp = sum(d['total_udp'] for d in self.huddle_data) / len(self.huddle_data)
            avg_tcp = sum(d['total_tcp'] for d in self.huddle_data) / len(self.huddle_data)
            audio_pct = sum(1 for d in self.huddle_data if d['has_audio']) * 100 / len(self.huddle_data)
            
            print(f"  Average UDP: {avg_udp:.1f}")
            print(f"  Average TCP: {avg_tcp:.1f}")
            print(f"  Audio Active: {audio_pct:.1f}%")
            
            # Process-specific huddle
            process_stats = defaultdict(lambda: {'cpu': [], 'udp': [], 'tcp': []})
            for data in self.huddle_data:
                for pid, details in data['process_details'].items():
                    process_stats[details['name']]['cpu'].append(details['cpu'])
                    process_stats[details['name']]['udp'].append(details['udp'])
                    process_stats[details['name']]['tcp'].append(details['tcp'])
            
            print("\n  Per-Process Huddle:")
            for name, stats in process_stats.items():
                if stats['cpu']:
                    avg_cpu = sum(stats['cpu']) / len(stats['cpu'])
                    avg_udp = sum(stats['udp']) / len(stats['udp'])
                    print(f"    {name}: CPU={avg_cpu:.1f}%, UDP={avg_udp:.1f}")
        
        if self.baseline_data and self.huddle_data:
            print("\n🎯 KEY DIFFERENCES:")
            # Calculate differences
            baseline_cpu = defaultdict(list)
            huddle_cpu = defaultdict(list)
            
            for data in self.baseline_data:
                for pid, details in data['process_details'].items():
                    baseline_cpu[details['name']].append(details['cpu'])
            
            for data in self.huddle_data:
                for pid, details in data['process_details'].items():
                    huddle_cpu[details['name']].append(details['cpu'])
            
            for name in set(baseline_cpu.keys()) | set(huddle_cpu.keys()):
                if baseline_cpu[name] and huddle_cpu[name]:
                    baseline_avg = sum(baseline_cpu[name]) / len(baseline_cpu[name])
                    huddle_avg = sum(huddle_cpu[name]) / len(huddle_cpu[name])
                    diff = huddle_avg - baseline_avg
                    if abs(diff) > 2.0:  # Significant CPU change
                        print(f"  {name}: CPU change of {diff:+.1f}%")
        
        print("="*80 + "\n")
    
    def run(self):
        """Main monitoring loop"""
        print("🔬 Comprehensive Slack Huddle Monitor")
        print("="*80)
        print("Using multiple detection methods: ps, netstat, lsof")
        print("NOTE: You may be prompted for sudo password for better network visibility")
        
        # Start stdin listener
        stdin_thread = threading.Thread(target=self.stdin_listener, daemon=True)
        stdin_thread.start()
        
        last_detail = 0
        detail_interval = 20
        
        while True:
            try:
                data = self.collect_comprehensive_data()
                
                # Store data based on state
                if self.manual_huddle_state:
                    self.huddle_data.append(data)
                    state = "🟢 HUDDLE"
                else:
                    self.baseline_data.append(data)
                    state = "⚪ BASELINE"
                
                # Status line
                audio = "🎧" if data['has_audio'] else "🔇"
                high_cpu = f"CPU: {', '.join(data['high_cpu'][:1])}" if data['high_cpu'] else "CPU: normal"
                
                print(f"\r{state} | UDP: {data['total_udp']:3d} | TCP: {data['total_tcp']:3d} | "
                      f"{audio} | {data['process_count']} procs | {high_cpu[:30]} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", end="", flush=True)
                
                # Detailed output
                if time.time() - last_detail > detail_interval:
                    print("\n\n" + "-"*80)
                    print(f"DETAILED VIEW - {datetime.now().strftime('%H:%M:%S')}")
                    print("-"*80)
                    
                    for pid, details in data['process_details'].items():
                        if details['cpu'] > 1.0 or details['udp'] > 0 or details['audio']:
                            print(f"\n📱 {details['name']} (PID: {pid})")
                            print(f"   CPU: {details['cpu']:.1f}%  MEM: {details['mem']:.1f}%")
                            print(f"   Network: UDP={details['udp']} TCP={details['tcp']}")
                            if details.get('stun_turn'):
                                print(f"   STUN/TURN connections: {details['stun_turn']}")
                            if details.get('webrtc_likely'):
                                print(f"   Likely WebRTC ports: {details['webrtc_likely']}")
                            if details['audio']:
                                print(f"   🎧 Audio device active")
                    
                    print("-"*80 + "\n")
                    last_detail = time.time()
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(3)
        
        print("\n\nFinal Analysis:")
        self.print_analysis()
        print("👋 Monitoring stopped")

if __name__ == "__main__":
    monitor = ComprehensiveSlackMonitor()
    monitor.run()