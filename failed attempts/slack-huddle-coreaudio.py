#!/usr/bin/env python3

import subprocess
import time
import sys
import os
from datetime import datetime
from collections import defaultdict
import threading
import signal

class CoreAudioMonitor:
    def __init__(self):
        self.huddle_state = False
        self.audio_state = defaultdict(dict)
        self.monitoring_thread = None
        self.stop_monitoring = False
        
    def monitor_coreaudio_hal(self):
        """Monitor CoreAudio HAL for audio device changes"""
        try:
            # Monitor CoreAudio property changes
            cmd = """sudo dtrace -qn '
                /* Monitor CoreAudio HAL property changes */
                pid$target::*AudioHardware*:entry,
                pid$target::*AudioDevice*:entry,
                pid$target::*AudioStream*:entry
                /execname == "coreaudiod" || execname == "Slack"/
                {
                    @calls[probefunc] = count();
                }
                
                /* Monitor audio device state changes */
                syscall::ioctl:entry
                /execname == "Slack" || execname == "coreaudiod"/
                {
                    @ioctl[execname] = count();
                }
                
                profile:::tick-1sec
                {
                    printf("=== CoreAudio Activity ===\\n");
                    printa("  %s: %@d\\n", @calls);
                    printa("  ioctl_%s: %@d\\n", @ioctl);
                    printf("\\n");
                    clear(@calls);
                    clear(@ioctl);
                }
            ' -p $(pgrep coreaudiod | head -1) 2>/dev/null"""
            
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            while not self.stop_monitoring:
                line = process.stdout.readline()
                if line:
                    # Parse DTrace output for audio activity
                    if 'AudioDevice' in line or 'AudioStream' in line:
                        # Extract activity level
                        try:
                            parts = line.split(':')
                            if len(parts) >= 2:
                                count = int(parts[1].strip())
                                if count > 0:
                                    self.audio_state['hal_activity'] = count
                        except:
                            pass
            
            process.terminate()
        except Exception as e:
            print(f"HAL monitoring error: {e}")
    
    def get_audio_devices_state(self):
        """Get current audio device state using system_profiler"""
        try:
            cmd = "system_profiler SPAudioDataType -json 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            import json
            data = json.loads(result.stdout)
            
            devices = {
                'input_sources': 0,
                'output_devices': 0,
                'active_input': None,
                'active_output': None
            }
            
            if 'SPAudioDataType' in data:
                for item in data['SPAudioDataType']:
                    if '_items' in item:
                        for device in item['_items']:
                            if 'coreaudio_input_source' in device:
                                devices['active_input'] = device.get('_name', 'Unknown')
                            if 'coreaudio_output_source' in device:
                                devices['active_output'] = device.get('_name', 'Unknown')
                            
                            # Count devices
                            if device.get('coreaudio_device_input'):
                                devices['input_sources'] += int(device['coreaudio_device_input'])
                            if device.get('coreaudio_device_output'):
                                devices['output_devices'] += int(device['coreaudio_device_output'])
            
            return devices
        except:
            return None
    
    def check_audio_unit_state(self):
        """Check AudioUnit hosting for Slack processes"""
        try:
            # Check if Slack is hosting audio units
            cmd = "sudo lsof -c Slack 2>/dev/null | grep -iE '(AudioUnit|audiounit|HAL|CoreAudio)' | wc -l"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            audio_unit_count = int(result.stdout.strip())
            
            # Check for audio-related shared memory
            shm_cmd = "sudo lsof -c Slack 2>/dev/null | grep -E '(AudioIPCS|com.apple.audio)' | wc -l"
            shm_result = subprocess.run(shm_cmd, shell=True, capture_output=True, text=True)
            audio_shm_count = int(shm_result.stdout.strip())
            
            return {
                'audio_units': audio_unit_count,
                'audio_shm': audio_shm_count
            }
        except:
            return {'audio_units': 0, 'audio_shm': 0}
    
    def monitor_audio_server_connections(self):
        """Monitor connections to CoreAudio server"""
        try:
            # Check Mach ports related to audio
            cmd = """sudo lsmp -p $(pgrep -f "Slack Helper" | head -1) 2>/dev/null | grep -iE "(audio|sound|hal)" | wc -l"""
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            audio_ports = int(result.stdout.strip())
            
            # Check XPC connections to audio services
            xpc_cmd = """sudo lsof -c Slack 2>/dev/null | grep -E "com.apple.audio" | wc -l"""
            xpc_result = subprocess.run(xpc_cmd, shell=True, capture_output=True, text=True)
            audio_xpc = int(xpc_result.stdout.strip())
            
            return {
                'audio_mach_ports': audio_ports,
                'audio_xpc_connections': audio_xpc
            }
        except:
            return {'audio_mach_ports': 0, 'audio_xpc_connections': 0}
    
    def get_audio_session_state(self):
        """Get audio session state using log stream"""
        try:
            # Quick check of recent audio logs
            cmd = """log show --predicate 'subsystem == "com.apple.audio" AND process == "Slack"' --last 5s --style compact 2>/dev/null | grep -iE "(start|stop|activate|deactivate)" | wc -l"""
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            recent_changes = int(result.stdout.strip())
            
            return recent_changes
        except:
            return 0
    
    def check_coreaudio_power_state(self):
        """Check if CoreAudio is in active state for Slack"""
        try:
            # Check power assertions related to audio
            cmd = "pmset -g assertions 2>/dev/null | grep -i audio"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            audio_assertions = 0
            if result.stdout:
                # Count audio-related power assertions
                audio_assertions = result.stdout.count('audio')
            
            # Check if Slack has preventative audio assertions
            slack_cmd = "pmset -g assertionslog 2>/dev/null | tail -100 | grep -i slack | grep -i audio | wc -l"
            slack_result = subprocess.run(slack_cmd, shell=True, capture_output=True, text=True)
            slack_audio_assertions = int(slack_result.stdout.strip())
            
            return {
                'audio_assertions': audio_assertions,
                'slack_audio_assertions': slack_audio_assertions
            }
        except:
            return {'audio_assertions': 0, 'slack_audio_assertions': 0}
    
    def detect_huddle(self):
        """Detect huddle based on CoreAudio state"""
        # Gather all audio-related metrics
        audio_units = self.check_audio_unit_state()
        audio_connections = self.monitor_audio_server_connections()
        audio_devices = self.get_audio_devices_state()
        session_changes = self.get_audio_session_state()
        power_state = self.check_coreaudio_power_state()
        
        score = 0
        reasons = []
        
        # Scoring based on audio state
        if audio_units['audio_units'] > 5:
            score += 30
            reasons.append(f"AudioUnits: {audio_units['audio_units']}")
        
        if audio_units['audio_shm'] > 2:
            score += 20
            reasons.append(f"Audio SHM: {audio_units['audio_shm']}")
        
        if audio_connections['audio_mach_ports'] > 10:
            score += 25
            reasons.append(f"Audio Mach ports: {audio_connections['audio_mach_ports']}")
        
        if audio_connections['audio_xpc_connections'] > 3:
            score += 20
            reasons.append(f"Audio XPC: {audio_connections['audio_xpc_connections']}")
        
        if session_changes > 0:
            score += 15
            reasons.append("Recent audio session changes")
        
        if power_state['slack_audio_assertions'] > 0:
            score += 30
            reasons.append("Slack audio power assertions")
        
        # Check for specific audio device configuration
        if audio_devices:
            if audio_devices['active_input'] and audio_devices['active_output']:
                score += 10
                reasons.append(f"Audio I/O: {audio_devices['active_input']}")
        
        return {
            'is_huddle': score >= 50,
            'score': score,
            'reasons': reasons,
            'details': {
                'audio_units': audio_units,
                'connections': audio_connections,
                'devices': audio_devices,
                'session_changes': session_changes,
                'power': power_state
            }
        }
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - CoreAudio HAL Monitor")
        print("=" * 60)
        print("Monitoring CoreAudio subsystem for huddle activity")
        print("This requires sudo access for audio system monitoring\n")
        
        # Check sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("🔐 Requesting sudo access...")
            subprocess.run("sudo true", shell=True)
        
        # Start background HAL monitor
        # self.monitoring_thread = threading.Thread(target=self.monitor_coreaudio_hal, daemon=True)
        # self.monitoring_thread.start()
        
        print("Calibrating baseline audio state...")
        time.sleep(3)
        
        baseline = self.detect_huddle()
        baseline_score = baseline['score']
        print(f"✅ Baseline score: {baseline_score}\n")
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
                start_threshold = max(50, baseline_score + 20)
                end_threshold = max(30, baseline_score + 10)
                
                # State detection with hysteresis and trend
                if not last_state and result['score'] >= start_threshold:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score: {result['score']} (baseline: {baseline_score})")
                    for reason in result['reasons']:
                        print(f"   • {reason}")
                    last_state = True
                
                elif last_state and result['score'] < end_threshold and score_trend <= 0:
                    print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score dropped to {result['score']}")
                    last_state = False
                    # Update baseline after huddle
                    baseline_score = result['score']
                
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
                      f"XPC: {details['connections']['audio_xpc_connections']} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                last_score = result['score']
                time.sleep(2)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(2)
        
        print("\n\n👋 Stopped monitoring")
        self.stop_monitoring = True

if __name__ == "__main__":
    monitor = CoreAudioMonitor()
    monitor.run()