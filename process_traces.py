import requests
import json
import sys

# Словарь с описанием опкодов и их аргументов
OPCODES = {
    'ADD': {'name': 'ADD', 'args': ['a', 'b']},
    'MUL': {'name': 'MUL', 'args': ['a', 'b']},
    'SUB': {'name': 'SUB', 'args': ['a', 'b']},
    'DIV': {'name': 'DIV', 'args': ['a', 'b']},
    'MOD': {'name': 'MOD', 'args': ['a', 'b']},
    'LT': {'name': 'LT', 'args': ['a', 'b']},
    'GT': {'name': 'GT', 'args': ['a', 'b']},
    'SLT': {'name': 'SLT', 'args': ['a', 'b']},
    'SGT': {'name': 'SGT', 'args': ['a', 'b']},
    'EQ': {'name': 'EQ', 'args': ['a', 'b']},
    'ISZERO': {'name': 'ISZERO', 'args': ['a']},
    'REVERT': {'name': 'REVERT', 'args': ['offset', 'size']},
    'JUMPI': {'name': 'JUMPI', 'args': ['counter', 'condition']},
    'JUMP': {'name': 'JUMP', 'args': ['destination']},
    'CALLDATALOAD': {'name': 'CALLDATALOAD', 'args': ['offset']},
    'CALLDATASIZE': {'name': 'CALLDATASIZE', 'args': []},
    'SLOAD': {'name': 'SLOAD', 'args': ['key']},
    'SSTORE': {'name': 'SSTORE', 'args': ['key', 'value']},
    'CALL': {'name': 'CALL', 'args': ['gas', 'to', 'value', 'in_offset', 'in_size']},
    'DELEGATECALL': {'name': 'DELEGATECALL', 'args': ['gas', 'to', 'in_offset', 'in_size']},
    'STATICCALL': {'name': 'STATICCALL', 'args': ['gas', 'to', 'in_offset', 'in_size']},
    'CALLCODE': {'name': 'CALLCODE', 'args': ['gas', 'to', 'value', 'in_offset', 'in_size']},
    'RETURN': {'name': 'RETURN', 'args': ['offset', 'size']},
}

def get_transaction_trace(tx_hash):
    """
    Получает трейс транзакции через debug_traceTransaction
    """
    url = "https://mainnet.chainnodes.org/c4aa58b5-440a-4dfc-a98f-e1fcd64d17d9"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "method": "debug_traceTransaction",
        "params": [
            tx_hash,
            {
                "enableMemory": True,
                "disableStack": False,
                "disableStorage": False,
                "enableReturnData": True
            }
        ],
        "id": 1,
        "jsonrpc": "2.0"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}")
        return None

def get_transaction(tx_hash):
    """
    Получает данные транзакции
    """
    url = "https://mainnet.chainnodes.org/c4aa58b5-440a-4dfc-a98f-e1fcd64d17d9"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "method": "eth_getTransactionByHash",
        "params": [tx_hash],
        "id": 1,
        "jsonrpc": "2.0"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}")
        return None

def hex_to_int(hex_str):
    """Конвертирует hex строку в int"""
    if isinstance(hex_str, str) and hex_str.startswith('0x'):
        return int(hex_str, 16)
    return hex_str

def get_memory_data(memory, offset, size):
    """Извлекает данные из memory по offset и size"""
    
    offset_int = hex_to_int(offset)
    size_int = hex_to_int(size)
    
    # Объединяем все слова памяти в одну строку
    memory_str = ''.join(memory)
    
    # Извлекаем нужный фрагмент
    start_pos = offset_int * 2  # *2 потому что каждый байт представлен двумя hex символами
    end_pos = start_pos + size_int * 2
    
    data = memory_str[start_pos:end_pos]
    
    result = "0x" + data
    return result

def hex_to_utf8(hex_str):
    """Конвертирует hex строку в UTF-8"""
    if not hex_str or not hex_str.startswith('0x'):
        return ""
    try:
        # Убираем префикс 0x и конвертируем в байты
        hex_bytes = bytes.fromhex(hex_str[2:])
        # Декодируем в UTF-8
        return hex_bytes.decode('utf-8')
    except:
        return ""

