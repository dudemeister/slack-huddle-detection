#!/usr/bin/env python3

import subprocess
import time
import sys

def get_slack_pid():
    try:
        result = subprocess.run(['pgrep', 'Slack'], capture_output=True, text=True)
        pids = result.stdout.strip().split('\n')
        if pids and pids[0]:
            return pids[0]
    except:
        pass
    return None

def check_huddle_active(pid):
    try:
        # Check for UDP connections (WebRTC indicator)
        result = subprocess.run(
            f'lsof -p {pid} -iUDP -P 2>/dev/null', 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        udp_lines = result.stdout.strip().split('\n')
        udp_connections = [line for line in udp_lines if 'UDP' in line]
        
        # Check for audio device usage
        audio_result = subprocess.run(
            f'lsof -p {pid} 2>/dev/null | grep -i "audio"', 
            shell=True, 
            capture_output=True, 
            text=True
        )
        has_audio = bool(audio_result.stdout.strip())
        
        # Huddle is likely active if:
        # - Multiple UDP connections (>2)
        # - Or has audio devices open
        is_huddle = len(udp_connections) > 2 or has_audio
        
        return is_huddle, len(udp_connections), has_audio
        
    except Exception as e:
        return False, 0, False

def main():
    print("🎧 Slack Huddle Detector")
    print("=" * 40)
    
    huddle_state = False
    
    while True:
        pid = get_slack_pid()
        
        if not pid:
            print("\r❌ Slack not running", end="", flush=True)
        else:
            is_huddle, udp_count, has_audio = check_huddle_active(pid)
            
            # State change detection
            if is_huddle and not huddle_state:
                print(f"\n🟢 HUDDLE STARTED - {time.strftime('%H:%M:%S')}")
                print(f"   UDP connections: {udp_count}, Audio: {'Yes' if has_audio else 'No'}")
                huddle_state = True
            elif not is_huddle and huddle_state:
                print(f"\n🔴 HUDDLE ENDED - {time.strftime('%H:%M:%S')}")
                huddle_state = False
            
            # Status line
            status = "🎙️  IN HUDDLE" if is_huddle else "💤 No huddle"
            print(f"\r{status} | UDP: {udp_count} | Audio: {'✓' if has_audio else '✗'} | {time.strftime('%H:%M:%S')}", end="", flush=True)
        
        time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Stopped monitoring")
        sys.exit(0)