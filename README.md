# Slack Huddle Detector

A macOS utility that detects when you're in a Slack huddle (voice/video call) by monitoring system audio state and power assertions.

## Features

- 🎯 **Accurate Detection**: Monitors multiple system indicators to reliably detect huddle start and end
- 🔄 **Auto-Calibration**: Learns your baseline state and adapts thresholds
- 📊 **Smart End Detection**: Three methods to ensure huddle end is properly detected
- 🚀 **Real-time Monitoring**: Updates every 3 seconds with current status
- 📈 **Dynamic Thresholds**: Adjusts detection based on peak scores and trends

## Requirements

- macOS (tested on macOS 14.x)
- Python 3.6+
- Slack desktop app
- sudo access (for audio system monitoring)

## Installation

1. Clone or download the repository:
```bash
git clone https://github.com/yourusername/slack-huddle-detection.git
cd slack-huddle-detection
```

2. No additional Python packages required - uses only standard library

## Usage

Run the detector with sudo privileges:

```bash
sudo python3 slack-huddle-detector-optimized.py
```

The detector will:
1. Request sudo access (needed for audio system monitoring)
2. Calibrate baseline (takes 6 seconds)
3. Begin monitoring for huddles
4. Display real-time status with indicators

### Output Example

```
🎧 Slack Huddle Detector - Optimized
==================================================
📊 Calibrating baseline (NOT in huddle)...
✅ Baseline score: 10

Monitoring for huddles...
  Start threshold: 35
  End: 70% drop from peak OR return to baseline+10

💤 No huddle | Score: 10→ | Monitoring... | Base:10 | 17:15:23

🟢 HUDDLE STARTED - 17:15:45
   Score: 65 (baseline: 10)
   • Audio power: 1
   • Slack assertions: 3
   • Audio units: 1

🎙️  IN HUDDLE | Score: 65→ | PWR:3 | AU:1 | Peak:65 | 17:15:48

🔴 HUDDLE ENDED - 17:18:32
   Score: 42 (peak was 65)
   New baseline: 42
```

## How It Works

The detector monitors several macOS system indicators:

### Primary Indicators
- **Power Assertions**: Slack creates audio power assertions during huddles
- **Audio Units**: AudioToolbox units are instantiated for audio processing
- **HAL Plugins**: Hardware Abstraction Layer plugins for audio I/O

### Secondary Indicators
- **Audio File Descriptors**: Open file handles to audio devices
- **IORegistry Clients**: Audio engine client connections
- **CoreAudio Connections**: Direct connections to CoreAudio daemon

### Detection Logic

**Huddle Start Detection:**
- Score exceeds baseline + 25 points (minimum 50)
- Requires 2 consecutive detections for confirmation

**Huddle End Detection (any of):**
- Score drops to 70% of peak huddle score
- Score returns within 10 points of baseline
- Strong downward trend detected

## Scoring System

| Indicator | Points | Description |
|-----------|--------|-------------|
| Audio Power Assertions | 25 | System-level audio power management |
| Slack Assertions | 20-60 | Slack-specific power assertions (capped) |
| Audio Units | 15-30 | Audio processing units (capped) |
| HAL Plugins | 10 | Hardware audio plugins |
| Audio FDs | 5 | File descriptors above baseline |
| IO Clients | 10 | IORegistry audio clients |
| CoreAudio | 10 | CoreAudio daemon connections |

## Status Indicators

- 🎙️ **IN HUDDLE**: Currently in a Slack huddle
- 💤 **No huddle**: Not in a huddle
- ↑↓→ **Trend arrows**: Score movement direction
- **PWR**: Power assertion count
- **AU**: Audio unit count
- **FD**: File descriptor count
- **Peak**: Highest score during current huddle
- **Base**: Current baseline score

## Troubleshooting

### "Sudo access required"
The detector needs sudo to access audio system information. This is safe and only reads system state.

### False Positives
- Ensure you're not in a huddle during calibration
- The detector adapts its baseline after each huddle
- May trigger briefly when testing audio in Slack settings

### Huddle End Not Detected
- The detector uses multiple methods to detect end
- If issues persist, try restarting the detector
- Score should drop significantly when huddle ends

### High Baseline Score
- Normal if you have other audio applications running
- The detector uses relative changes, not absolute values
- Baseline updates after each huddle for adaptation

## Technical Details

The detector uses macOS system frameworks to monitor audio state:
- IOKit/IORegistry for audio device state
- Power Management for assertions
- CoreAudio for audio session state
- File descriptors for audio device access

No network traffic monitoring or process memory inspection is performed.

## Other Scripts in Repository

- `slack-huddle-detector-optimized.py` - The main working detector (recommended)
- `slack-huddle-analyzer.py` - Network connection analyzer for debugging
- `slack-huddle-iokit-fixed.py` - IOKit-based detector (alternative)
- `slack-huddle-simple.py` - Simple network-based detector
- Various debug and analysis tools

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please test changes thoroughly on macOS with Slack desktop app.

## Acknowledgments

Developed through extensive testing and analysis of Slack's behavior on macOS during huddles.