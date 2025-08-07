#!/usr/bin/env python3

import subprocess
import time
import sys
from datetime import datetime
from collections import deque

class SimpleSlackHuddleDetector:
    def __init__(self):
        self.baseline_udp = None
        self.baseline_tcp = None
        self.udp_history = deque(maxlen=10)
        self.tcp_history = deque(maxlen=10)
        self.in_huddle = False
        
    def get_slack_network_stats(self):
        """Get network connection counts for all Slack processes"""
        try:
            # Count UDP connections
            udp_cmd = "sudo lsof -c Slack -i UDP 2>/dev/null | grep -v COMMAND | wc -l"
            udp_result = subprocess.run(udp_cmd, shell=True, capture_output=True, text=True, timeout=2)
            udp_count = int(udp_result.stdout.strip()) if udp_result.stdout.strip().isdigit() else 0
            
            # Count TCP ESTABLISHED connections
            tcp_cmd = "sudo lsof -c Slack -i TCP 2>/dev/null | grep ESTABLISHED | wc -l"
            tcp_result = subprocess.run(tcp_cmd, shell=True, capture_output=True, text=True, timeout=2)
            tcp_count = int(tcp_result.stdout.strip()) if tcp_result.stdout.strip().isdigit() else 0
            
            # Get Renderer process CPU
            cpu_cmd = "ps aux | grep 'Slack Helper (Renderer)' | grep -v grep | awk '{print $3}'"
            cpu_result = subprocess.run(cpu_cmd, shell=True, capture_output=True, text=True, timeout=2)
            cpu = float(cpu_result.stdout.strip()) if cpu_result.stdout.strip() else 0.0
            
            return {
                'udp': udp_count,
                'tcp': tcp_count,
                'cpu': cpu
            }
        except Exception as e:
            return {'udp': 0, 'tcp': 0, 'cpu': 0.0}
    
    def calibrate(self):
        """Establish baseline when not in huddle"""
        print("📊 Calibrating baseline (make sure you're NOT in a huddle)...")
        
        samples = []
        for i in range(5):
            stats = self.get_slack_network_stats()
            samples.append(stats)
            print(f"\rCalibrating... {i+1}/5 (UDP: {stats['udp']}, TCP: {stats['tcp']})", end="", flush=True)
            time.sleep(2)
        
        # Calculate baseline as average
        self.baseline_udp = sum(s['udp'] for s in samples) / len(samples)
        self.baseline_tcp = sum(s['tcp'] for s in samples) / len(samples)
        
        print(f"\n✅ Baseline established:")
        print(f"   UDP: {self.baseline_udp:.0f} connections")
        print(f"   TCP: {self.baseline_tcp:.0f} connections\n")
    
    def detect_huddle(self, stats):
        """Detect huddle based on network changes"""
        # Add to history
        self.udp_history.append(stats['udp'])
        self.tcp_history.append(stats['tcp'])
        
        # Calculate averages over recent samples
        avg_udp = sum(self.udp_history) / len(self.udp_history) if self.udp_history else stats['udp']
        avg_tcp = sum(self.tcp_history) / len(self.tcp_history) if self.tcp_history else stats['tcp']
        
        # Detection logic
        udp_increase = avg_udp - self.baseline_udp
        tcp_increase = avg_tcp - self.baseline_tcp
        
        # Score-based detection
        score = 0
        reasons = []
        
        # Significant UDP increase (we saw +82 in your data)
        if udp_increase > 50:
            score += 40
            reasons.append(f"UDP +{udp_increase:.0f}")
        elif udp_increase > 30:
            score += 20
            reasons.append(f"UDP +{udp_increase:.0f}")
        
        # TCP increase (we saw +44 in your data)
        if tcp_increase > 20:
            score += 30
            reasons.append(f"TCP +{tcp_increase:.0f}")
        elif tcp_increase > 10:
            score += 15
            reasons.append(f"TCP +{tcp_increase:.0f}")
        
        # CPU spike
        if stats['cpu'] > 20:
            score += 20
            reasons.append(f"CPU {stats['cpu']:.0f}%")
        
        # Combined network increase
        total_increase = udp_increase + tcp_increase
        if total_increase > 100:
            score += 20
            reasons.append(f"Total network +{total_increase:.0f}")
        
        return {
            'score': score,
            'is_huddle': score >= 50,
            'reasons': reasons,
            'udp_delta': udp_increase,
            'tcp_delta': tcp_increase
        }
    
    def run(self):
        """Main monitoring loop"""
        print("🎧 Slack Huddle Detector - Simple Network Monitor")
        print("=" * 60)
        
        # Check sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("🔐 Requesting sudo access...")
            subprocess.run("sudo true", shell=True)
        
        # Calibrate
        self.calibrate()
        
        print("Monitoring for huddles...")
        print("(Network increases: UDP +50-80, TCP +20-40 indicate huddle)\n")
        
        last_state = False
        huddle_start_time = None
        
        while True:
            try:
                stats = self.get_slack_network_stats()
                result = self.detect_huddle(stats)
                
                # State change detection with stability requirement
                if result['is_huddle'] and not last_state:
                    # Require 2 consecutive detections
                    time.sleep(2)
                    stats2 = self.get_slack_network_stats()
                    result2 = self.detect_huddle(stats2)
                    
                    if result2['is_huddle']:
                        print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                        print(f"   Score: {result2['score']}")
                        for reason in result2['reasons']:
                            print(f"   • {reason}")
                        last_state = True
                        huddle_start_time = time.time()
                
                elif not result['is_huddle'] and last_state:
                    # Require huddle to have lasted at least 10 seconds
                    if huddle_start_time and (time.time() - huddle_start_time) > 10:
                        # And require consistent low score
                        time.sleep(2)
                        stats2 = self.get_slack_network_stats()
                        result2 = self.detect_huddle(stats2)
                        
                        if not result2['is_huddle']:
                            print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                            print(f"   Network returned to baseline")
                            last_state = False
                            
                            # Update baseline with post-huddle values
                            print("   Updating baseline...")
                            self.baseline_udp = stats2['udp']
                            self.baseline_tcp = stats2['tcp']
                
                # Status line
                if last_state:
                    status = "🎙️  IN HUDDLE"
                    duration = f" ({int(time.time() - huddle_start_time)}s)" if huddle_start_time else ""
                else:
                    status = "💤 No huddle"
                    duration = ""
                
                # Show deltas with color coding
                udp_delta_str = f"{result['udp_delta']:+.0f}" if result['udp_delta'] != 0 else "0"
                tcp_delta_str = f"{result['tcp_delta']:+.0f}" if result['tcp_delta'] != 0 else "0"
                
                print(f"\r{status}{duration} | "
                      f"UDP: {stats['udp']} ({udp_delta_str}) | "
                      f"TCP: {stats['tcp']} ({tcp_delta_str}) | "
                      f"CPU: {stats['cpu']:.0f}% | "
                      f"Score: {result['score']} | "
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
    detector = SimpleSlackHuddleDetector()
    detector.run()