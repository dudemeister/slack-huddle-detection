#!/usr/bin/env python3

import subprocess
import time
import sys
import threading
import select
from datetime import datetime
from collections import defaultdict, deque
import os

class SudoSlackMonitor:
    def __init__(self):
        self.manual_huddle_state = False
        self.baseline_data = []
        self.huddle_data = []
        self.sudo_available = self.check_sudo()
        
    def check_sudo(self):
        """Check if we can use sudo"""
        try:
            print("🔐 Checking sudo access...")
            result = subprocess.run(
                "sudo -n true 2>/dev/null",
                shell=True,
                capture_output=True
            )
            if result.returncode == 0:
                print("✅ Sudo access available without password")
                return True
            else:
                # Try to get sudo access
                print("📝 Requesting sudo access for network monitoring...")
                result = subprocess.run(
                    "sudo true",
                    shell=True
                )
                if result.returncode == 0:
                    print("✅ Sudo access granted")
                    return True
        except:
            pass
        print("⚠️  Running without sudo (limited network visibility)")
        return False
    
    def get_all_slack_pids(self):
        """Get all Slack-related process IDs with detailed info"""
        try:
            # Get all Slack processes with full details
            cmd = "ps aux | grep -E '(Slack|slack)' | grep -v grep | grep -v slack-huddle"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            processes = {}
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split(None, 10)  # Split on whitespace, max 11 parts
                    if len(parts) > 10:
                        pid = parts[1]
                        cpu = float(parts[2])
                        mem = float(parts[3])
                        vsz = parts[4]  # Virtual memory
                        rss = parts[5]  # Resident memory
                        cmd = parts[10]
                        
                        # Identify process type
                        if 'Slack Helper (Renderer)' in cmd:
                            name = 'Renderer'
                        elif 'Slack Helper (GPU)' in cmd:
                            name = 'GPU'
                        elif 'Slack Helper (Plugin)' in cmd:
                            name = 'Plugin'
                        elif 'Slack Helper' in cmd:
                            name = 'Helper'
                        elif 'Slack.app' in cmd:
                            name = 'Main'
                        else:
                            continue  # Skip non-Slack processes
                        
                        processes[pid] = {
                            'name': name,
                            'cpu': cpu,
                            'mem': mem,
                            'vsz': vsz,
                            'rss': rss
                        }
            
            return processes
        except Exception as e:
            print(f"Error getting processes: {e}")
            return {}
    
    def get_network_connections_sudo(self, pid):
        """Get detailed network connections using sudo lsof"""
        connections = {
            'udp': [],
            'tcp': [],
            'unix': 0,
            'total_udp': 0,
            'total_tcp': 0,
            'stun_turn': 0,
            'webrtc_ports': 0
        }
        
        try:
            # Get all network connections for the process
            cmd = f"{'sudo ' if self.sudo_available else ''}lsof -p {pid} -i -n -P 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                if not line:
                    continue
                    
                parts = line.split()
                if len(parts) < 9:
                    continue
                
                protocol = parts[7]
                connection_info = parts[8] if len(parts) > 8 else ""
                
                if 'UDP' in protocol:
                    connections['total_udp'] += 1
                    connections['udp'].append(connection_info)
                    
                    # Check for WebRTC-related ports
                    if any(port in connection_info for port in ['3478', '3479', '19302', '19303', '19304', '19305', '19306', '19307', '19308', '19309']):
                        connections['stun_turn'] += 1
                    
                    # Check for high dynamic ports (common for WebRTC)
                    if '->' in connection_info:
                        try:
                            remote = connection_info.split('->')[1]
                            if ':' in remote:
                                port = int(remote.split(':')[-1])
                                if 40000 <= port <= 65535:
                                    connections['webrtc_ports'] += 1
                        except:
                            pass
                
                elif 'TCP' in protocol:
                    connections['total_tcp'] += 1
                    connections['tcp'].append(connection_info)
            
            # Also check for UNIX domain sockets (used for IPC)
            unix_cmd = f"{'sudo ' if self.sudo_available else ''}lsof -p {pid} -U 2>/dev/null | wc -l"
            unix_result = subprocess.run(unix_cmd, shell=True, capture_output=True, text=True)
            connections['unix'] = int(unix_result.stdout.strip()) - 1  # Subtract header
            
        except Exception as e:
            pass
        
        return connections
    
    def get_network_stats(self, pid):
        """Get network statistics using netstat"""
        try:
            # Get network stats for the process
            cmd = f"{'sudo ' if self.sudo_available else ''}netstat -anv | grep {pid}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            udp_count = 0
            tcp_established = 0
            
            for line in result.stdout.strip().split('\n'):
                if 'udp' in line.lower():
                    udp_count += 1
                elif 'tcp' in line.lower() and 'ESTABLISHED' in line:
                    tcp_established += 1
            
            return {'udp_netstat': udp_count, 'tcp_established': tcp_established}
        except:
            return {'udp_netstat': 0, 'tcp_established': 0}
    
    def check_audio_devices(self, pid):
        """Check audio device usage"""
        audio_indicators = {
            'coreaudio': False,
            'audiodevice': False,
            'microphone': False,
            'speaker': False
        }
        
        try:
            # Check for audio-related file descriptors
            cmd = f"{'sudo ' if self.sudo_available else ''}lsof -p {pid} 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            output_lower = result.stdout.lower()
            audio_indicators['coreaudio'] = 'coreaudio' in output_lower
            audio_indicators['audiodevice'] = 'audiodevice' in output_lower
            audio_indicators['microphone'] = 'microphone' in output_lower or 'input' in output_lower
            audio_indicators['speaker'] = 'speaker' in output_lower or 'output' in output_lower
            
            # Check system audio input
            audio_cmd = "system_profiler SPAudioDataType 2>/dev/null | grep -A 5 'Input'"
            audio_result = subprocess.run(audio_cmd, shell=True, capture_output=True, text=True)
            system_audio = bool(audio_result.stdout)
            
            return any(audio_indicators.values()), audio_indicators, system_audio
        except:
            return False, audio_indicators, False
    
    def check_dtrace_network(self):
        """Use dtrace to monitor Slack network activity (requires sudo)"""
        if not self.sudo_available:
            return None
        
        try:
            # Quick dtrace probe to check for UDP sends
            cmd = """sudo dtrace -n 'syscall::sendto:entry /execname == "Slack"/ { @[pid] = count(); }' -c 'sleep 1' 2>/dev/null"""
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            
            if result.stdout:
                return "Network activity detected via dtrace"
        except:
            pass
        return None
    
    def collect_comprehensive_data(self):
        """Collect all available data with sudo access"""
        processes = self.get_all_slack_pids()
        
        data = {
            'timestamp': datetime.now(),
            'process_count': len(processes),
            'total_udp': 0,
            'total_tcp': 0,
            'stun_turn_total': 0,
            'webrtc_ports_total': 0,
            'has_audio': False,
            'high_cpu': [],
            'process_details': {},
            'sudo': self.sudo_available
        }
        
        for pid, info in processes.items():
            # Get network connections with sudo
            connections = self.get_network_connections_sudo(pid)
            netstat = self.get_network_stats(pid)
            audio, audio_details, system_audio = self.check_audio_devices(pid)
            
            # Combine data
            udp_total = max(connections['total_udp'], netstat['udp_netstat'])
            tcp_total = max(connections['total_tcp'], netstat['tcp_established'])
            
            data['process_details'][pid] = {
                'name': info['name'],
                'cpu': info['cpu'],
                'mem': info['mem'],
                'udp': udp_total,
                'tcp': tcp_total,
                'unix_sockets': connections['unix'],
                'stun_turn': connections['stun_turn'],
                'webrtc_ports': connections['webrtc_ports'],
                'audio': audio,
                'audio_details': audio_details,
                'udp_samples': connections['udp'][:3],  # First 3 UDP connections
                'tcp_samples': connections['tcp'][:3]   # First 3 TCP connections
            }
            
            data['total_udp'] += udp_total
            data['total_tcp'] += tcp_total
            data['stun_turn_total'] += connections['stun_turn']
            data['webrtc_ports_total'] += connections['webrtc_ports']
            data['has_audio'] = data['has_audio'] or audio
            
            if info['cpu'] > 5.0:
                data['high_cpu'].append(f"{info['name']}:{info['cpu']:.1f}%")
        
        return data
    
    def stdin_listener(self):
        """Listen for stdin commands"""
        print("\n💡 Commands: 'h' = huddle start, 'n' = normal/no huddle, 's' = stats, 'd' = details, 'q' = quit\n")
        
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
                    elif line == 'd':
                        self.print_current_details()
                    elif line == 'q':
                        return
            except:
                pass
            time.sleep(0.1)
    
    def print_current_details(self):
        """Print current detailed state"""
        data = self.collect_comprehensive_data()
        print("\n" + "="*80)
        print(f"📸 CURRENT STATE SNAPSHOT - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)
        
        for pid, details in data['process_details'].items():
            print(f"\n📱 Slack {details['name']} (PID: {pid})")
            print(f"   CPU: {details['cpu']:.1f}%  MEM: {details['mem']:.1f}%")
            print(f"   Network: UDP={details['udp']}, TCP={details['tcp']}, UNIX={details['unix_sockets']}")
            
            if details['stun_turn'] > 0:
                print(f"   🎯 STUN/TURN connections: {details['stun_turn']}")
            if details['webrtc_ports'] > 0:
                print(f"   🎯 WebRTC high ports: {details['webrtc_ports']}")
            
            if details['audio']:
                print(f"   🎧 Audio active: {', '.join(k for k, v in details['audio_details'].items() if v)}")
            
            if details['udp_samples']:
                print(f"   UDP connections:")
                for conn in details['udp_samples'][:3]:
                    print(f"     • {conn}")
            
            if details['tcp_samples'] and details['tcp'] > 0:
                print(f"   TCP connections:")
                for conn in details['tcp_samples'][:2]:
                    print(f"     • {conn}")
        
        print("="*80 + "\n")
    
    def print_analysis(self):
        """Print comparative analysis"""
        print("\n" + "="*80)
        print("📊 HUDDLE DETECTION ANALYSIS")
        print("="*80)
        
        # Process baseline data
        if self.baseline_data:
            print(f"\n🔵 BASELINE (No Huddle) - {len(self.baseline_data)} samples")
            
            process_stats = defaultdict(lambda: {
                'cpu': [], 'udp': [], 'tcp': [], 'stun': [], 'audio': []
            })
            
            for data in self.baseline_data:
                for pid, details in data['process_details'].items():
                    name = details['name']
                    process_stats[name]['cpu'].append(details['cpu'])
                    process_stats[name]['udp'].append(details['udp'])
                    process_stats[name]['tcp'].append(details['tcp'])
                    process_stats[name]['stun'].append(details['stun_turn'])
                    process_stats[name]['audio'].append(1 if details['audio'] else 0)
            
            for name, stats in process_stats.items():
                if stats['cpu']:
                    print(f"\n  {name}:")
                    print(f"    CPU: {sum(stats['cpu'])/len(stats['cpu']):.1f}%")
                    print(f"    UDP: {sum(stats['udp'])/len(stats['udp']):.1f}")
                    print(f"    STUN/TURN: {sum(stats['stun'])/len(stats['stun']):.1f}")
                    print(f"    Audio: {sum(stats['audio'])/len(stats['audio'])*100:.0f}%")
        
        # Process huddle data
        if self.huddle_data:
            print(f"\n🟢 HUDDLE - {len(self.huddle_data)} samples")
            
            process_stats = defaultdict(lambda: {
                'cpu': [], 'udp': [], 'tcp': [], 'stun': [], 'audio': []
            })
            
            for data in self.huddle_data:
                for pid, details in data['process_details'].items():
                    name = details['name']
                    process_stats[name]['cpu'].append(details['cpu'])
                    process_stats[name]['udp'].append(details['udp'])
                    process_stats[name]['tcp'].append(details['tcp'])
                    process_stats[name]['stun'].append(details['stun_turn'])
                    process_stats[name]['audio'].append(1 if details['audio'] else 0)
            
            for name, stats in process_stats.items():
                if stats['cpu']:
                    print(f"\n  {name}:")
                    print(f"    CPU: {sum(stats['cpu'])/len(stats['cpu']):.1f}%")
                    print(f"    UDP: {sum(stats['udp'])/len(stats['udp']):.1f}")
                    print(f"    STUN/TURN: {sum(stats['stun'])/len(stats['stun']):.1f}")
                    print(f"    Audio: {sum(stats['audio'])/len(stats['audio'])*100:.0f}%")
        
        # Calculate differences
        if self.baseline_data and self.huddle_data:
            print("\n🎯 KEY DIFFERENCES (Huddle - Baseline):")
            
            # Calculate per-process differences
            baseline_avg = defaultdict(lambda: {'cpu': 0, 'udp': 0, 'stun': 0})
            huddle_avg = defaultdict(lambda: {'cpu': 0, 'udp': 0, 'stun': 0})
            
            for data in self.baseline_data:
                for pid, details in data['process_details'].items():
                    name = details['name']
                    baseline_avg[name]['cpu'] += details['cpu']
                    baseline_avg[name]['udp'] += details['udp']
                    baseline_avg[name]['stun'] += details['stun_turn']
            
            for data in self.huddle_data:
                for pid, details in data['process_details'].items():
                    name = details['name']
                    huddle_avg[name]['cpu'] += details['cpu']
                    huddle_avg[name]['udp'] += details['udp']
                    huddle_avg[name]['stun'] += details['stun_turn']
            
            # Normalize
            for name in baseline_avg:
                if self.baseline_data:
                    baseline_avg[name]['cpu'] /= len(self.baseline_data)
                    baseline_avg[name]['udp'] /= len(self.baseline_data)
                    baseline_avg[name]['stun'] /= len(self.baseline_data)
            
            for name in huddle_avg:
                if self.huddle_data:
                    huddle_avg[name]['cpu'] /= len(self.huddle_data)
                    huddle_avg[name]['udp'] /= len(self.huddle_data)
                    huddle_avg[name]['stun'] /= len(self.huddle_data)
            
            # Print differences
            for name in set(baseline_avg.keys()) | set(huddle_avg.keys()):
                cpu_diff = huddle_avg[name]['cpu'] - baseline_avg[name]['cpu']
                udp_diff = huddle_avg[name]['udp'] - baseline_avg[name]['udp']
                stun_diff = huddle_avg[name]['stun'] - baseline_avg[name]['stun']
                
                if abs(cpu_diff) > 2 or abs(udp_diff) > 5 or stun_diff > 0:
                    print(f"\n  {name}:")
                    if abs(cpu_diff) > 2:
                        print(f"    CPU: {cpu_diff:+.1f}%")
                    if abs(udp_diff) > 5:
                        print(f"    UDP: {udp_diff:+.1f} connections")
                    if stun_diff > 0:
                        print(f"    STUN/TURN: {stun_diff:+.1f} connections")
        
        print("="*80 + "\n")
    
    def run(self):
        """Main monitoring loop"""
        print("🔬 Slack Huddle Monitor with Sudo Access")
        print("="*80)
        
        # Start stdin listener
        stdin_thread = threading.Thread(target=self.stdin_listener, daemon=True)
        stdin_thread.start()
        
        last_detail = 0
        detail_interval = 15
        
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
                cpu_info = f"CPU:{','.join(data['high_cpu'][:2])}" if data['high_cpu'] else "CPU:normal"
                
                # Enhanced status with WebRTC indicators
                webrtc_indicator = ""
                if data['stun_turn_total'] > 0:
                    webrtc_indicator = f" | STUN:{data['stun_turn_total']}"
                if data['webrtc_ports_total'] > 0:
                    webrtc_indicator += f" | WebRTC:{data['webrtc_ports_total']}"
                
                print(f"\r{state} | UDP:{data['total_udp']:3d} | TCP:{data['total_tcp']:3d} | "
                      f"{audio} | {data['process_count']} procs | {cpu_info[:20]}{webrtc_indicator} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", end="", flush=True)
                
                # Detailed output
                if time.time() - last_detail > detail_interval:
                    print("\n\n" + "-"*80)
                    print(f"PROCESS ACTIVITY - {datetime.now().strftime('%H:%M:%S')}")
                    print("-"*80)
                    
                    for pid, details in data['process_details'].items():
                        # Only show processes with activity
                        if details['cpu'] > 1.0 or details['udp'] > 0 or details['audio'] or details['stun_turn'] > 0:
                            print(f"\n📱 Slack {details['name']} (PID: {pid})")
                            print(f"   Resources: CPU={details['cpu']:.1f}% MEM={details['mem']:.1f}%")
                            print(f"   Network: UDP={details['udp']} TCP={details['tcp']} UNIX={details['unix_sockets']}")
                            
                            if details['stun_turn'] > 0:
                                print(f"   🎯 STUN/TURN: {details['stun_turn']} connections")
                            if details['webrtc_ports'] > 0:
                                print(f"   🎯 WebRTC ports: {details['webrtc_ports']}")
                            if details['audio']:
                                active_audio = [k for k, v in details['audio_details'].items() if v]
                                print(f"   🎧 Audio: {', '.join(active_audio)}")
                            
                            # Show sample connections
                            if details['udp_samples']:
                                print(f"   UDP samples: {details['udp_samples'][0]}")
                    
                    print("-"*80 + "\n")
                    last_detail = time.time()
                
                time.sleep(2)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(2)
        
        print("\n\nFinal Analysis:")
        self.print_analysis()
        print("👋 Monitoring stopped")

if __name__ == "__main__":
    monitor = SudoSlackMonitor()
    monitor.run()