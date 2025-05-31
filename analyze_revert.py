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

# Cache for source maps
source_map_cache = {}

def fill_missing_pc(source_map):
    """Заполняет пропущенные значения предыдущим code и context_code"""
    if not source_map:
        return source_map
        
    # Получаем все pc и сортируем их
    pcs = sorted(source_map.keys())
    if not pcs:
        return source_map
        
    # Заполняем пропуски
    result = {}
    last_code = source_map[pcs[0]].get('code', '')
    last_context = source_map[pcs[0]].get('context_code', '')
    
    for i in range(pcs[0], pcs[-1] + 1):
        if i in source_map:
            last_code = source_map[i].get('code', '')
            last_context = source_map[i].get('context_code', '')
        result[i] = {
            'code': last_code,
            'context_code': last_context
        }
        
    return result

def get_source_map(contract_address):
    """Получает jsonSourceMap для контракта"""
    # Check cache first
    if contract_address in source_map_cache:
        print(f"Using cached source map for {contract_address}")
        return source_map_cache[contract_address]
        
    try:
        print(f"Fetching source map for contract: {contract_address}")
        response = requests.post(
            'http://205.196.81.76:5000/verify',
            headers={'Content-Type': 'application/json'},
            json={'address': contract_address},
            timeout=5  # Add timeout
        )
        response.raise_for_status()
        # Преобразуем список словарей в словарь с ключами pc
        source_map_list = response.json().get('jsonSourceMap', [])
        source_map = {
            item['pc']: {
                'code': item.get('code', '')[:512] if len(item.get('code', '')) < 512 else '',  # Reduce size
                'context_code': item.get('context_code', '')[:512] if len(item.get('context_code', '')) < 512 else ''  # Reduce size
            } for item in source_map_list
        }
        # Cache the result
        source_map_cache[contract_address] = source_map
        return source_map
    except Exception as e:
        print(f"Error fetching source map: {e}")
        return {}

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
            
        # Находим первый CALL для получения адреса контракта
        first_call = None
        for op in trace:
            if op['op'] in ['CALL', 'DELEGATECALL', 'STATICCALL']:
                first_call = op
                break
                
        if first_call:
            # Получаем адрес контракта из первого вызова
            contract_address = first_call['args']['to']
            print(f"Fetching source map for contract: {contract_address}")
            
            # Получаем source map и обновляем trace
            source_map = get_source_map(contract_address)
            trace = update_trace_with_source_map(trace, source_map)
            
            # Сохраняем обновленный trace
            with open('cleaned_trace.json', 'w') as f:
                json.dump(trace, f, indent=2)
            
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