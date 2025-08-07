#!/usr/bin/env python3

import subprocess
import time
import sys
from datetime import datetime
import os

class SlackHuddleDetector:
    def __init__(self):
        self.huddle_state = False
        self.sudo_available = self.check_sudo()
        self.cpu_history = []  # Track CPU over time
        self.stun_history = []  # Track STUN over time
        
    def check_sudo(self):
        """Check if we have sudo access"""
        try:
            result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
            if result.returncode == 0:
                return True
            else:
                print("🔐 Requesting sudo access for STUN/TURN detection...")
                result = subprocess.run("sudo true", shell=True)
                return result.returncode == 0
        except:
            return False
    
    def get_slack_processes(self):
        """Get all Slack processes with CPU usage"""
        try:
            cmd = "ps aux | grep -E '(Slack|slack)' | grep -v grep | grep -v slack-huddle"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            processes = {}
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split(None, 10)
                    if len(parts) > 10:
                        pid = parts[1]
                        cpu = float(parts[2])
                        cmd = parts[10]
                        
                        # Identify process type
                        if 'Slack Helper (Renderer)' in cmd:
                            name = 'Renderer'
                        elif 'Slack Helper (GPU)' in cmd:
                            name = 'GPU'
                        elif 'Slack.app' in cmd:
                            name = 'Main'
                        else:
                            continue
                        
                        processes[name] = {
                            'pid': pid,
                            'cpu': cpu
                        }
            
            return processes
        except:
            return {}
    
    def check_stun_connections(self):
        """Check for STUN/TURN connections - the most reliable indicator"""
        if not self.sudo_available:
            print("\n⚠️  Sudo required for STUN detection. Please run with sudo.")
            return 0, []
        
        stun_count = 0
        stun_details = []
        
        try:
            # Get all Slack PIDs
            pids_cmd = "pgrep -f Slack"
            pids_result = subprocess.run(pids_cmd, shell=True, capture_output=True, text=True)
            pids = pids_result.stdout.strip().split('\n')
            
            # STUN/TURN ports used by WebRTC
            stun_ports = {
                '3478': 'STUN',
                '3479': 'TURN', 
                '19302': 'Google STUN',
                '19303': 'Google STUN',
                '19304': 'Google STUN',
                '19305': 'Google STUN',
                '19306': 'Google STUN',
                '19307': 'Google STUN',
                '19308': 'Google STUN',
                '19309': 'Google STUN'
            }
            
            for pid in pids:
                if pid:
                    # Check for network connections
                    cmd = f"sudo lsof -p {pid} -i -n -P 2>/dev/null"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    
                    for port, service in stun_ports.items():
                        matches = result.stdout.count(f":{port}")
                        if matches > 0:
                            stun_count += matches
                            stun_details.append(f"{service}:{port}")
            
            # Also check for high UDP ports typical of WebRTC media
            if stun_count > 0:
                # If we have STUN, check for high UDP ports (media streams)
                for pid in pids:
                    if pid:
                        cmd = f"sudo lsof -p {pid} -iUDP -n -P 2>/dev/null | grep -E ':([4-6][0-9]{{4}}|3[5-9][0-9]{{3}})'"
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                        high_port_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
                        if high_port_count > 0:
                            stun_details.append(f"HighUDP:{high_port_count}")
            
            return stun_count, list(set(stun_details))
        except Exception as e:
            return 0, []
    
    def detect_huddle(self):
        """Detect huddle primarily based on STUN/TURN connections"""
        processes = self.get_slack_processes()
        stun_count, stun_details = self.check_stun_connections()
        
        # Get CPU values
        renderer_cpu = processes.get('Renderer', {}).get('cpu', 0)
        gpu_cpu = processes.get('GPU', {}).get('cpu', 0)
        
        # Track history (keep last 10 samples)
        self.cpu_history.append(renderer_cpu)
        self.stun_history.append(stun_count)
        if len(self.cpu_history) > 10:
            self.cpu_history.pop(0)
        if len(self.stun_history) > 10:
            self.stun_history.pop(0)
        
        # Calculate sustained CPU (average of last 3 samples)
        sustained_cpu = 0
        if len(self.cpu_history) >= 3:
            sustained_cpu = sum(self.cpu_history[-3:]) / 3
        
        # STUN-focused detection logic
        is_huddle = False
        confidence = "LOW"
        reasons = []
        
        # Primary indicator: STUN/TURN connections
        if stun_count > 0:
            is_huddle = True
            confidence = "HIGH"
            reasons.append(f"STUN/TURN active ({stun_count} connections)")
            if stun_details:
                reasons.append(f"Services: {', '.join(stun_details[:3])}")
        
        # Secondary indicator: Sustained high CPU without STUN (lower confidence)
        elif sustained_cpu > 25 and renderer_cpu > 20:
            # Only if CPU stays high for multiple samples
            if len([c for c in self.cpu_history[-3:] if c > 20]) >= 2:
                is_huddle = True
                confidence = "MEDIUM"
                reasons.append(f"Sustained high CPU ({sustained_cpu:.0f}% avg)")
        
        return {
            'is_huddle': is_huddle,
            'confidence': confidence,
            'stun_count': stun_count,
            'stun_details': stun_details,
            'renderer_cpu': renderer_cpu,
            'gpu_cpu': gpu_cpu,
            'sustained_cpu': sustained_cpu,
            'reasons': reasons
        }
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - STUN-Focused")
        print("=" * 50)
        
        if not self.sudo_available:
            print("❌ Sudo access required for STUN detection!")
            print("Please run: sudo python3 slack-huddle-detector-stun.py")
            return
        
        print("✅ Sudo available - monitoring STUN/TURN connections")
        print("ℹ️  STUN/TURN connections are the primary indicator")
        print("ℹ️  CPU spikes alone won't trigger detection\n")
        
        last_state = False
        
        while True:
            try:
                result = self.detect_huddle()
                
                # State change detection
                if result['is_huddle'] and not last_state:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Confidence: {result['confidence']}")
                    for reason in result['reasons']:
                        print(f"   • {reason}")
                    last_state = True
                    self.huddle_state = True
                
                elif not result['is_huddle'] and last_state:
                    print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                    last_state = False
                    self.huddle_state = False
                
                # Status line
                if result['is_huddle']:
                    status = f"🎙️  IN HUDDLE ({result['confidence']})"
                else:
                    status = "💤 No huddle"
                
                # Build info string
                info = f"STUN:{result['stun_count']} | CPU:R={result['renderer_cpu']:.0f}%"
                if result['sustained_cpu'] > 10:
                    info += f" (avg:{result['sustained_cpu']:.0f}%)"
                
                print(f"\r{status} | {info} | {datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                time.sleep(2)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(2)
        
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    detector = SlackHuddleDetector()
    detector.run()