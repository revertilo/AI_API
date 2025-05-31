import subprocess
import os
import time
import asyncio
import websockets
import json
from datetime import datetime
import logging
import requests
import traceback

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Глобальная переменная для хранения активных подключений
connected_clients = set()

async def register(websocket):
    """Регистрирует новое подключение"""
    logger.info(f"Registering new connection. Total connections: {len(connected_clients)}")
    connected_clients.add(websocket)
    try:
        # Убираем wait_closed, так как он блокирует обработку сообщений
        return websocket
    except Exception as e:
        logger.error(f"Error in register: {e}")
        connected_clients.remove(websocket)
        raise

async def broadcast(message):
    """Отправляет сообщение всем подключенным клиентам"""
    logger.info(f"Broadcasting message to {len(connected_clients)} clients: {message}")
    if connected_clients:
        try:
            await asyncio.gather(
                *[client.send(json.dumps(message)) for client in connected_clients]
            )
            logger.info("Message broadcasted successfully")
        except Exception as e:
            logger.error(f"Error broadcasting message: {e}")
    else:
        logger.warning("No connected clients to broadcast to")

async def send_to_api(data):
    """Отправляет данные на API"""
    try:
        response = requests.post('http://localhost:3000/api/analysis', json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        logger.error("Could not connect to API server. Make sure it's running on port 3000")
        return {
            'status': 'error',
            'message': 'API server is not available. Please start the API server first.',
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error sending data to API: {e}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }

async def run_script(script_name, tx_hash=None):
    """Запускает скрипт с переданным хэшем транзакции"""
    try:
        # Формируем команду для запуска скрипта
        cmd = ['python3', '-Xfrozen_modules=off', script_name]
        if tx_hash:
            cmd.append(tx_hash)
            
        logger.info(f"Running command: {' '.join(cmd)}")
            
        # Запускаем процесс
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Читаем stdout и stderr в реальном времени
        while True:
            stdout_data = await process.stdout.read(1024)
            stderr_data = await process.stderr.read(1024)
            
            if not stdout_data and not stderr_data:
                break
                
            if stdout_data:
                message = stdout_data.decode().strip()
                if message:
                    logger.info(f"STDOUT from {script_name}: {message}")
                    await broadcast({
                        'type': 'stdout',
                        'script': script_name,
                        'data': message,
                        'timestamp': datetime.now().isoformat()
                    })
                    
            if stderr_data:
                message = stderr_data.decode().strip()
                if message:
                    logger.error(f"STDERR from {script_name}: {message}")
                    await broadcast({
                        'type': 'stderr',
                        'script': script_name,
                        'data': message,
                        'timestamp': datetime.now().isoformat()
                    })
        
        # Ждем завершения процесса
        await process.wait()
        
        if process.returncode != 0:
            logger.error(f"Script {script_name} failed with return code {process.returncode}")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"Error running script {script_name}: {str(e)}")
        logger.error(traceback.format_exc())
        return False

