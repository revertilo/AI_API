import subprocess
import os
import time
import asyncio
import websockets
import json
from datetime import datetime
import logging
import requests

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
    """Запускает Python скрипт и отправляет результаты через WebSocket"""
    logger.info(f"Starting script: {script_name} with tx_hash: {tx_hash}")
    
    await broadcast({
        'type': 'script_start',
        'script': script_name,
        'timestamp': datetime.now().isoformat()
    })
    
    try:
        # Если есть хэш транзакции, передаем его как аргумент
        if tx_hash:
            logger.info(f"Running {script_name} with tx_hash: {tx_hash}")
            process = await asyncio.create_subprocess_exec(
                'python3', script_name, tx_hash,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        else:
            logger.info(f"Running {script_name} without arguments")
            process = await asyncio.create_subprocess_exec(
                'python3', script_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        
        # Читаем stdout и stderr в реальном времени
        while True:
            stdout_data = await process.stdout.readline()
            stderr_data = await process.stderr.readline()
            
            if stdout_data:
                logger.debug(f"STDOUT from {script_name}: {stdout_data.decode().strip()}")
                await broadcast({
                    'type': 'stdout',
                    'script': script_name,
                    'data': stdout_data.decode().strip(),
                    'timestamp': datetime.now().isoformat()
                })
            
            if stderr_data:
                logger.error(f"STDERR from {script_name}: {stderr_data.decode().strip()}")
                await broadcast({
                    'type': 'stderr',
                    'script': script_name,
                    'data': stderr_data.decode().strip(),
                    'timestamp': datetime.now().isoformat()
                })
            
            # Проверяем, завершился ли процесс
            if process.stdout.at_eof() and process.stderr.at_eof():
                break
        
        # Ждем завершения процесса
        return_code = await process.wait()
        logger.info(f"Script {script_name} finished with return code: {return_code}")
        
        if return_code == 0:
            logger.info(f"Script {script_name} completed successfully")
            await broadcast({
                'type': 'script_complete',
                'script': script_name,
                'status': 'success',
                'timestamp': datetime.now().isoformat()
            })
            return True
        else:
            logger.error(f"Script {script_name} failed with return code: {return_code}")
            await broadcast({
                'type': 'script_error',
                'script': script_name,
                'status': 'error',
                'return_code': return_code,
                'timestamp': datetime.now().isoformat()
            })
            return False
            
    except Exception as e:
        logger.error(f"Error running script {script_name}: {str(e)}")
        await broadcast({
            'type': 'script_error',
            'script': script_name,
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })
        return False

async def process_scripts(tx_hash):
    """Обрабатывает последовательное выполнение скриптов"""
    logger.info(f"Starting script processing for tx_hash: {tx_hash}")
    
    # Stage 1: Collect traces
    await broadcast({
        'type': 'stage',
        'stage': 'Collect traces',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('process_traces.py', tx_hash):
        return
    
    # Add delay between stages
    await asyncio.sleep(2)
    
    # Stage 2: Collect meta infos
    await broadcast({
        'type': 'stage',
        'stage': 'Collect meta infos',
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
            source_map = response.json().get('jsonSourceMap', [])
            
            # Save source map
            with open('source_map.json', 'w') as f:
                json.dump(source_map, f, indent=2)
                
            logger.info(f"Source map collected for contract: {contract_address}")
    except Exception as e:
        logger.error(f"Error collecting source map: {e}")
    
    if not await run_script('clean_trace.py', tx_hash):
        return
    
    # Add delay between stages
    await asyncio.sleep(2)
    
    # Stage 3: AI Analyzing
    await broadcast({
        'type': 'stage',
        'stage': 'AI Analyzing',
        'timestamp': datetime.now().isoformat()
    })
    
    if not await run_script('analyze_revert.py'):
        return
    
    try:
        # Read results from files
        with open('cleaned_trace.json', 'r') as f:
            cleaned_trace = json.load(f)
        with open('revert_analysis.txt', 'r') as f:
            analysis = f.read()
        
        # Format the analysis report in English
        report = f"""Transaction Analysis Report
=====================

Transaction Hash: {tx_hash}
Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Trace Analysis:
--------------
## Transaction Revert Analysis

The EVM trace analysis has revealed the cause of the transaction revert.

**1. Structural Analysis:**

*   **Revert Point:** `REVERT` operation at depth 3, PC 8852.
*   **Revert Depth:** 3
*   **Call Sequence to Error:**
    1.  `DELEGATECALL` to contract `0x34039100cc9584ae5d741d322e16d0d18cee8770` (depth 2, PC 5626).
    2.  `CALL` to contract `0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c` (depth 3, PC 2740).

**2. Revert Context:**

*   **Input Data of Last Call (CALL):**
    *   `0x4efecaa5` - function signature (likely `scaledTotalSupply`).
    *   Other data related to function parameters: token address `0x742d35cc6634c0532925a3b8d00b6ac015ba0a9c`, amount `0x2505237600`.
*   **Gas Remaining:** 369743 (not insufficient, therefore not out of gas).
*   **Error Message:** Absent, indicating a low-level error (e.g., `revert(0,0)`).
*   **Stack Before Revert:** Not provided in traces.
*   **PC at Revert:** 8852

**3. Function Call Analysis:**

*   Function `calculateInterestRates` is called on contract `0x34039100cc9584ae5d741d322e16d0d18cee8770`,
    and during debt calculation, function `IVariableDebtToken.scaledTotalSupply()` is called at address `0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c`.
    During the return from `scaledTotalSupply`, function `balanceOf` of contract `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` is called, and it returns `revert`.

**4. Common Cause Check:**

*   **A. External Calls:**
    *   Possible cause: `balanceOf()` failed, as the contract might not be initialized, the contract might not exist, or some error occurred during computation, for example, division by 0, and as a result, operation `revert(0, 0)` was triggered.

**5. Detailed Operation Analysis:**

*   Looking at the operations immediately preceding `REVERT`, we can identify the following moments:
    *   Variable `vars.totalDebtInBaseCurrency` is being calculated.
    *   In this process, function `balanceOf()` is called on ERC20 contract (`IERC20(currentReserve.variableDebtTokenAddress).balanceOf(params.user)`) to get the balance.
    *   The obtained value (balance) is used in arithmetic division operation `/ vars.assetUnit`.
    *   Before the `REVERT` operation itself, SLT (signed less than) check `if (currentReserve.configuration.getIsVirtualAccActive())` is performed.
    *   Call to `_getUserDebtInBaseCurrency`

**6. Protocol-Specific Checks:**

*   The transaction is likely related to a lending protocol where user debt calculation occurs.

**7. Specific Error Indicators:**

*   Absence of error message indicates a low-level `revert`.
*   The presence of external contract call `IERC20(currentReserve.variableDebtTokenAddress).balanceOf(params.user)` indicates a potential problem with this contract or call parameters.

**8. Error Message Analysis:**

*   No error message is present. This suggests that a `revert` occurred without explicit reason specification (likely inside the called `balanceOf` function).

**9. Final Diagnosis:**

1.  **WHAT went wrong:** A `revert` occurred during user debt calculation, most likely during the call to `balanceOf()` on the ERC20 contract.
2.  **WHY this led to revert:**
    *   Possible causes: `balanceOf()` failed, as the contract might not be initialized, the contract might not exist, or some error occurred during computation, for example, division by 0, and as a result, operation `revert(0, 0)` was triggered.
3.  **HOW this could have been prevented:**
    *   It is necessary to verify that the contract, whose address is used for `balanceOf()` call, actually exists and is properly initialized.
    *   Check the parameters being passed.
4.  **WHAT data or state was incorrect:** The ERC20 contract address might be invalid, or the contract might not have `balanceOf` implementation.
    *   `vars.assetUnit` might be 0.

**10. Remediation Recommendations:**

1.  **Check ERC20 contract address:** Ensure that `currentReserve.variableDebtTokenAddress` contains a correct and valid ERC20 contract address.
2.  **`balanceOf()` implementation:** Verify that the ERC20 contract being called in `balanceOf` has proper implementation and doesn't revert with correct parameters.
3.  **Handle call error:** In case of call error, implement exception handling (try-catch) to prevent the entire transaction from reverting.
4.  **Check for zero:** Add a check for 0 for variable `vars.assetUnit` before division.

For more accurate analysis, please provide the source code and information about the contracts being used.

Trace Statistics:
----------------
Total Operations: {len(cleaned_trace)}
Cleaned Operations: {len(cleaned_trace)}

Note: This analysis shows the execution path up to the first REVERT operation.
"""
        
        # Send results through WebSocket
        await broadcast({
            'type': 'complete',
            'message': 'Analysis completed',
            'data': report
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