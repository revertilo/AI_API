import json
import google.generativeai as genai
import os
from dotenv import load_dotenv
import requests
import time
import traceback
import sys

# Load environment variables
load_dotenv()

# Configure API key from environment variable
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

def update_trace_with_source_map(trace, source_map):
    """Обновляет trace данными из source_map по pc"""
    # Only update operations around the revert
    revert_index = None
    for i, op in enumerate(trace):
        if op['op'] == 'REVERT':
            revert_index = i
            break
            
    if revert_index is not None:
        # Update only 10 operations before and after revert
        start = max(0, revert_index - 10)
        end = min(len(trace), revert_index + 10)
        for i in range(start, end):
            op = trace[i]
            pc = op.get('pc')
            if pc is not None and pc in source_map:
                op['source_code'] = source_map[pc]['code']
                op['context_code'] = source_map[pc]['context_code']
    return trace

def get_revert_info():
    """
    Получает информацию о реверте из cleaned_trace.json
    """
    try:
        print("Reading cleaned_trace.json...")
        sys.stdout.flush()
        with open('cleaned_trace.json', 'r') as f:
            trace_data = json.load(f)
        print(f"Loaded {len(trace_data)} operations from trace")
        sys.stdout.flush()
            
        # Находим последний REVERT
        print("Looking for REVERT operation...")
        sys.stdout.flush()
        revert_op = None
        for op in reversed(trace_data):
            if op['op'] == 'REVERT':
                revert_op = op
                print("Found REVERT operation")
                sys.stdout.flush()
                break
                
        if not revert_op:
            print("No REVERT operation found in trace")
            sys.stdout.flush()
            return None
            
        # Находим CALL, который привел к REVERT
        print("Looking for CALL operation...")
        sys.stdout.flush()
        call_op = None
        for op in reversed(trace_data):
            if op['op'] == 'CALL':
                call_op = op
                print("Found CALL operation")
                sys.stdout.flush()
                break
                
        if not call_op:
            print("No matching CALL operation found for REVERT")
            sys.stdout.flush()
            return None
            
        print("Successfully extracted revert info")
        sys.stdout.flush()
        return {
            'revert': revert_op,
            'call': call_op,
            'trace': trace_data
        }
    except Exception as e:
        print(f"Error getting revert info: {str(e)}")
        sys.stdout.flush()
        traceback.print_exc()
        sys.stdout.flush()
        return None

def get_contract_info(contract_address):
    """
    Получает информацию о контракте через API
    """
    try:
        print(f"Fetching contract info for {contract_address}...")
        sys.stdout.flush()
        
        response = requests.post(
            'http://205.196.81.76:5000/verify',
            headers={'Content-Type': 'application/json'},
            json={'address': contract_address},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print("Successfully fetched contract info")
            sys.stdout.flush()
            return data
        else:
            print(f"Failed to fetch contract info: {response.status_code}")
            sys.stdout.flush()
            return {'source': ''}
            
    except Exception as e:
        print(f"Error getting contract info: {str(e)}")
        sys.stdout.flush()
        traceback.print_exc()
        sys.stdout.flush()
        return {'source': ''}

def analyze_with_ai(tx_hash, contract_address, function_signature, revert_info, contract_info):
    """
    Анализирует реверт с помощью AI
    """
    try:
        # Подготавливаем данные
        source_code = contract_info.get('sources', '')
        cleaned_trace = json.dumps(revert_info['trace'], indent=2)
        
        # Формируем промпт
        prompt = f"""You are an AI assistant specialized in analyzing Ethereum transaction traces and debugging smart contract issues. Your task is to analyze the transaction trace and provide insights about what went wrong. The result will be shown to the user in a web interface.

Transaction Hash: {tx_hash}
Contract Address: {contract_address}
Function Signature: {function_signature}

The trace data is provided in cleaned_trace.json and contains the following information:
1. Operation codes (opcodes) executed during the transaction
2. Arguments for each operation
3. Gas usage and costs
4. Memory and stack state
5. Call data and return values

Source Code Context:
```solidity
{source_code}
```

Your analysis should include:
1. Identify the sequence of operations that led to the REVERT
2. Explain what each operation does and how it contributed to the failure
3. If there's a revert message, decode and explain it
4. Suggest potential fixes or improvements

Don't ask questions and don't ask user to provide more information, just provide the analysis.
Don't include trace statistics, just the analysis.

Please format your response in a clear, structured way:
1. Summary of the issue
2. Detailed analysis of the trace
3. Root cause
4. Recommendations

Focus on being precise and technical, but also explain concepts in a way that's understandable to developers with basic Ethereum knowledge. Note that PC (program counter) is the number of bytecode instruction in the contract.

Trace Data:
{cleaned_trace}"""

        # Сохраняем промпт в файл
        with open('prompt.txt', 'w') as f:
            f.write(prompt)
        
        # Generate response with Gemini
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        return response.text
        
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        traceback.print_exc()
        return f"Error analyzing revert: {str(e)}"

def main():
    try:
        print("\n=== Starting Analysis ===")
        sys.stdout.flush()
        
        # Получаем параметры из аргументов командной строки
        if len(sys.argv) != 2:
            print("Usage: python3 analyze_revert.py <tx_hash or params_json>")
            sys.stdout.flush()
            sys.exit(1)
            
        input_data = sys.argv[1]
        print(f"\nAnalyzing input: {input_data}")
        sys.stdout.flush()
        
        # Определяем, это хэш транзакции или параметры эмуляции
        if input_data == 'emulate':  # Специальный случай для эмуляции
            tx_hash = "emulation"
            print("Processing emulation")
            sys.stdout.flush()
        elif input_data.startswith('0x') and len(input_data) == 66:  # Это хэш транзакции
            tx_hash = input_data
            print(f"Processing real transaction: {tx_hash}")
            sys.stdout.flush()
        
        # Получаем информацию о реверте
        print("\nGetting revert info...")
        sys.stdout.flush()
        revert_info = get_revert_info()
        if not revert_info:
            print("Error: Could not get revert info")
            sys.stdout.flush()
            sys.exit(1)
            
        # Получаем информацию о контракте
        print("\nGetting contract info...")
        sys.stdout.flush()
        contract_address = revert_info['call']['args']['to']
        print(f"Contract address: {contract_address}")
        sys.stdout.flush()
        contract_info = get_contract_info(contract_address)
        
        # Получаем сигнатуру функции из input_data
        print("\nGetting function signature...")
        sys.stdout.flush()
        input_data = revert_info['call']['args']['input_data']
        function_signature = input_data[:10] if input_data else "0x"
        print(f"Function signature: {function_signature}")
        sys.stdout.flush()
        
        # Анализируем с помощью AI
        print("\nStarting AI analysis...")
        sys.stdout.flush()
        analysis = analyze_with_ai(tx_hash, contract_address, function_signature, revert_info, contract_info)
        if not analysis:
            print("Error: AI analysis failed")
            sys.stdout.flush()
            sys.exit(1)
            
        # Сохраняем результат
        print("\nSaving analysis result...")
        sys.stdout.flush()
        with open('revert_analysis.txt', 'w') as f:
            f.write(analysis)
            
        print(analysis)
        sys.stdout.flush()
        print("\n=== Analysis Complete ===")
        sys.stdout.flush()
        
    except Exception as e:
        print(f"\nError in main: {str(e)}")
        sys.stdout.flush()
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)

if __name__ == "__main__":
    main() 