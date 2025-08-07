#!/usr/bin/env python3

import subprocess
import time
import sys
import os
from datetime import datetime
from collections import defaultdict, deque
import re
import json

class IOKitAudioMonitor:
    def __init__(self):
        self.baseline_state = {}
        self.in_huddle = False
        self.audio_state_history = deque(maxlen=5)
        
    def run_command_safe(self, cmd, timeout=1):
        """Run command with timeout and error handling"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return ""
        except Exception:
            return ""
    
    def get_ioregistry_audio_state(self):
        """Query IORegistry for audio device state"""
        try:
            # Get audio device state from IORegistry
            output = self.run_command_safe("ioreg -r -c IOAudioDevice -k IOAudioDeviceTransportType 2>/dev/null", timeout=2)
            
            audio_devices = {
                'active_devices': 0,
                'input_active': False,
                'output_active': False,
                'sample_rate': 0,
                'active_clients': 0,
                'engine_running': False
            }
            
            if not output:
                return audio_devices
            
            # Parse IORegistry output
            for line in output.split('\n'):
                if 'IOAudioDeviceTransportType' in line:
                    audio_devices['active_devices'] += 1
                if 'IOAudioDeviceInputAvailable' in line and 'Yes' in line:
                    audio_devices['input_active'] = True
                if 'IOAudioDeviceOutputAvailable' in line and 'Yes' in line:
                    audio_devices['output_active'] = True
                if 'IOAudioDeviceSampleRate' in line:
                    match = re.search(r'= (\d+)', line)
                    if match:
                        audio_devices['sample_rate'] = int(match.group(1))
            
            # Get audio engine state - simpler query
            engine_output = self.run_command_safe("ioreg -r -c IOAudioEngine 2>/dev/null | grep -c IOAudioEngine")
            audio_devices['active_clients'] = int(engine_output) if engine_output.isdigit() else 0
            
            return audio_devices
        except Exception as e:
            return {
                'active_devices': 0,
                'input_active': False,
                'output_active': False,
                'sample_rate': 0,
                'active_clients': 0,
                'engine_running': False
            }
    
    def get_avaudiosession_state(self):
        """Check AVAudioSession-like state"""
        try:
            session_data = {
                'audio_hal_clients': 0,
                'coreaudio_active': False,
                'audio_server_connections': 0
            }
            
            # Simpler check - just count Slack's audio-related file descriptors
            output = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c -i audio", timeout=1)
            session_data['audio_hal_clients'] = int(output) if output.isdigit() else 0
            
            # Check for coreaudio connections
            output2 = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c coreaudio", timeout=1)
            audio_connections = int(output2) if output2.isdigit() else 0
            session_data['coreaudio_active'] = audio_connections > 0
            session_data['audio_server_connections'] = audio_connections
            
            return session_data
        except:
            return {
                'audio_hal_clients': 0,
                'coreaudio_active': False,
                'audio_server_connections': 0
            }
    
    def get_audio_power_assertions(self):
        """Check audio-related power assertions"""
        try:
            # Quick check for audio assertions
            output = self.run_command_safe("pmset -g assertions 2>/dev/null | grep -c -i audio", timeout=1)
            audio_count = int(output) if output.isdigit() else 0
            
            # Check if Slack has any assertions
            output2 = self.run_command_safe("pmset -g assertions 2>/dev/null | grep -c Slack", timeout=1)
            slack_assertions = int(output2) if output2.isdigit() else 0
            
            return {
                'audio_assertion': audio_count > 0,
                'prevent_sleep': slack_assertions > 0,
                'audio_related': audio_count,
                'slack_audio_count': slack_assertions
            }
        except:
            return {
                'audio_assertion': False,
                'prevent_sleep': False,
                'audio_related': 0,
                'slack_audio_count': 0
            }
    
    def get_audio_unit_hosting(self):
        """Check if Slack is hosting audio units"""
        try:
            # Simpler check
            output = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c AudioToolbox", timeout=1)
            au_count = int(output) if output.isdigit() else 0
            
            output2 = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c HAL", timeout=1)
            hal_count = int(output2) if output2.isdigit() else 0
            
            return {
                'audio_units': au_count,
                'audio_plugins': hal_count
            }
        except:
            return {'audio_units': 0, 'audio_plugins': 0}
    
    def get_quick_network_stats(self):
        """Get quick network stats without full lsof"""
        try:
            # Use netstat which is faster
            output = self.run_command_safe("netstat -an | grep -c Slack", timeout=1)
            return int(output) if output.isdigit() else 0
        except:
            return 0
    
    def get_aggregate_audio_state(self):
        """Get comprehensive audio state from multiple sources"""
        io_state = self.get_ioregistry_audio_state()
        session_state = self.get_avaudiosession_state()
        power_state = self.get_audio_power_assertions()
        au_state = self.get_audio_unit_hosting()
        network_connections = self.get_quick_network_stats()
        
        return {
            'io': io_state,
            'session': session_state,
            'power': power_state,
            'au': au_state,
            'network': network_connections,
            'timestamp': datetime.now()
        }
    
    def detect_huddle(self, state):
        """Detect huddle based on audio state changes"""
        score = 0
        reasons = []
        
        # IORegistry indicators
        if state['io']:
            if state['io']['active_clients'] > 0:
                score += 30
                reasons.append(f"Active audio clients: {state['io']['active_clients']}")
            
            if state['io']['engine_running']:
                score += 20
                reasons.append("Audio engine running")
            
            if state['io']['sample_rate'] > 0:
                score += 10
                reasons.append(f"Sample rate: {state['io']['sample_rate']}")
            
            if state['io']['input_active'] and state['io']['output_active']:
                score += 15
                reasons.append("Audio I/O active")
        
        # AVAudioSession-like indicators
        if state['session']:
            if state['session']['audio_hal_clients'] > 5:
                score += 25
                reasons.append(f"HAL clients: {state['session']['audio_hal_clients']}")
            
            if state['session']['coreaudio_active']:
                score += 20
                reasons.append("CoreAudio active")
            
            if state['session']['audio_server_connections'] > 3:
                score += 15
                reasons.append(f"Audio connections: {state['session']['audio_server_connections']}")
        
        # Power assertions
        if state['power']:
            if state['power']['audio_assertion']:
                score += 25
                reasons.append("Audio power assertion")
            
            if state['power']['slack_audio_count'] > 0:
                score += 20
                reasons.append(f"Slack assertions: {state['power']['slack_audio_count']}")
        
        # Audio Units
        if state['au']:
            if state['au']['audio_units'] > 0:
                score += 20
                reasons.append(f"Audio units: {state['au']['audio_units']}")
            
            if state['au']['audio_plugins'] > 0:
                score += 15
                reasons.append(f"HAL plugins: {state['au']['audio_plugins']}")
        
        # Network correlation (if we have baseline)
        if self.baseline_state.get('network') and state['network'] > 0:
            network_increase = state['network'] - self.baseline_state['network']
            if network_increase > 10:
                score += 10
                reasons.append(f"Network +{network_increase}")
        
        return {
            'score': score,
            'is_huddle': score >= 50,
            'reasons': reasons
        }
    
    def calibrate(self):
        """Establish baseline state"""
        print("📊 Calibrating baseline audio state...")
        
        samples = []
        for i in range(3):
            state = self.get_aggregate_audio_state()
            samples.append(state)
            print(f"\rCalibrating... {i+1}/3", end="", flush=True)
            time.sleep(2)
        
        # Use last sample as baseline
        self.baseline_state = samples[-1]
        
        print(f"\n✅ Baseline established:")
        if self.baseline_state['io']:
            print(f"   IORegistry: {self.baseline_state['io']['active_devices']} devices, "
                  f"{self.baseline_state['io']['active_clients']} clients")
        if self.baseline_state['session']:
            print(f"   Audio FDs: {self.baseline_state['session']['audio_hal_clients']}")
        print(f"   Network: {self.baseline_state['network']} connections\n")
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - IOKit & AVAudioSession Monitor")
        print("=" * 65)
        print("Monitoring IORegistry and audio session state")
        print("This uses IOKit framework data and system audio state\n")
        
        # Check sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("🔐 Requesting sudo access...")
            result = subprocess.run("sudo true", shell=True)
            if result.returncode != 0:
                print("⚠️  Running with limited functionality (no sudo)")
        
        # Calibrate
        self.calibrate()
        
        print("Monitoring for huddles...\n")
        
        last_state = False
        last_score = 0
        consecutive_detections = 0
        
        while True:
            try:
                state = self.get_aggregate_audio_state()
                result = self.detect_huddle(state)
                
                # Track consecutive detections for stability
                if result['is_huddle']:
                    consecutive_detections += 1
                else:
                    consecutive_detections = 0
                
                # State changes with hysteresis
                if consecutive_detections >= 2 and not last_state:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score: {result['score']}")
                    for reason in result['reasons']:
                        print(f"   • {reason}")
                    last_state = True
                
                elif consecutive_detections == 0 and last_state and result['score'] < 30:
                    print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Audio state returned to baseline")
                    last_state = False
                    # Update baseline
                    self.baseline_state = state
                
                # Status line
                if last_state:
                    status = "🎙️  IN HUDDLE"
                else:
                    status = "💤 No huddle"
                
                # Build info display
                info_parts = []
                
                if state['io']:
                    info_parts.append(f"IOClients:{state['io']['active_clients']}")
                    if state['io']['sample_rate'] > 0:
                        info_parts.append(f"SR:{state['io']['sample_rate']}")
                
                if state['session']:
                    info_parts.append(f"AudioFDs:{state['session']['audio_hal_clients']}")
                
                if state['au']:
                    total_au = state['au']['audio_units'] + state['au']['audio_plugins']
                    if total_au > 0:
                        info_parts.append(f"AU:{total_au}")
                
                if state['power'] and state['power']['slack_audio_count'] > 0:
                    info_parts.append(f"PWR:{state['power']['slack_audio_count']}")
                
                info_parts.append(f"Score:{result['score']}")
                
                print(f"\r{status} | {' | '.join(info_parts)} | {datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                last_score = result['score']
                time.sleep(3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError in main loop: {e}")
                time.sleep(3)
        
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    monitor = IOKitAudioMonitor()
    monitor.run()