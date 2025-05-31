import json
import google.generativeai as genai
import os
from dotenv import load_dotenv
import requests
import time

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
    """Получает информацию о реверте из cleaned_trace.json"""
    try:
        with open('cleaned_trace.json', 'r') as f:
            trace = json.load(f)
            
        # Находим последний REVERT
        revert_op = None
        for op in trace:
            if op['op'] == 'REVERT':
                revert_op = op
                break
                
        if not revert_op:
            print("No REVERT operation found in trace")
            return None
            
        # Находим вызов, который привел к реверту
        call_op = None
        revert_depth = revert_op.get('depth', 0)
        target_depth = revert_depth - 1  # Ищем вызов с глубиной на 1 меньше
        
        for op in trace:
            if (op['op'] in ['CALL', 'DELEGATECALL', 'STATICCALL'] and 
                op.get('depth', 0) == target_depth):
                call_op = op
                break
                
        if not call_op:
            print(f"No matching call found for REVERT at depth {revert_depth} (looking for call at depth {target_depth})")
            return None
                
        return {
            'revert': revert_op,
            'call': call_op,
            'trace': trace
        }
    except FileNotFoundError:
        print("Error: cleaned_trace.json not found")
        return None
    except json.JSONDecodeError:
        print("Error: Invalid JSON in cleaned_trace.json")
        return None

def analyze_revert(revert_info):
    """Анализирует реверт с помощью Gemini"""
    if not revert_info:
        return "No revert information found"
        
    revert_op = revert_info['revert']
    call_op = revert_info['call']
    
    # Получаем адрес контракта
    contract_address = call_op['args']['to']
    
    # Формируем более компактный промпт
    prompt = f"""Analyze this transaction revert:

Contract: {contract_address}
Revert Depth: {revert_op.get('depth', 0)}
Gas Remaining: {revert_op.get('gas', 0)}
Input Data: {call_op.get('args', {}).get('input', '')}

Please analyze:
1. What caused the revert?
2. What was the sequence of calls leading to it?
3. What specific operation failed?
4. How could this have been prevented?

Provide a clear, concise analysis in English."""

    try:
        # Configure model with timeout
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        return f"Error analyzing revert: {str(e)}"

def main():
    # Получаем информацию о реверте
    revert_info = get_revert_info()
    if not revert_info:
        print("Failed to get revert information")
        return
        
    # Анализируем реверт
    analysis = analyze_revert(revert_info)
    
    # Сохраняем результат
    with open('revert_analysis.txt', 'w') as f:
        f.write(analysis)
        
    print("Analysis completed and saved to revert_analysis.txt")

if __name__ == "__main__":
    main() 