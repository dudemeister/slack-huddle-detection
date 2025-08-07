#!/usr/bin/env python3

import subprocess
import time
import sys
from datetime import datetime
from collections import defaultdict

class SlackHuddleDetector:
    def __init__(self):
        self.huddle_state = False
        self.known_baseline_ips = set()
        self.calibration_samples = 0
        self.sudo_available = self.check_sudo()
        
        # AWS IP ranges commonly used for Slack media servers
        self.media_server_patterns = [
            '44.', '54.', '99.77.', '52.', '35.', '18.', '3.'  # AWS IP prefixes
        ]
        
    def check_sudo(self):
        """Check sudo access"""
        try:
            result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
            if result.returncode == 0:
                return True
            else:
                print("🔐 Requesting sudo access for connection monitoring...")
                result = subprocess.run("sudo true", shell=True)
                return result.returncode == 0
        except:
            return False
    
    def get_slack_connections(self):
        """Get all active connections for Slack processes"""
        connections = {
            'all_ips': set(),
            'tcp_count': 0,
            'udp_count': 0,
            'aws_ips': set(),
            'new_connections': [],
            'process_stats': defaultdict(lambda: {'tcp': 0, 'udp': 0})
        }
        
        try:
            # Get all Slack PIDs
            pids_cmd = "pgrep -f Slack"
            pids_result = subprocess.run(pids_cmd, shell=True, capture_output=True, text=True)
            pids = [p.strip() for p in pids_result.stdout.strip().split('\n') if p.strip()]
            
            for pid in pids:
                # Get process name
                ps_cmd = f"ps -p {pid} -o comm="
                ps_result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True)
                process_name = 'Unknown'
                if 'Renderer' in ps_result.stdout:
                    process_name = 'Renderer'
                elif 'GPU' in ps_result.stdout:
                    process_name = 'GPU'
                elif 'Slack' in ps_result.stdout:
                    process_name = 'Main'
                
                # Get connections
                lsof_cmd = f"{'sudo ' if self.sudo_available else ''}lsof -p {pid} -i -n -P 2>/dev/null"
                lsof_result = subprocess.run(lsof_cmd, shell=True, capture_output=True, text=True)
                
                for line in lsof_result.stdout.strip().split('\n')[1:]:
                    if line and ('TCP' in line or 'UDP' in line):
                        parts = line.split()
                        if len(parts) >= 9:
                            protocol = 'TCP' if 'TCP' in parts[7] else 'UDP'
                            connection_str = parts[8]
                            
                            # Count protocols
                            if protocol == 'TCP':
                                connections['tcp_count'] += 1
                                connections['process_stats'][process_name]['tcp'] += 1
                            else:
                                connections['udp_count'] += 1
                                connections['process_stats'][process_name]['udp'] += 1
                            
                            # Extract remote IP
                            if '->' in connection_str:
                                remote = connection_str.split('->')[1]
                                if ':' in remote:
                                    ip = remote.rsplit(':', 1)[0]
                                    # Clean IPv6 brackets
                                    ip = ip.strip('[]')
                                    
                                    connections['all_ips'].add(ip)
                                    
                                    # Check if it's an AWS IP
                                    if any(ip.startswith(prefix) for prefix in self.media_server_patterns):
                                        connections['aws_ips'].add(ip)
                                    
                                    # Track new IPs
                                    if ip not in self.known_baseline_ips:
                                        connections['new_connections'].append({
                                            'ip': ip,
                                            'protocol': protocol,
                                            'process': process_name
                                        })
            
        except Exception as e:
            pass
        
        return connections
    
    def calibrate_baseline(self):
        """Build baseline of normal IPs"""
        print("📊 Calibrating baseline connections...")
        
        for i in range(5):
            connections = self.get_slack_connections()
            self.known_baseline_ips.update(connections['all_ips'])
            print(f"\rCalibration {i+1}/5: {len(self.known_baseline_ips)} unique IPs", end="", flush=True)
            time.sleep(2)
        
        print(f"\n✅ Baseline established: {len(self.known_baseline_ips)} known IPs")
        print(f"   AWS IPs in baseline: {len([ip for ip in self.known_baseline_ips if any(ip.startswith(p) for p in self.media_server_patterns)])}")
    
    def detect_huddle(self):
        """Detect huddle based on new AWS connections"""
        connections = self.get_slack_connections()
        
        # Detection criteria
        new_aws_ips = connections['aws_ips'] - self.known_baseline_ips
        new_ip_count = len(connections['all_ips'] - self.known_baseline_ips)
        
        # Score-based detection
        score = 0
        reasons = []
        
        # Primary indicator: New AWS IPs
        if len(new_aws_ips) > 0:
            score += 40 + (len(new_aws_ips) * 10)  # More IPs = higher confidence
            reasons.append(f"{len(new_aws_ips)} new AWS IPs")
            
            # Show some IPs for debugging
            sample_ips = list(new_aws_ips)[:3]
            for ip in sample_ips:
                reasons.append(f"  → {ip}")
        
        # Secondary indicator: Multiple new IPs
        if new_ip_count > 3:
            score += 20
            reasons.append(f"{new_ip_count} new connections total")
        
        # Tertiary indicator: Increased TCP connections
        baseline_tcp = 210  # From your data
        if connections['tcp_count'] > baseline_tcp + 5:
            score += 10
            reasons.append(f"TCP increase ({connections['tcp_count']})")
        
        # Process-specific changes
        if 'Renderer' in connections['process_stats']:
            renderer_stats = connections['process_stats']['Renderer']
            if renderer_stats['tcp'] > 105:  # Baseline ~210 split across processes
                score += 10
                reasons.append(f"Renderer TCP high ({renderer_stats['tcp']})")
        
        is_huddle = score >= 50
        
        return {
            'is_huddle': is_huddle,
            'score': score,
            'new_aws_ips': new_aws_ips,
            'new_ip_count': new_ip_count,
            'tcp_count': connections['tcp_count'],
            'udp_count': connections['udp_count'],
            'reasons': reasons
        }
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - AWS IP Based")
        print("=" * 60)
        
        if not self.sudo_available:
            print("⚠️  Running without sudo - detection may be limited")
        else:
            print("✅ Sudo access available")
        
        print("\nThis detector monitors for new AWS media server connections")
        print("that appear when Slack huddles start.\n")
        
        # Calibrate baseline
        self.calibrate_baseline()
        print("\nMonitoring for huddles...\n")
        
        last_state = False
        consecutive_detections = 0
        
        while True:
            try:
                result = self.detect_huddle()
                
                # Require 2 consecutive detections to avoid flickers
                if result['is_huddle']:
                    consecutive_detections += 1
                else:
                    consecutive_detections = 0
                
                is_confirmed_huddle = consecutive_detections >= 2
                
                # State change detection
                if is_confirmed_huddle and not last_state:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score: {result['score']}")
                    for reason in result['reasons']:
                        print(f"   {reason}")
                    last_state = True
                    self.huddle_state = True
                
                elif not is_confirmed_huddle and last_state:
                    print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                    last_state = False
                    self.huddle_state = False
                    # Add huddle IPs to baseline after huddle ends
                    self.known_baseline_ips.update(result['new_aws_ips'])
                
                # Status line
                if is_confirmed_huddle:
                    status = f"🎙️  IN HUDDLE"
                else:
                    status = "💤 No huddle"
                
                aws_info = f"AWS: {len(result['new_aws_ips'])}" if result['new_aws_ips'] else "AWS: 0"
                
                print(f"\r{status} | {aws_info} | "
                      f"New IPs: {result['new_ip_count']} | "
                      f"TCP: {result['tcp_count']} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(3)
        
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    detector = SlackHuddleDetector()
    detector.run()