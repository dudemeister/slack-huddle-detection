#!/usr/bin/env python3

import subprocess
import time
import sys
import os
from datetime import datetime
import ctypes
import ctypes.util
from collections import defaultdict

class MacOSMemoryAnalyzer:
    def __init__(self):
        self.huddle_state = False
        self.setup_dtrace_probes()
        
    def setup_dtrace_probes(self):
        """Setup DTrace probes for Slack monitoring"""
        self.dtrace_scripts = {
            'syscalls': '''
                syscall::*audio*:entry /execname == "Slack"/ { @audio[probefunc] = count(); }
                syscall::*send*:entry /execname == "Slack"/ { @network[probefunc] = count(); }
                profile:::tick-1sec { printa(@audio); printa(@network); clear(@audio); clear(@network); }
            ''',
            'malloc': '''
                pid$target::malloc:entry { @malloc_size = quantize(arg0); }
                profile:::tick-1sec { printa(@malloc_size); clear(@malloc_size); }
            '''
        }
    
    def get_process_info_via_vmmap(self, pid):
        """Use vmmap to analyze process memory regions"""
        try:
            # Get memory map
            cmd = f"sudo vmmap {pid} 2>/dev/null | grep -E '(MALLOC|mapped file|__TEXT|__DATA)'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            memory_stats = {
                'malloc_regions': 0,
                'malloc_size': 0,
                'mapped_files': 0,
                'text_size': 0,
                'data_size': 0
            }
            
            for line in result.stdout.strip().split('\n'):
                if 'MALLOC' in line:
                    memory_stats['malloc_regions'] += 1
                    # Extract size if available
                    parts = line.split()
                    for part in parts:
                        if 'K' in part or 'M' in part:
                            try:
                                size = part.replace('K', '').replace('M', '')
                                memory_stats['malloc_size'] += float(size)
                            except:
                                pass
                elif 'mapped file' in line:
                    memory_stats['mapped_files'] += 1
                elif '__TEXT' in line:
                    memory_stats['text_size'] += 1
                elif '__DATA' in line:
                    memory_stats['data_size'] += 1
            
            return memory_stats
        except:
            return None
    
    def analyze_with_dtrace(self, pid):
        """Use DTrace to monitor Slack system calls"""
        try:
            # Quick DTrace probe for audio and network activity
            dtrace_cmd = f"""sudo dtrace -qn '
                syscall::send*:entry /pid == {pid}/ {{ @sends = count(); }}
                syscall::recv*:entry /pid == {pid}/ {{ @recvs = count(); }}
                syscall::*audio*:entry /pid == {pid}/ {{ @audio = count(); }}
                syscall::*ioctl:entry /pid == {pid}/ {{ @ioctl = count(); }}
                profile:::tick-1sec {{ 
                    printa("sends: %@d\\n", @sends);
                    printa("recvs: %@d\\n", @recvs);
                    printa("audio: %@d\\n", @audio);
                    printa("ioctl: %@d\\n", @ioctl);
                    exit(0);
                }}
            ' 2>/dev/null"""
            
            result = subprocess.run(dtrace_cmd, shell=True, capture_output=True, text=True, timeout=2)
            
            stats = {
                'sends': 0,
                'recvs': 0,
                'audio': 0,
                'ioctl': 0
            }
            
            for line in result.stdout.strip().split('\n'):
                if 'sends:' in line:
                    stats['sends'] = int(line.split(':')[1].strip())
                elif 'recvs:' in line:
                    stats['recvs'] = int(line.split(':')[1].strip())
                elif 'audio:' in line:
                    stats['audio'] = int(line.split(':')[1].strip())
                elif 'ioctl:' in line:
                    stats['ioctl'] = int(line.split(':')[1].strip())
            
            return stats
        except:
            return None
    
    def check_mach_ports(self, pid):
        """Check Mach ports for the process"""
        try:
            # Use lsmp to list Mach ports
            cmd = f"sudo lsmp -p {pid} 2>/dev/null | wc -l"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            port_count = int(result.stdout.strip())
            
            # Check for specific port names related to audio/video
            detail_cmd = f"sudo lsmp -p {pid} 2>/dev/null | grep -iE '(audio|video|media|coreaudio|hal)'"
            detail_result = subprocess.run(detail_cmd, shell=True, capture_output=True, text=True)
            
            media_ports = len(detail_result.stdout.strip().split('\n')) if detail_result.stdout.strip() else 0
            
            return {
                'total_ports': port_count,
                'media_ports': media_ports
            }
        except:
            return {'total_ports': 0, 'media_ports': 0}
    
    def check_file_descriptors(self, pid):
        """Check open file descriptors for audio/video devices"""
        try:
            # Check for audio device files
            cmd = f"sudo lsof -p {pid} 2>/dev/null | grep -iE '(/dev/audio|coreaudio|hal_plugin|audiodevice|com.apple.audio)' | wc -l"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            audio_fds = int(result.stdout.strip())
            
            # Check for shared memory segments (used for media)
            shm_cmd = f"sudo lsof -p {pid} 2>/dev/null | grep -E '(PSXSHM|/dev/shm)' | wc -l"
            shm_result = subprocess.run(shm_cmd, shell=True, capture_output=True, text=True)
            shm_count = int(shm_result.stdout.strip())
            
            return {
                'audio_fds': audio_fds,
                'shared_memory': shm_count
            }
        except:
            return {'audio_fds': 0, 'shared_memory': 0}
    
    def sample_process(self, pid):
        """Use sample command to get process activity snapshot"""
        try:
            # Quick sample of process activity
            cmd = f"sudo sample {pid} 1 -mayDie 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            
            # Look for huddle-related symbols
            huddle_indicators = [
                'WebRTC', 'RTCPeerConnection', 'MediaStream',
                'AudioDevice', 'audio', 'opus', 'vpx',
                'Huddle', 'Call', 'Voice', 'Video'
            ]
            
            sample_score = 0
            found_indicators = []
            
            for indicator in huddle_indicators:
                if indicator.lower() in result.stdout.lower():
                    sample_score += 10
                    found_indicators.append(indicator)
            
            return {
                'score': sample_score,
                'indicators': found_indicators
            }
        except:
            return {'score': 0, 'indicators': []}
    
    def get_all_slack_pids(self):
        """Get all Slack process PIDs"""
        try:
            cmd = "pgrep -f Slack"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            
            # Identify process types
            pid_info = {}
            for pid in pids:
                name_cmd = f"ps -p {pid} -o comm="
                name_result = subprocess.run(name_cmd, shell=True, capture_output=True, text=True)
                name = name_result.stdout.strip()
                
                if 'Renderer' in name:
                    pid_info[pid] = 'Renderer'
                elif 'GPU' in name:
                    pid_info[pid] = 'GPU'
                elif 'Slack' in name:
                    pid_info[pid] = 'Main'
                else:
                    pid_info[pid] = 'Helper'
            
            return pid_info
        except:
            return {}
    
    def detect_huddle(self):
        """Detect huddle using multiple macOS-specific methods"""
        pids = self.get_all_slack_pids()
        
        detection_data = {
            'score': 0,
            'reasons': [],
            'details': {}
        }
        
        for pid, process_type in pids.items():
            # Skip GPU process as it's less relevant
            if process_type == 'GPU':
                continue
            
            # Collect data from various sources
            memory_stats = self.get_process_info_via_vmmap(pid)
            mach_ports = self.check_mach_ports(pid)
            file_descriptors = self.check_file_descriptors(pid)
            sample_data = self.sample_process(pid) if process_type == 'Renderer' else {'score': 0}
            dtrace_stats = self.analyze_with_dtrace(pid) if process_type == 'Renderer' else None
            
            detection_data['details'][process_type] = {
                'memory': memory_stats,
                'mach_ports': mach_ports,
                'fds': file_descriptors,
                'sample': sample_data,
                'dtrace': dtrace_stats
            }
            
            # Score based on findings
            if mach_ports['media_ports'] > 5:
                detection_data['score'] += 30
                detection_data['reasons'].append(f"{process_type}: {mach_ports['media_ports']} media ports")
            
            if file_descriptors['audio_fds'] > 0:
                detection_data['score'] += 20
                detection_data['reasons'].append(f"{process_type}: Audio FDs active")
            
            if file_descriptors['shared_memory'] > 10:
                detection_data['score'] += 15
                detection_data['reasons'].append(f"{process_type}: High shared memory usage")
            
            if sample_data['score'] > 20:
                detection_data['score'] += sample_data['score']
                detection_data['reasons'].append(f"{process_type}: {', '.join(sample_data['indicators'][:3])}")
            
            if dtrace_stats and dtrace_stats['sends'] > 100:
                detection_data['score'] += 20
                detection_data['reasons'].append(f"{process_type}: High network activity")
        
        detection_data['is_huddle'] = detection_data['score'] >= 50
        
        return detection_data
    
    def run(self):
        """Main monitoring loop"""
        print("🔬 Slack Huddle Detector - macOS Memory/Process Analysis")
        print("=" * 70)
        print("Using: vmmap, DTrace, Mach ports, process sampling")
        print("Note: This requires sudo access and may trigger security prompts\n")
        
        # Check for sudo
        result = subprocess.run("sudo -n true 2>/dev/null", shell=True)
        if result.returncode != 0:
            print("🔐 Requesting sudo access...")
            subprocess.run("sudo true", shell=True)
        
        print("Monitoring for huddles...\n")
        
        last_state = False
        last_score = 0
        
        while True:
            try:
                result = self.detect_huddle()
                
                # State change detection with hysteresis
                if result['is_huddle'] and not last_state:
                    print(f"\n🟢 HUDDLE STARTED - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"   Score: {result['score']}")
                    for reason in result['reasons']:
                        print(f"   • {reason}")
                    last_state = True
                
                elif not result['is_huddle'] and last_state:
                    # Require score to drop significantly
                    if result['score'] < 30:
                        print(f"\n🔴 HUDDLE ENDED - {datetime.now().strftime('%H:%M:%S')}")
                        last_state = False
                
                # Status line
                if result['is_huddle']:
                    status = "🎙️  IN HUDDLE"
                else:
                    status = "💤 No huddle"
                
                # Show key metrics
                renderer_details = result['details'].get('Renderer', {})
                mach_info = renderer_details.get('mach_ports', {})
                fd_info = renderer_details.get('fds', {})
                
                print(f"\r{status} | Score: {result['score']:3d} | "
                      f"Media Ports: {mach_info.get('media_ports', 0)} | "
                      f"Audio FDs: {fd_info.get('audio_fds', 0)} | "
                      f"{datetime.now().strftime('%H:%M:%S')}", 
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
    analyzer = MacOSMemoryAnalyzer()
    analyzer.run()