async def process_scripts(tx_hash):
    """Обрабатывает последовательное выполнение скриптов"""
    logger.info(f"Starting script processing for tx_hash: {tx_hash}")
    
    # Stage 1: Fetching transaction traces
    await broadcast({
        'type': 'stage',
        'stage': 'Fetching transaction traces',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('process_traces.py', tx_hash):
        return
        
    # Add delay between stages
    await asyncio.sleep(1)
    
    # Stage 2: Cleaning trace
    await broadcast({
        'type': 'stage',
        'stage': 'Cleaning trace',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('clean_trace.py', tx_hash):
        return
        
    # Add delay between stages
    await asyncio.sleep(1)
    
    # Stage 3: Fetching contract metadata
    await broadcast({
        'type': 'stage',
        'stage': 'Fetching contract metadata',
        'timestamp': datetime.now().isoformat()
    })
    
    # Get contract address from cleaned_trace.json
    try:
        with open('cleaned_trace.json', 'r') as f:
            trace = json.load(f)
            
        # Find first CALL to get contract address
        contract_address = None
        for op in trace:
            if op['op'] in ['CALL', 'DELEGATECALL', 'STATICCALL']:
                contract_address = op['args']['to']
                break
                
        if contract_address:
            # Get source map for the contract
            response = requests.post(
                'http://205.196.81.76:5000/verify',
                headers={'Content-Type': 'application/json'},
                json={'address': contract_address},
                timeout=5
            )
            response.raise_for_status()
            source_map_list = response.json().get('jsonSourceMap', [])
            source_map = {
                item['pc']: {
                    'code': item.get('code', '')[:256] if len(item.get('code', '')) < 256 else '',
                    'context_code': item.get('context_code', '')[:512] if len(item.get('context_code', '')) < 512 else ''
                } for item in source_map_list
            }

            source_code_filled = {}
            current_source_code = {}

            for idx in range(max(source_map.keys())):
                if idx in source_map.keys():
                    source_code_filled[idx] = source_map[idx]
                    current_source_code = source_map[idx]
                else:
                    source_code_filled[idx] = current_source_code

            for idx, op in enumerate(trace):
                pc = op['pc']
                if pc in source_code_filled.keys():
                    trace[idx]['code'] = source_code_filled[pc]['code']
                    trace[idx]['context_code'] = source_code_filled[pc]['context_code']
                else:
                    trace[idx]['code'] = ''
                    trace[idx]['context_code'] = ''
            
            # Save updated trace
            with open('cleaned_trace.json', 'w') as f:
                json.dump(trace, f, indent=2)
                
            logger.info(f"Source map collected and trace updated for contract: {contract_address}")
    except Exception as e:
        logger.error(f"Error collecting source map: {e}")
    
    # Add delay between stages
    await asyncio.sleep(1)
    
    # Stage 4: Analyzing transaction with AI
    await broadcast({
        'type': 'stage',
        'stage': 'Analyzing transaction with AI',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('analyze_revert.py', tx_hash):
        return
    
    try:
        # Read results from files
        with open('cleaned_trace.json', 'r') as f:
            cleaned_trace = json.load(f)
        with open('revert_analysis.txt', 'r') as f:
            analysis = f.read()
        
        # Send results through WebSocket
        await broadcast({
            'type': 'complete',
            'message': 'Analysis completed',
            'data': analysis
        })
            
    except Exception as e:
        logger.error(f"Error processing results: {e}")
        await broadcast({
            'type': 'error',
            'message': f'Error processing results: {str(e)}',
            'timestamp': datetime.now().isoformat()
        })

async def process_emulation(params):
    """Обрабатывает эмуляцию транзакции"""
    logger.info(f"Starting emulation processing with params: {params}")
    
    # Stage 1: Emulating transaction
    await broadcast({
        'type': 'stage',
        'stage': 'Emulating transaction',
        'timestamp': datetime.now().isoformat()
    })
    
    # Запускаем скрипт эмуляции
    if not await run_script('emulate_trace.py', json.dumps(params)):
        return
        
    # Add delay between stages
    await asyncio.sleep(1)
    
    # Stage 2: Cleaning trace
    await broadcast({
        'type': 'stage',
        'stage': 'Cleaning trace',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('clean_trace.py', 'emulate'):
        return
        
    # Add delay between stages
    await asyncio.sleep(1)
    
    # Stage 3: Fetching contract metadata
    await broadcast({
        'type': 'stage',
        'stage': 'Fetching contract metadata',
        'timestamp': datetime.now().isoformat()
    })
    
    # Get contract address from cleaned_trace.json
    try:
        with open('cleaned_trace.json', 'r') as f:
            trace = json.load(f)
            
        # Find first CALL to get contract address
        contract_address = None
        for op in trace:
            if op['op'] in ['CALL', 'DELEGATECALL', 'STATICCALL']:
                contract_address = op['args']['to']
                break
                
        if contract_address:
            # Get source map for the contract
            response = requests.post(
                'http://205.196.81.76:5000/verify',
                headers={'Content-Type': 'application/json'},
                json={'address': contract_address},
                timeout=5
            )
            response.raise_for_status()
            source_map_list = response.json().get('jsonSourceMap', [])
            source_map = {
                item['pc']: {
                    'code': item.get('code', '')[:256] if len(item.get('code', '')) < 256 else '',
                    'context_code': item.get('context_code', '')[:512] if len(item.get('context_code', '')) < 512 else ''
                } for item in source_map_list
            }

            source_code_filled = {}
            current_source_code = {}

            for idx in range(max(source_map.keys())):
                if idx in source_map.keys():
                    source_code_filled[idx] = source_map[idx]
                    current_source_code = source_map[idx]
                else:
                    source_code_filled[idx] = current_source_code

            for idx, op in enumerate(trace):
                pc = op['pc']
                if pc in source_code_filled.keys():
                    trace[idx]['code'] = source_code_filled[pc]['code']
                    trace[idx]['context_code'] = source_code_filled[pc]['context_code']
                else:
                    trace[idx]['code'] = ''
                    trace[idx]['context_code'] = ''
            
            # Save updated trace
            with open('cleaned_trace.json', 'w') as f:
                json.dump(trace, f, indent=2)
                
            logger.info(f"Source map collected and trace updated for contract: {contract_address}")
    except Exception as e:
        logger.error(f"Error collecting source map: {e}")
    
    # Add delay between stages
    await asyncio.sleep(1)
    
    # Stage 4: Analyzing transaction with AI
    await broadcast({
        'type': 'stage',
        'stage': 'Analyzing transaction with AI',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('analyze_revert.py', 'emulate'):
        return
    
    try:
        # Read results from files
        with open('cleaned_trace.json', 'r') as f:
            cleaned_trace = json.load(f)
        with open('revert_analysis.txt', 'r') as f:
            analysis = f.read()
        
        # Send results through WebSocket
        await broadcast({
            'type': 'complete',
            'message': 'Analysis completed',
            'data': analysis
        })
            
    except Exception as e:
        logger.error(f"Error processing results: {e}")
        await broadcast({
            'type': 'error',
            'message': f'Error processing results: {str(e)}',
            'timestamp': datetime.now().isoformat()
        })

async def handler(websocket):
    """WebSocket connection handler"""
    logger.info("New WebSocket connection established")
    try:
        await register(websocket)
        logger.info("Starting message loop")
        
        async for message in websocket:
            try:
                logger.info(f"Raw message received: {message}")
                data = json.loads(message)
                logger.info(f"Parsed message data: {data}")
                
                if data.get('action') == 'start':
                    logger.info("Start action detected")
                    tx_hash = data.get('txHash')
                    logger.info(f"Processing transaction hash: {tx_hash}")
                    
                    if not tx_hash:
                        logger.error("No transaction hash provided")
                        await broadcast({
                            'type': 'error',
                            'message': 'Transaction hash not provided',
                            'timestamp': datetime.now().isoformat()
                        })
                        continue
                    
                    logger.info("Starting script processing...")
                    try:
                        await process_scripts(tx_hash)
                        logger.info("Script processing completed")
                    except Exception as e:
                        logger.error(f"Error in process_scripts: {str(e)}", exc_info=True)
                elif data.get('action') == 'emulate':
                    logger.info("Emulate action detected")
                    params = {
                        'from': data.get('from'),
                        'to': data.get('to'),
                        'data': data.get('data'),
                        'value': data.get('value')
                    }
                    
                    # Проверяем обязательные параметры
                    if not all([params['from'], params['to'], params['data']]):
                        logger.error("Missing required parameters for emulation")
                        await broadcast({
                            'type': 'error',
                            'message': 'Missing required parameters for emulation',
                            'timestamp': datetime.now().isoformat()
                        })
                        continue
                    
                    logger.info("Starting emulation processing...")
                    try:
                        await process_emulation(params)
                        logger.info("Emulation processing completed")
                    except Exception as e:
                        logger.error(f"Error in process_emulation: {str(e)}", exc_info=True)
                else:
                    logger.warning(f"Unknown action received: {data.get('action')}")
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding message: {e}", exc_info=True)
                await broadcast({
                    'type': 'error',
                    'message': 'Invalid message format',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Unexpected error in message handler: {str(e)}", exc_info=True)
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Connection closed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in handler: {str(e)}", exc_info=True)
    finally:
        logger.info("Removing connection")
        connected_clients.remove(websocket)
        logger.info(f"Remaining connections: {len(connected_clients)}")

async def main():
    """Start WebSocket server"""
    logger.info("Starting WebSocket server...")
    server = await websockets.serve(handler, '127.0.0.1', 8765)
    logger.info("WebSocket server started at ws://127.0.0.1:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main()) 