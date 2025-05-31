import json
from process_traces import process_trace

def clean_trace_to_first_revert(trace):
    """
    Очищает трассу до первого реверта.
    Находит первый REVERT и вызов, который к нему привел.
    """
    
    # Найти первый REVERT
    first_revert_index = None
    for i, op in enumerate(trace):
        if op.get('op') == 'REVERT':
            first_revert_index = i
            break
    
    if first_revert_index is None:
        print("REVERT не найден")
        return trace
    
    revert_depth = trace[first_revert_index].get('depth', 0)
    target_depth = revert_depth - 1
    
    # Найти вызов, который привел к реверту
    call_index = None
    for i in range(first_revert_index - 1, -1, -1):
        op = trace[i]
        if (op.get('op') in ['CALL', 'DELEGATECALL', 'STATICCALL'] and 
            op.get('depth', 0) == target_depth):
            call_index = i
            break
    
    # Если не нашли вызов, берем начало
    if call_index is None:
        call_index = 0
    
    return trace[call_index:]

def process_trace(trace_data):
    cleaned = clean_trace_to_first_revert(trace_data)
    return cleaned

def clean_transaction_trace(tx_hash):
    """
    Обрабатывает трейс транзакции и возвращает очищенный результат
    """
    # Получаем трейс из process_traces
    trace_data = process_trace(tx_hash)
    if not trace_data:
        return None
        
    # Очищаем трейс
    cleaned_trace = process_trace(trace_data)
    
    # Сохраняем результат
    with open('cleaned_trace.json', 'w') as f:
        json.dump(cleaned_trace, f, indent=2)
        
    return cleaned_trace

def main():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python3 clean_trace.py <tx_hash>")
        sys.exit(1)
        
    tx_hash = sys.argv[1]
    clean_transaction_trace(tx_hash)

if __name__ == "__main__":
    main() 