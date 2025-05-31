import json
import sys
import requests
import time
import traceback
from process_traces import process_struct_logs

def get_trace_call(params):
    """
    Получает трейс через debug_traceCall
    """
    try:
        # Формируем параметры для debug_traceCall
        trace_params = {
            'jsonrpc': '2.0',
            'method': 'debug_traceCall',
            'params': [
                {
                    'from': params['from'],
                    'to': params['to'],
                    'data': params['data'],
                    'value': params.get('value', '0x0')
                },
                'latest',  # block number
                {
                    "enableMemory": True,
                    "disableStack": False,
                    "disableStorage": False,
                    "enableReturnData": True
                }
            ],
            'id': 1
        }
        
        # Отправляем запрос к ноде
        response = requests.post(
            'https://mainnet.chainnodes.org/c4aa58b5-440a-4dfc-a98f-e1fcd64d17d9',
            json=trace_params,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"Error: Node returned status code {response.status_code}")
            return None
            
        result = response.json()
        if 'error' in result:
            print(f"Error from node: {result['error']}")
            return None
            
        return result.get('result')
        
    except Exception as e:
        print(f"Error getting trace: {str(e)}")
        traceback.print_exc()
        return None

def main():
    try:
        # Получаем параметры из stdin
        params = json.loads(sys.argv[1])
        
        # Получаем трейс
        trace = get_trace_call(params)
        if not trace:
            sys.exit(1)
            
        # Обрабатываем трейс используя функцию из process_traces.py
        processed_trace = process_struct_logs(trace['structLogs'])
        if not processed_trace:
            sys.exit(1)
            
        # Сохраняем результат
        with open('cleaned_trace.json', 'w') as f:
            json.dump(processed_trace, f, indent=2)
            
    except Exception as e:
        print(f"Error in main: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 