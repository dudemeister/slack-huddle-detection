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
        
    def get_ioregistry_audio_state(self):
        """Query IORegistry for audio device state"""
        try:
            # Get audio device state from IORegistry
            cmd = "ioreg -r -c IOAudioDevice -k IOAudioDeviceTransportType 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            
            audio_devices = {
                'active_devices': 0,
                'input_active': False,
                'output_active': False,
                'sample_rate': 0,
                'io_state': {}
            }
            
            # Parse IORegistry output
            for line in result.stdout.split('\n'):
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
            
            # Get more detailed audio engine state
            engine_cmd = "ioreg -r -c IOAudioEngine 2>/dev/null | grep -E '(IOAudioEngineState|IOAudioEngineNumActiveUserClients|IOAudioStreamAvailable)'"
            engine_result = subprocess.run(engine_cmd, shell=True, capture_output=True, text=True, timeout=2)
            
            active_clients = 0
            engine_running = False
            for line in engine_result.stdout.split('\n'):
                if 'IOAudioEngineNumActiveUserClients' in line:
                    match = re.search(r'= (\d+)', line)
                    if match:
                        active_clients += int(match.group(1))
                if 'IOAudioEngineState' in line and '1' in line:
                    engine_running = True
            
            audio_devices['active_clients'] = active_clients
            audio_devices['engine_running'] = engine_running
            
            return audio_devices
        except Exception as e:
            return None
    
    def get_avaudiosession_state(self):
        """Check AVAudioSession-like state via system logs and processes"""
        try:
            session_data = {
                'audio_hal_clients': 0,
                'coreaudio_active': False,
                'audio_server_connections': 0
            }
            
            # Check how many clients are connected to CoreAudio HAL
            hal_cmd = "sudo lsof -c coreaudiod 2>/dev/null | grep -c Slack"
            hal_result = subprocess.run(hal_cmd, shell=True, capture_output=True, text=True, timeout=2)
            session_data['audio_hal_clients'] = int(hal_result.stdout.strip()) if hal_result.stdout.strip().isdigit() else 0
            
            # Check if Slack has active audio sessions via log
            # Look for recent audio session activations
            log_cmd = "log show --predicate 'subsystem == \"com.apple.coreaudio\" AND process == \"Slack\"' --last 10s --style compact 2>/dev/null | grep -c -i 'session'"
            log_result = subprocess.run(log_cmd, shell=True, capture_output=True, text=True, timeout=3)
            session_count = int(log_result.stdout.strip()) if log_result.stdout.strip().isdigit() else 0
            session_data['coreaudio_active'] = session_count > 0
            
            # Check audio server connections
            server_cmd = "sudo lsof -U 2>/dev/null | grep -E '(coreaudio|Slack)' | grep -c CONNECTED"
            server_result = subprocess.run(server_cmd, shell=True, capture_output=True, text=True, timeout=2)
            session_data['audio_server_connections'] = int(server_result.stdout.strip()) if server_result.stdout.strip().isdigit() else 0
            
            return session_data
        except:
            return None
    
    def get_audio_power_assertions(self):
        """Check audio-related power assertions"""
        try:
            # Check for audio power assertions
            cmd = "pmset -g assertions 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            
            assertions = {
                'audio_assertion': False,
                'prevent_sleep': False,
                'audio_related': 0
            }
            
            for line in result.stdout.split('\n'):
                if 'PreventUserIdleSystemSleep' in line and 'Slack' in line:
                    assertions['prevent_sleep'] = True
                if 'audio' in line.lower() or 'coreaudio' in line.lower():
                    assertions['audio_related'] += 1
                if 'com.apple.audio' in line:
                    assertions['audio_assertion'] = True
            
            # Also check assertion details
            detail_cmd = "pmset -g assertionslog 2>/dev/null | tail -50 | grep -c -i 'slack.*audio'"
            detail_result = subprocess.run(detail_cmd, shell=True, capture_output=True, text=True, timeout=2)
            slack_audio_assertions = int(detail_result.stdout.strip()) if detail_result.stdout.strip().isdigit() else 0
            assertions['slack_audio_count'] = slack_audio_assertions
            
            return assertions
        except:
            return None
    
    def get_audio_unit_hosting(self):
        """Check if Slack is hosting audio units"""
        try:
            # Check for audio unit hosting
            cmd = "sudo lsof -c Slack 2>/dev/null | grep -E '(AudioToolbox|AUHost|AudioComponent)' | wc -l"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            au_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
            
            # Check for audio plugins
            plugin_cmd = "sudo lsof -c Slack 2>/dev/null | grep -E '(HAL.plugin|audio.*plugin)' | wc -l"
            plugin_result = subprocess.run(plugin_cmd, shell=True, capture_output=True, text=True, timeout=2)
            plugin_count = int(plugin_result.stdout.strip()) if plugin_result.stdout.strip().isdigit() else 0
            
            return {
                'audio_units': au_count,
                'audio_plugins': plugin_count
            }
        except:
            return {'audio_units': 0, 'audio_plugins': 0}
    
    def get_aggregate_audio_state(self):
        """Get comprehensive audio state from multiple sources"""
        io_state = self.get_ioregistry_audio_state()
        session_state = self.get_avaudiosession_state()
        power_state = self.get_audio_power_assertions()
        au_state = self.get_audio_unit_hosting()
        
        # Also get basic network stats for correlation
        network_cmd = "sudo lsof -c Slack -i 2>/dev/null | wc -l"
        network_result = subprocess.run(network_cmd, shell=True, capture_output=True, text=True, timeout=2)
        network_connections = int(network_result.stdout.strip()) if network_result.stdout.strip().isdigit() else 0
        
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
        
        # AVAudioSession-like indicators
        if state['session']:
            if state['session']['audio_hal_clients'] > 5:
                score += 25
                reasons.append(f"HAL clients: {state['session']['audio_hal_clients']}")
            
            if state['session']['coreaudio_active']:
                score += 20
                reasons.append("CoreAudio session active")
            
            if state['session']['audio_server_connections'] > 10:
                score += 15
                reasons.append(f"Audio server connections: {state['session']['audio_server_connections']}")
        
        # Power assertions
        if state['power']:
            if state['power']['audio_assertion']:
                score += 25
                reasons.append("Audio power assertion")
            
            if state['power']['slack_audio_count'] > 0:
                score += 20
                reasons.append(f"Slack audio assertions: {state['power']['slack_audio_count']}")
        
        # Audio Units
        if state['au']:
            if state['au']['audio_units'] > 3:
                score += 20
                reasons.append(f"Audio units: {state['au']['audio_units']}")
            
            if state['au']['audio_plugins'] > 0:
                score += 15
                reasons.append(f"Audio plugins: {state['au']['audio_plugins']}")
        
        # Network correlation
        if self.baseline_state.get('network'):
            network_increase = state['network'] - self.baseline_state['network']
            if network_increase > 50:
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
            print(f"   HAL clients: {self.baseline_state['session']['audio_hal_clients']}")
        print(f"   Network connections: {self.baseline_state['network']}\n")
    
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
            subprocess.run("sudo true", shell=True)
        
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
                    info_parts.append(f"Clients:{state['io']['active_clients']}")
                    if state['io']['engine_running']:
                        info_parts.append("Engine:ON")
                
                if state['session']:
                    info_parts.append(f"HAL:{state['session']['audio_hal_clients']}")
                
                if state['au']:
                    if state['au']['audio_units'] > 0:
                        info_parts.append(f"AU:{state['au']['audio_units']}")
                
                info_parts.append(f"Net:{state['network']}")
                info_parts.append(f"Score:{result['score']}")
                
                print(f"\r{status} | {' | '.join(info_parts)} | {datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                last_score = result['score']
                time.sleep(3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(3)
        
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    monitor = IOKitAudioMonitor()
    monitor.run()