import json
import sys
import traceback
from process_traces import process_trace as get_trace

def clean_trace_to_first_revert(trace_data):
    """
    Очищает трейс до первого REVERT
    """
    try:
        # Находим первый REVERT
        revert_index = None
        for i, op in enumerate(trace_data):
            if op['op'] == 'REVERT':
                revert_index = i
                break
                
        if revert_index is None:
            print("No REVERT operation found in trace")
            return None
            
        # Находим CALL, который привел к REVERT
        call_index = None
        for i in range(revert_index, -1, -1):
            if trace_data[i]['op'] == 'CALL':
                call_index = i
                break
                
        if call_index is None:
            print("No matching CALL operation found for REVERT")
            return None
            
        # Возвращаем часть трейса от CALL до REVERT
        return trace_data[call_index:revert_index + 1]
    except Exception as e:
        print(f"Error in clean_trace_to_first_revert: {str(e)}")
        traceback.print_exc()
        return None

def clean_trace(trace_data):
    """
    Очищает трейс и возвращает результат
    """
    try:
        cleaned_trace = clean_trace_to_first_revert(trace_data)
        if cleaned_trace:
            # Сохраняем очищенный трейс
            with open('cleaned_trace.json', 'w') as f:
                json.dump(cleaned_trace, f, indent=2)
            print("Cleaned trace saved to cleaned_trace.json")
            return cleaned_trace
        return None
    except Exception as e:
        print(f"Error in clean_trace: {str(e)}")
        traceback.print_exc()
        return None

def main():
    try:
        # Читаем трейс из файла
        print("Reading trace from cleaned_trace.json...")
        with open('cleaned_trace.json', 'r') as f:
            trace_data = json.load(f)
            
        # Очищаем трейс
        print("Cleaning trace...")
        cleaned_trace = clean_trace(trace_data)
        
        if not cleaned_trace:
            print("Error: Failed to clean trace")
            sys.exit(1)
            
        print("Success!")
        
    except FileNotFoundError:
        print("Error: cleaned_trace.json not found")
        sys.exit(1)
    except json.JSONDecodeError:
        print("Error: Invalid JSON in cleaned_trace.json")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 