def process_struct_logs(struct_logs):
    results = []
    for log in struct_logs:
        op = log.get('op')
        if op in OPCODES:
            result = {
                'op': op,
                'args': {},
                'pc': log.get('pc', 0),
                'depth': log.get('depth', 0),
                'result': '',
            }
            result['gas'] = log.get('gas', 0)
            result['gasCost'] = log.get('gasCost', 0)
            if 'stack' in log:
                stack = log['stack']
                args = OPCODES[op]['args']
                
                # Обрабатываем все опкоды
                if op in ['CALL', 'DELEGATECALL', 'STATICCALL', 'CALLCODE']:
                    # Стек для CALL: [retSize, retOffset, argsSize, argsOffset, value, address, gas]
                    # Для DELEGATECALL/STATICCALL/CALLCODE: [retSize, retOffset, argsSize, argsOffset, address, gas]
                    if op == 'CALL':
                        result['args']['gas'] = stack[-1]
                        result['args']['to'] = "0x" + stack[-2][2:].zfill(40)
                        result['args']['value'] = stack[-3]
                        result['args']['in_offset'] = stack[-4]
                        result['args']['in_size'] = stack[-5]
                        result['args']['ret_offset'] = stack[-6]
                        result['args']['ret_size'] = stack[-7]
                    else:
                        result['args']['gas'] = stack[-1]
                        result['args']['to'] = "0x" + stack[-2][2:].zfill(40)
                        result['args']['in_offset'] = stack[-3]
                        result['args']['in_size'] = stack[-4]
                        result['args']['ret_offset'] = stack[-5]
                        result['args']['ret_size'] = stack[-6]
                    result['args']['input_data'] = get_memory_data(log.get('memory', []), result['args']['in_offset'], result['args']['in_size'])
                
                elif op == 'REVERT':
                    offset = hex_to_int(stack[-1])  # Первый элемент стека
                    size = hex_to_int(stack[-2])    # Второй элемент стека
                    hex_full = get_memory_data(log.get('memory', []), offset, size)
                    result['message_hex'] = hex_full
                    result['message'] = hex_to_utf8(hex_full)
                    result['args']['offset'] = stack[-1]
                    result['args']['size'] = stack[-2]
                
                else:
                    # Для всех остальных опкодов берем аргументы в правильном порядке
                    # В стеке аргументы лежат в обратном порядке: [b, a]
                    for i, arg in enumerate(args):
                        if i < len(stack):
                            result['args'][arg] = stack[-(i+1)]
                    
                    # Вычисляем результат для логических операций
                    if op == 'GT':
                        result['result'] = hex_to_int(result['args']['a']) > hex_to_int(result['args']['b'])
                    elif op == 'LT':
                        result['result'] = hex_to_int(result['args']['a']) < hex_to_int(result['args']['b'])
                    elif op == 'EQ':
                        result['result'] = hex_to_int(result['args']['a']) == hex_to_int(result['args']['b'])
                    elif op == 'ISZERO':
                        result['result'] = hex_to_int(result['args']['a']) == 0
            results.append(result)
    return results

def process_trace(tx_hash):
    """
    Обрабатывает трейс транзакции и возвращает результаты
    """
    # Получаем данные транзакции
    tx_data = get_transaction(tx_hash)
    if not tx_data or 'result' not in tx_data:
        print("Error: Could not get transaction data")
        return None
    
    tx = tx_data['result']
    
    # Получаем трейс
    trace_data = get_transaction_trace(tx_hash)
    if not trace_data or 'result' not in trace_data:
        print("Error: Could not get transaction trace")
        return None
        
    # Обрабатываем трейс
    struct_logs = trace_data['result']['structLogs']
    results = process_struct_logs(struct_logs)
    
    # Добавляем первый CALL из транзакции в начало трейса
    first_call = {
        'op': 'CALL',
        'args': {
            'from': tx['from'],
            'to': tx['to'],
            'value': tx['value'],
            'input_data': tx['input']
        },
        'pc': 0,
        'depth': 0,
        'gas': 0,
        'gasCost': 0
    }
    results.insert(0, first_call)
    
    # Сохраняем результаты в cleaned_trace.json
    with open('cleaned_trace.json', 'w') as f:
        json.dump(results, f, indent=2)
        
    print(f"Trace saved to cleaned_trace.json")
    return results

def main():
    # Получаем хэш транзакции из аргументов командной строки
    if len(sys.argv) != 2:
        print("Usage: python3 process_traces.py <tx_hash>")
        sys.exit(1)
        
    tx_hash = sys.argv[1]
    print(f"Processing transaction: {tx_hash}")
    
    results = process_trace(tx_hash)
    if not results:
        print("Error: Failed to process transaction")
        sys.exit(1)
        
    print("Success!")

if __name__ == "__main__":
    main() 