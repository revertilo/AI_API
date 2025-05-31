# AI-Powered Transaction Analysis System

A system for analyzing Ethereum transaction reverts using AI to provide detailed explanations and recommendations.

## Installation

1. Clone the repository:
```bash
git clone git@github.com:ETHGlobal-Prague-2025/AI_API.git
cd AI_API
```

2. Create and activate virtual environment:
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Start the server:
```bash
python run.py
```

2. Open the web interface in your browser:
```
http://localhost:8000
```

3. Enter a transaction hash to analyze

## Features

- Transaction trace collection and analysis
- Smart contract source code mapping
- AI-powered revert analysis
- Web interface for real-time monitoring
- Detailed error explanations and recommendations

## Project Structure

- `run.py` - Main server script
- `process_traces.py` - Transaction trace processing
- `clean_trace.py` - Trace cleaning and optimization
- `analyze_revert.py` - AI analysis of transaction reverts

## Requirements

- Python 3.8+
- Google API key for Gemini AI
- Ethereum node access (currently using Chainnodes) 