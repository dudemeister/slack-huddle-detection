#!/usr/bin/env python3

import subprocess
import time
import sys
import json
from collections import defaultdict, Counter

def get_slack_pid():
    try:
        result = subprocess.run(['pgrep', 'Slack'], capture_output=True, text=True)
        pids = result.stdout.strip().split('\n')
        if pids and pids[0]:
            return pids[0]
    except:
        pass
    return None

def analyze_udp_connections(pid):
    """Get detailed UDP connection information"""
    try:
        result = subprocess.run(
            f'lsof -p {pid} -iUDP -P 2>/dev/null', 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        connections = []
        lines = result.stdout.strip().split('\n')[1:]  # Skip header
        
        for line in lines:
            if 'UDP' in line:
                parts = line.split()
                if len(parts) >= 9:
                    connection = {
                        'name': parts[0],
                        'pid': parts[1],
                        'user': parts[2],
                        'fd': parts[3],
                        'type': parts[4],
                        'device': parts[5] if len(parts) > 5 else '',
                        'size': parts[6] if len(parts) > 6 else '',
                        'node': parts[7] if len(parts) > 7 else '',
                        'connection': parts[8] if len(parts) > 8 else '',
                        'state': parts[9] if len(parts) > 9 else ''
                    }
                    
                    # Parse connection details
                    if '->' in connection['connection']:
                        local, remote = connection['connection'].split('->')
                        connection['local'] = local.strip()
                        connection['remote'] = remote.strip()
                    else:
                        connection['local'] = connection['connection']
                        connection['remote'] = ''
                    
                    connections.append(connection)
        
        return connections
    except Exception as e:
        print(f"Error analyzing UDP: {e}")
        return []

def analyze_tcp_connections(pid):
    """Get TCP connection information for comparison"""
    try:
        result = subprocess.run(
            f'lsof -p {pid} -iTCP -P 2>/dev/null | grep ESTABLISHED', 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        tcp_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
        return tcp_count
    except:
        return 0

def check_audio_devices(pid):
    """Check audio device usage with more detail"""
    try:
        result = subprocess.run(
            f'lsof -p {pid} 2>/dev/null | grep -E "(audio|coreaudio|AudioDevice)"', 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        audio_lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
        return len(audio_lines) > 0, audio_lines
    except:
        return False, []

def check_network_statistics(pid):
    """Get network statistics for the process"""
    try:
        result = subprocess.run(
            f'nettop -P -L 1 -p {pid} 2>/dev/null', 
            shell=True, 
            capture_output=True, 
            text=True
        )
        return result.stdout
    except:
        return ""

def analyze_patterns(connections):
    """Analyze UDP connection patterns"""
    analysis = {
        'total_count': len(connections),
        'unique_remote_hosts': set(),
        'unique_remote_ports': set(),
        'unique_local_ports': set(),
        'port_ranges': defaultdict(int),
        'common_patterns': []
    }
    
    for conn in connections:
        if 'remote' in conn and conn['remote']:
            # Extract host and port
            if ':' in conn['remote']:
                host, port = conn['remote'].rsplit(':', 1)
                analysis['unique_remote_hosts'].add(host)
                try:
                    port_num = int(port)
                    analysis['unique_remote_ports'].add(port_num)
                    
                    # Categorize port ranges
                    if 3478 <= port_num <= 3479:
                        analysis['port_ranges']['STUN/TURN'] += 1
                    elif 19302 <= port_num <= 19309:
                        analysis['port_ranges']['Google STUN'] += 1
                    elif port_num == 443:
                        analysis['port_ranges']['HTTPS/QUIC'] += 1
                    elif 1024 <= port_num <= 5000:
                        analysis['port_ranges']['Low Dynamic'] += 1
                    elif 5001 <= port_num <= 49151:
                        analysis['port_ranges']['High Dynamic'] += 1
                    else:
                        analysis['port_ranges']['Other'] += 1
                except:
                    pass
        
        if 'local' in conn and ':' in conn['local']:
            _, port = conn['local'].rsplit(':', 1)
            try:
                analysis['unique_local_ports'].add(int(port))
            except:
                pass
    
    # Identify patterns
    if analysis['port_ranges']['STUN/TURN'] > 0 or analysis['port_ranges']['Google STUN'] > 0:
        analysis['common_patterns'].append('WebRTC STUN/TURN detected')
    
    if len(analysis['unique_remote_hosts']) > 10:
        analysis['common_patterns'].append('Many unique remote hosts')
    
    if len(analysis['unique_local_ports']) > 20:
        analysis['common_patterns'].append('Many local ports in use')
    
    return analysis

def main():
    print("🔍 Slack Huddle Detector - DEBUG MODE")
    print("=" * 60)
    print("Collecting detailed connection data to identify patterns...")
    print()
    
    last_detailed_dump = 0
    dump_interval = 30  # Detailed dump every 30 seconds
    
    while True:
        pid = get_slack_pid()
        
        if not pid:
            print("\r❌ Slack not running", end="", flush=True)
            time.sleep(5)
            continue
        
        # Get all data
        udp_connections = analyze_udp_connections(pid)
        tcp_count = analyze_tcp_connections(pid)
        has_audio, audio_details = check_audio_devices(pid)
        patterns = analyze_patterns(udp_connections)
        
        # Current time
        current_time = time.time()
        
        # Status line
        print(f"\r📊 UDP: {patterns['total_count']} | TCP: {tcp_count} | "
              f"Audio: {'✓' if has_audio else '✗'} | "
              f"Unique Remotes: {len(patterns['unique_remote_hosts'])} | "
              f"Local Ports: {len(patterns['unique_local_ports'])} | "
              f"{time.strftime('%H:%M:%S')}", end="", flush=True)
        
        # Detailed dump periodically
        if current_time - last_detailed_dump > dump_interval:
            print("\n\n" + "="*60)
            print(f"DETAILED ANALYSIS - {time.strftime('%H:%M:%S')}")
            print("="*60)
            
            print(f"\n📈 CONNECTION SUMMARY:")
            print(f"  Total UDP connections: {patterns['total_count']}")
            print(f"  Total TCP connections: {tcp_count}")
            print(f"  Unique remote hosts: {len(patterns['unique_remote_hosts'])}")
            print(f"  Unique remote ports: {len(patterns['unique_remote_ports'])}")
            print(f"  Unique local ports: {len(patterns['unique_local_ports'])}")
            
            print(f"\n🔌 PORT RANGES:")
            for range_name, count in patterns['port_ranges'].items():
                print(f"  {range_name}: {count}")
            
            print(f"\n🎯 PATTERNS DETECTED:")
            if patterns['common_patterns']:
                for pattern in patterns['common_patterns']:
                    print(f"  • {pattern}")
            else:
                print("  • No specific patterns identified")
            
            print(f"\n🎧 AUDIO DEVICES:")
            if has_audio:
                print("  Audio devices detected:")
                for line in audio_details[:3]:  # Show first 3 lines
                    print(f"    {line[:100]}")
            else:
                print("  No audio devices detected")
            
            # Sample of connections
            print(f"\n🔗 SAMPLE UDP CONNECTIONS (first 10):")
            for i, conn in enumerate(udp_connections[:10]):
                local = conn.get('local', 'N/A')
                remote = conn.get('remote', 'N/A')
                print(f"  {i+1}. {local} -> {remote}")
            
            # Huddle likelihood assessment
            print(f"\n🎯 HUDDLE LIKELIHOOD ASSESSMENT:")
            huddle_score = 0
            reasons = []
            
            if has_audio:
                huddle_score += 40
                reasons.append("Audio devices active (+40)")
            
            if patterns['port_ranges'].get('STUN/TURN', 0) > 0:
                huddle_score += 30
                reasons.append(f"STUN/TURN ports detected (+30)")
            
            if patterns['port_ranges'].get('Google STUN', 0) > 0:
                huddle_score += 20
                reasons.append(f"Google STUN ports detected (+20)")
            
            if patterns['total_count'] > 100:
                huddle_score -= 20
                reasons.append(f"Too many UDP connections, likely background traffic (-20)")
            elif patterns['total_count'] > 10 and patterns['total_count'] < 50:
                huddle_score += 20
                reasons.append(f"Reasonable UDP count for WebRTC (+20)")
            
            if len(patterns['unique_remote_hosts']) < 5 and patterns['total_count'] > 5:
                huddle_score += 15
                reasons.append(f"Few unique hosts with multiple connections (+15)")
            
            print(f"  Score: {huddle_score}/100")
            for reason in reasons:
                print(f"    • {reason}")
            
            if huddle_score >= 50:
                print(f"  ⚠️  LIKELY IN HUDDLE")
            else:
                print(f"  ✅ LIKELY NOT IN HUDDLE")
            
            print("="*60 + "\n")
            last_detailed_dump = current_time
        
        time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Debug session ended")
        sys.exit(0)