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
        self.baseline_cpu = {}
        self.sample_count = 0
        
    def check_sudo(self):
        """Check if we have sudo access"""
        try:
            result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
            if result.returncode == 0:
                return True
            else:
                print("🔐 Requesting sudo access for better detection...")
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
                        elif 'Slack Helper (Plugin)' in cmd:
                            name = 'Plugin'
                        elif 'Slack Helper' in cmd:
                            name = 'Helper'
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
        """Check for STUN/TURN connections indicating WebRTC"""
        stun_count = 0
        
        if not self.sudo_available:
            return 0
        
        try:
            # Get all Slack PIDs
            pids_cmd = "pgrep -f Slack"
            pids_result = subprocess.run(pids_cmd, shell=True, capture_output=True, text=True)
            pids = pids_result.stdout.strip().split('\n')
            
            for pid in pids:
                if pid:
                    # Check for STUN/TURN ports
                    cmd = f"sudo lsof -p {pid} -i -n -P 2>/dev/null"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    
                    # Common STUN/TURN ports
                    stun_ports = ['3478', '3479', '19302', '19303', '19304', '19305', '19306', '19307', '19308', '19309']
                    
                    for port in stun_ports:
                        if f":{port}" in result.stdout:
                            stun_count += result.stdout.count(f":{port}")
            
            return stun_count
        except:
            return 0
    
    def detect_huddle(self):
        """Detect if a huddle is active based on multiple indicators"""
        processes = self.get_slack_processes()
        stun_connections = self.check_stun_connections()
        
        # Detection criteria
        renderer_cpu = processes.get('Renderer', {}).get('cpu', 0)
        gpu_cpu = processes.get('GPU', {}).get('cpu', 0)
        main_cpu = processes.get('Main', {}).get('cpu', 0)
        
        # Update baseline CPU (rolling average of first 5 samples)
        if self.sample_count < 5 and not self.huddle_state:
            for name, data in processes.items():
                if name not in self.baseline_cpu:
                    self.baseline_cpu[name] = []
                self.baseline_cpu[name].append(data['cpu'])
            self.sample_count += 1
        
        # Calculate baseline averages
        baseline_renderer = sum(self.baseline_cpu.get('Renderer', [0])) / max(len(self.baseline_cpu.get('Renderer', [0])), 1)
        baseline_gpu = sum(self.baseline_cpu.get('GPU', [0])) / max(len(self.baseline_cpu.get('GPU', [0])), 1)
        
        # Detection logic
        huddle_indicators = {
            'renderer_cpu_spike': renderer_cpu > baseline_renderer + 15,  # 15% above baseline
            'gpu_cpu_spike': gpu_cpu > baseline_gpu + 5,  # 5% above baseline
            'high_renderer_cpu': renderer_cpu > 20,  # Absolute threshold
            'stun_detected': stun_connections > 2,  # STUN/TURN connections
            'combined_cpu': (renderer_cpu + gpu_cpu) > 30  # Combined CPU usage
        }
        
        # Score-based detection
        score = 0
        reasons = []
        
        if huddle_indicators['renderer_cpu_spike']:
            score += 40
            reasons.append(f"Renderer CPU spike ({renderer_cpu:.1f}%)")
        
        if huddle_indicators['high_renderer_cpu']:
            score += 20
            reasons.append(f"High Renderer CPU")
        
        if huddle_indicators['gpu_cpu_spike']:
            score += 20
            reasons.append(f"GPU CPU spike ({gpu_cpu:.1f}%)")
        
        if huddle_indicators['stun_detected']:
            score += 30
            reasons.append(f"STUN/TURN ({stun_connections})")
        
        if huddle_indicators['combined_cpu']:
            score += 10
            reasons.append("High combined CPU")
        
        # Determine huddle state
        is_huddle = score >= 50
        
        return {
            'is_huddle': is_huddle,
            'score': score,
            'reasons': reasons,
            'renderer_cpu': renderer_cpu,
            'gpu_cpu': gpu_cpu,
            'main_cpu': main_cpu,
            'stun_connections': stun_connections,
            'processes': len(processes)
        }
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector v2.0")
        print("=" * 50)
        print(f"Sudo: {'✅ Available' if self.sudo_available else '⚠️  Limited mode'}")
        print("Calibrating baseline...\n")
        
        # Quick calibration phase
        for i in range(5):
            self.detect_huddle()
            print(f"\rCalibrating... {i+1}/5", end="", flush=True)
            time.sleep(1)
        
        print("\n✅ Ready! Monitoring for huddles...\n")
        
        last_state = False
        
        while True:
            try:
                result = self.detect_huddle()
                
                # State change detection
                if result['is_huddle'] and not last_state:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score: {result['score']}/100")
                    print(f"   Reasons: {', '.join(result['reasons'])}")
                    last_state = True
                    self.huddle_state = True
                
                elif not result['is_huddle'] and last_state:
                    print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                    last_state = False
                    self.huddle_state = False
                
                # Status line
                if result['is_huddle']:
                    status = f"🎙️  IN HUDDLE (Score: {result['score']})"
                else:
                    status = "💤 No huddle"
                
                # Build info string
                info = f"CPU: R={result['renderer_cpu']:.0f}% G={result['gpu_cpu']:.0f}%"
                if result['stun_connections'] > 0:
                    info += f" | STUN: {result['stun_connections']}"
                
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