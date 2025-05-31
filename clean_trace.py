import json
import sys
import traceback
from process_traces import process_trace as get_trace

def clean_trace_to_first_revert(trace):
    """
    Очищает трассу до первого реверта.
    Находит первый REVERT и вызов, который к нему привел.
    """
    try:
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
    except Exception as e:
        print(f"Error in clean_trace_to_first_revert: {str(e)}")
        print("Trace:", traceback.format_exc())
        return None

def clean_trace(trace_data):
    """
    Очищает трейс до первого реверта
    """
    try:
        cleaned = clean_trace_to_first_revert(trace_data)
        if cleaned is None:
            print("Error: Failed to clean trace")
            return None
        return cleaned
    except Exception as e:
        print(f"Error in clean_trace: {str(e)}")
        print("Trace:", traceback.format_exc())
        return None

def clean_transaction_trace(tx_hash):
    """
    Обрабатывает трейс транзакции и возвращает очищенный результат
    """
    try:
        # Получаем трейс из process_traces
        print(f"Getting trace for transaction: {tx_hash}")
        trace_data = get_trace(tx_hash)
        if not trace_data:
            print("Error: Could not get transaction trace")
            return None
            
        # Очищаем трейс
        print("Cleaning trace...")
        cleaned_trace = clean_trace(trace_data)
        if not cleaned_trace:
            print("Error: Failed to clean trace")
            return None
        
        # Сохраняем результат
        print("Saving cleaned trace...")
        with open('cleaned_trace.json', 'w') as f:
            json.dump(cleaned_trace, f, indent=2)
            
        print(f"Successfully cleaned trace. Saved {len(cleaned_trace)} operations.")
        return cleaned_trace
    except Exception as e:
        print(f"Error in clean_transaction_trace: {str(e)}")
        print("Trace:", traceback.format_exc())
        return None

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 clean_trace.py <tx_hash>")
        sys.exit(1)
        
    tx_hash = sys.argv[1]
    print(f"Processing transaction: {tx_hash}")
    result = clean_transaction_trace(tx_hash)
    if not result:
        print("Error: Failed to process transaction")
        sys.exit(1)
    print("Success!")

if __name__ == "__main__":
    main() 