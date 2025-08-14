#!/usr/bin/env python3

import subprocess
import time
import sys
import os
import json
from datetime import datetime
from collections import deque
import re

class OptimizedSlackHuddleDetector:
    def __init__(self):
        self.baseline_score = 0
        self.in_huddle = False
        self.score_history = deque(maxlen=10)
        self.huddle_peak_score = 0
        import getpass
        import os
        # Get the real user even when running with sudo
        username = os.environ.get('SUDO_USER') or getpass.getuser()
        self.status_file_path = f"/tmp/huddle-status-{username}.json"
        
    def run_command_safe(self, cmd, timeout=1):
        """Run command with timeout and error handling"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip()
        except:
            return ""
    
    def get_audio_state(self):
        """Get audio-related state indicators"""
        state = {
            'audio_fds': 0,
            'audio_units': 0,
            'hal_plugins': 0,
            'power_assertions': 0,
            'slack_assertions': 0,
            'ioregistry_clients': 0,
            'coreaudio_connections': 0
        }
        
        # Audio file descriptors
        output = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c -i audio", timeout=1)
        state['audio_fds'] = int(output) if output.isdigit() else 0
        
        # Audio units
        output = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c AudioToolbox", timeout=1)
        state['audio_units'] = int(output) if output.isdigit() else 0
        
        # HAL plugins
        output = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c HAL", timeout=1)
        state['hal_plugins'] = int(output) if output.isdigit() else 0
        
        # Power assertions
        output = self.run_command_safe("pmset -g assertions 2>/dev/null | grep -c -i audio", timeout=1)
        state['power_assertions'] = int(output) if output.isdigit() else 0
        
        # Slack-specific assertions
        output = self.run_command_safe("pmset -g assertions 2>/dev/null | grep -c Slack", timeout=1)
        state['slack_assertions'] = int(output) if output.isdigit() else 0
        
        # IORegistry audio clients
        output = self.run_command_safe("ioreg -r -c IOAudioEngine 2>/dev/null | grep -c IOAudioEngine", timeout=2)
        state['ioregistry_clients'] = int(output) if output.isdigit() else 0
        
        # CoreAudio connections
        output = self.run_command_safe("sudo lsof -n -P -c Slack 2>/dev/null | grep -c coreaudio", timeout=1)
        state['coreaudio_connections'] = int(output) if output.isdigit() else 0
        
        return state
    
    def calculate_score(self, state):
        """Calculate huddle score from state"""
        score = 0
        reasons = []
        
        # Strong indicators
        if state['power_assertions'] > 0:
            score += 25
            reasons.append(f"Audio power: {state['power_assertions']}")
        
        if state['slack_assertions'] > 0:
            score += 20 * min(state['slack_assertions'], 3)  # Cap at 60
            reasons.append(f"Slack assertions: {state['slack_assertions']}")
        
        # Medium indicators
        if state['audio_units'] > 0:
            score += 15 * min(state['audio_units'], 2)  # Cap at 30
            reasons.append(f"Audio units: {state['audio_units']}")
        
        if state['hal_plugins'] > 0:
            score += 10
            reasons.append(f"HAL plugins: {state['hal_plugins']}")
        
        # Weak indicators
        if state['audio_fds'] > 3:  # Above baseline
            score += 5
            reasons.append(f"Audio FDs: {state['audio_fds']}")
        
        if state['ioregistry_clients'] > 0:
            score += 10
            reasons.append(f"IO clients: {state['ioregistry_clients']}")
        
        if state['coreaudio_connections'] > 0:
            score += 10
            reasons.append(f"CoreAudio: {state['coreaudio_connections']}")
        
        return score, reasons
    
    def detect_huddle_change(self, current_score):
        """Detect huddle state changes with smart thresholds"""
        # Add to history
        self.score_history.append(current_score)
        
        # Calculate trend
        if len(self.score_history) >= 3:
            recent_avg = sum(list(self.score_history)[-3:]) / 3
            older_avg = sum(list(self.score_history)[-6:-3]) / 3 if len(self.score_history) >= 6 else recent_avg
            trend = recent_avg - older_avg
        else:
            trend = 0
        
        # Dynamic thresholds based on baseline
        start_threshold = max(50, self.baseline_score + 25)
        
        # End detection: either significant drop from peak or return near baseline
        if self.in_huddle:
            # End if score drops to 70% of peak score or below
            end_by_ratio = current_score < (self.huddle_peak_score * 0.7)
            # Or if score is within 10 points of baseline
            end_by_baseline = current_score <= (self.baseline_score + 10)
            # Or if there's a strong downward trend
            end_by_trend = trend < -10 and current_score < 50
            
            should_end = end_by_ratio or end_by_baseline or end_by_trend
        else:
            should_end = False
        
        # Start detection
        should_start = not self.in_huddle and current_score >= start_threshold and trend >= 0
        
        return should_start, should_end, trend
    
    def write_status_file(self, current_score, state, trend):
        """Write current status to JSON file for menubar app"""
        try:
            trend_str = "↑" if trend > 5 else "↓" if trend < -5 else "→"
            
            status_data = {
                "inHuddle": self.in_huddle,
                "score": current_score,
                "baseline": self.baseline_score,
                "peakScore": self.huddle_peak_score if self.in_huddle else 0,
                "trend": trend_str,
                "timestamp": datetime.now().strftime('%H:%M:%S'),
                "metrics": {
                    "slackAssertions": state['slack_assertions'],
                    "audioUnits": state['audio_units'],
                    "audioFds": state['audio_fds'],
                    "powerAssertions": state['power_assertions']
                }
            }
            
            with open(self.status_file_path, 'w') as f:
                json.dump(status_data, f, indent=2)
            
            # Fix permissions so the user can read the file
            os.chmod(self.status_file_path, 0o644)
            
        except Exception as e:
            pass  # Don't let file writing errors break the detector
    
    def calibrate(self):
        """Establish baseline"""
        print("📊 Calibrating baseline (NOT in huddle)...")
        
        scores = []
        for i in range(3):
            state = self.get_audio_state()
            score, _ = self.calculate_score(state)
            scores.append(score)
            print(f"\rCalibrating... {i+1}/3 (Score: {score})", end="", flush=True)
            time.sleep(2)
        
        self.baseline_score = sum(scores) / len(scores)
        print(f"\n✅ Baseline score: {self.baseline_score:.1f}\n")
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - Optimized")
        print("=" * 50)
        print("Smart thresholds for accurate start/end detection\n")
        
        # Check sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("🔐 Requesting sudo access...")
            subprocess.run("sudo true", shell=True)
        
        # Calibrate
        self.calibrate()
        
        print(f"Monitoring for huddles...")
        print(f"  Start threshold: {max(50, self.baseline_score + 25)}")
        print(f"  End: 70% drop from peak OR return to baseline+10\n")
        
        consecutive_starts = 0
        consecutive_ends = 0
        
        while True:
            try:
                state = self.get_audio_state()
                score, reasons = self.calculate_score(state)
                
                # Detect changes
                should_start, should_end, trend = self.detect_huddle_change(score)
                
                # Handle state transitions with confirmation
                if should_start:
                    consecutive_starts += 1
                    consecutive_ends = 0
                    if consecutive_starts >= 2:  # Require 2 consecutive
                        print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                        print(f"   Score: {score} (baseline: {self.baseline_score:.0f})")
                        for reason in reasons:
                            print(f"   • {reason}")
                        self.in_huddle = True
                        self.huddle_peak_score = score
                        consecutive_starts = 0
                elif should_end:
                    consecutive_ends += 1
                    consecutive_starts = 0
                    if consecutive_ends >= 2:  # Require 2 consecutive
                        print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                        print(f"   Score: {score} (peak was {self.huddle_peak_score})")
                        self.in_huddle = False
                        self.huddle_peak_score = 0
                        consecutive_ends = 0
                        # Update baseline to current score
                        self.baseline_score = score
                        print(f"   New baseline: {self.baseline_score}")
                else:
                    consecutive_starts = 0
                    consecutive_ends = 0
                
                # Update peak score during huddle
                if self.in_huddle and score > self.huddle_peak_score:
                    self.huddle_peak_score = score
                
                # Write status file for menubar app
                self.write_status_file(score, state, trend)
                
                # Status line
                if self.in_huddle:
                    status = "🎙️  IN HUDDLE"
                    extra = f" Peak:{self.huddle_peak_score}"
                else:
                    status = "💤 No huddle"
                    extra = f" Base:{self.baseline_score:.0f}"
                
                # Trend indicator
                trend_str = "↑" if trend > 5 else "↓" if trend < -5 else "→"
                
                # Key metrics
                metrics = []
                if state['slack_assertions'] > 0:
                    metrics.append(f"PWR:{state['slack_assertions']}")
                if state['audio_units'] > 0:
                    metrics.append(f"AU:{state['audio_units']}")
                if state['audio_fds'] > 3:
                    metrics.append(f"FD:{state['audio_fds']}")
                
                print(f"\r{status} | Score:{score:3d}{trend_str} | "
                      f"{' | '.join(metrics) if metrics else 'Monitoring...'} | "
                      f"{extra} | {datetime.now().strftime('%H:%M:%S')}", 
                      end="", flush=True)
                
                time.sleep(3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(3)
        
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    detector = OptimizedSlackHuddleDetector()
    detector.run()