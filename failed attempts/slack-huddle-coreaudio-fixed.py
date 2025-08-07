#!/usr/bin/env python3

import subprocess
import time
import sys
import os
from datetime import datetime
from collections import defaultdict
import json

class CoreAudioMonitor:
    def __init__(self):
        self.huddle_state = False
        self.baseline_score = 0
        
    def run_command_with_timeout(self, cmd, timeout=1):
        """Run a command with timeout to prevent hanging"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return ""
        except:
            return ""
    
    def get_audio_devices_state(self):
        """Get current audio device state"""
        try:
            # Simpler check - just count audio-related file descriptors
            cmd = "sudo lsof -c Slack 2>/dev/null | grep -iE '(audio|Audio)' | wc -l"
            output = self.run_command_with_timeout(cmd)
            count = int(output) if output.isdigit() else 0
            return {'audio_fds': count}
        except:
            return {'audio_fds': 0}
    
    def check_audio_unit_state(self):
        """Check AudioUnit hosting for Slack processes"""
        try:
            # Check if Slack is hosting audio units
            cmd = "sudo lsof -c Slack 2>/dev/null | grep -iE '(AudioUnit|audiounit|HAL|CoreAudio)' | wc -l"
            output = self.run_command_with_timeout(cmd)
            audio_unit_count = int(output) if output.isdigit() else 0
            
            # Check for audio-related shared memory
            shm_cmd = "sudo lsof -c Slack 2>/dev/null | grep -E '(AudioIPCS|com.apple.audio|POSIX\\sSHARED)' | wc -l"
            shm_output = self.run_command_with_timeout(shm_cmd)
            audio_shm_count = int(shm_output) if shm_output.isdigit() else 0
            
            return {
                'audio_units': audio_unit_count,
                'audio_shm': audio_shm_count
            }
        except Exception as e:
            print(f"Debug: audio_unit_state error: {e}")
            return {'audio_units': 0, 'audio_shm': 0}
    
    def monitor_audio_server_connections(self):
        """Monitor connections to CoreAudio server"""
        try:
            # Get first Slack Helper PID
            pid_cmd = "pgrep -f 'Slack Helper' | head -1"
            pid_output = self.run_command_with_timeout(pid_cmd)
            
            if pid_output and pid_output.isdigit():
                # Check Mach ports related to audio
                cmd = f"sudo lsmp -p {pid_output} 2>/dev/null | grep -iE '(audio|sound|hal)' | wc -l"
                output = self.run_command_with_timeout(cmd)
                audio_ports = int(output) if output.isdigit() else 0
            else:
                audio_ports = 0
            
            # Check XPC connections to audio services
            xpc_cmd = "sudo lsof -c Slack 2>/dev/null | grep -E 'com.apple.audio' | wc -l"
            xpc_output = self.run_command_with_timeout(xpc_cmd)
            audio_xpc = int(xpc_output) if xpc_output.isdigit() else 0
            
            return {
                'audio_mach_ports': audio_ports,
                'audio_xpc_connections': audio_xpc
            }
        except Exception as e:
            print(f"Debug: audio_server_connections error: {e}")
            return {'audio_mach_ports': 0, 'audio_xpc_connections': 0}
    
    def check_coreaudio_power_state(self):
        """Check if CoreAudio is in active state for Slack"""
        try:
            # Quick check - don't parse logs which can be slow
            # Just check if Slack processes have high thread count (indicates activity)
            cmd = "ps -M $(pgrep -f 'Slack Helper' | head -1) 2>/dev/null | wc -l"
            output = self.run_command_with_timeout(cmd)
            thread_count = int(output) if output.isdigit() else 0
            
            return {'thread_count': thread_count}
        except:
            return {'thread_count': 0}
    
    def check_network_activity(self):
        """Quick network activity check"""
        try:
            # Count TCP connections for Slack
            tcp_cmd = "sudo lsof -c Slack -i TCP 2>/dev/null | grep ESTABLISHED | wc -l"
            tcp_output = self.run_command_with_timeout(tcp_cmd)
            tcp_count = int(tcp_output) if tcp_output.isdigit() else 0
            
            # Count UDP connections
            udp_cmd = "sudo lsof -c Slack -i UDP 2>/dev/null | wc -l"
            udp_output = self.run_command_with_timeout(udp_cmd)
            udp_count = int(udp_output) if udp_output.isdigit() else 0
            
            return {'tcp': tcp_count, 'udp': udp_count}
        except:
            return {'tcp': 0, 'udp': 0}
    
    def detect_huddle(self):
        """Detect huddle based on CoreAudio state"""
        # Gather metrics with timeouts
        audio_units = self.check_audio_unit_state()
        audio_connections = self.monitor_audio_server_connections()
        audio_devices = self.get_audio_devices_state()
        power_state = self.check_coreaudio_power_state()
        network = self.check_network_activity()
        
        score = 0
        reasons = []
        
        # Scoring based on audio state
        if audio_units['audio_units'] > 5:
            score += 30
            reasons.append(f"AudioUnits: {audio_units['audio_units']}")
        
        if audio_units['audio_shm'] > 2:
            score += 25
            reasons.append(f"Audio SHM: {audio_units['audio_shm']}")
        
        if audio_connections['audio_mach_ports'] > 10:
            score += 25
            reasons.append(f"Audio Mach ports: {audio_connections['audio_mach_ports']}")
        
        if audio_connections['audio_xpc_connections'] > 3:
            score += 20
            reasons.append(f"Audio XPC: {audio_connections['audio_xpc_connections']}")
        
        if audio_devices['audio_fds'] > 10:
            score += 20
            reasons.append(f"Audio FDs: {audio_devices['audio_fds']}")
        
        # Thread count as activity indicator
        if power_state['thread_count'] > 100:
            score += 10
            reasons.append(f"High thread count: {power_state['thread_count']}")
        
        # Network activity as supplementary indicator
        if network['tcp'] > 220 or network['udp'] > 300:
            score += 10
            reasons.append(f"Network activity: TCP={network['tcp']}, UDP={network['udp']}")
        
        return {
            'is_huddle': score >= 50,
            'score': score,
            'reasons': reasons,
            'details': {
                'audio_units': audio_units,
                'connections': audio_connections,
                'devices': audio_devices,
                'threads': power_state['thread_count'],
                'network': network
            }
        }
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - CoreAudio Monitor (Fixed)")
        print("=" * 60)
        print("Monitoring CoreAudio subsystem for huddle activity")
        print("This requires sudo access for audio system monitoring\n")
        
        # Check sudo
        print("Checking sudo access...")
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("🔐 Requesting sudo access...")
            result = subprocess.run("sudo true", shell=True)
            if result.returncode != 0:
                print("❌ Sudo access required. Please run with sudo.")
                return
        print("✅ Sudo access confirmed\n")
        
        print("Calibrating baseline audio state...")
        
        # Quick calibration - just 3 samples
        baseline_scores = []
        for i in range(3):
            print(f"\rCalibrating... {i+1}/3", end="", flush=True)
            baseline = self.detect_huddle()
            baseline_scores.append(baseline['score'])
            time.sleep(1)
        
        self.baseline_score = sum(baseline_scores) / len(baseline_scores)
        print(f"\n✅ Baseline score: {self.baseline_score:.1f}\n")
        print("Monitoring for huddles...\n")
        
        last_state = False
        last_score = 0
        score_history = []
        
        while True:
            try:
                result = self.detect_huddle()
                
                # Track score history for trend detection
                score_history.append(result['score'])
                if len(score_history) > 5:
                    score_history.pop(0)
                
                # Calculate score trend
                score_trend = 0
                if len(score_history) >= 2:
                    score_trend = score_history[-1] - score_history[-2]
                
                # Adaptive thresholds based on baseline
                start_threshold = max(50, self.baseline_score + 20)
                end_threshold = max(30, self.baseline_score + 10)
                
                # State detection with hysteresis and trend
                if not last_state and result['score'] >= start_threshold:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score: {result['score']} (baseline: {self.baseline_score:.1f})")
                    for reason in result['reasons']:
                        print(f"   • {reason}")
                    last_state = True
                
                elif last_state and result['score'] < end_threshold and score_trend <= 0:
                    print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score dropped to {result['score']}")
                    last_state = False
                    # Update baseline after huddle
                    self.baseline_score = result['score']
                
                # Status line
                if last_state:
                    status = "🎙️  IN HUDDLE"
                else:
                    status = "💤 No huddle"
                
                # Display key metrics
                details = result['details']
                trend_indicator = "↑" if score_trend > 0 else "↓" if score_trend < 0 else "→"
                
                print(f"\r{status} | Score: {result['score']:3d}{trend_indicator} | "
                      f"Units: {details['audio_units']['audio_units']} | "
                      f"Ports: {details['connections']['audio_mach_ports']} | "
                      f"SHM: {details['audio_units']['audio_shm']} | "
                      f"Net: {details['network']['tcp']}/{details['network']['udp']} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                last_score = result['score']
                time.sleep(2)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError in main loop: {e}")
                time.sleep(2)
        
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    monitor = CoreAudioMonitor()
    monitor.run()