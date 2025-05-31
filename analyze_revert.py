import json
import google.generativeai as genai
import os
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Configure API key from environment variable
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

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
    try:
        response = requests.post(
            'http://205.196.81.76:5000/verify',
            headers={'Content-Type': 'application/json'},
            json={'address': contract_address}
        )
        response.raise_for_status()
        # Преобразуем список словарей в словарь с ключами pc
        source_map_list = response.json().get('jsonSourceMap', [])
        source_map = {
            item['pc']: {
                'code': item.get('code', '')[:1024] if len(item.get('code', '')) < 1024 else '',
                'context_code': item.get('context_code', '')[:1024] if len(item.get('context_code', '')) < 1024 else ''
            } for item in source_map_list
        }
        # Заполняем пропущенные значения
        return fill_missing_pc(source_map)
    except Exception as e:
        print(f"Error fetching source map: {e}")
        return {}

def update_trace_with_source_map(trace, source_map):
    """Обновляет trace данными из source_map по pc"""
    for op in trace:
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
    
    # Формируем промпт
    prompt = f"""Analyze the transaction revert using EVM trace. Follow this algorithm and provide response in Russian:

## 1. STRUCTURAL ANALYSIS
- Find the revert point (last REVERT opcode)
- Determine the call depth where revert occurred
- Trace the sequence of calls to the error point
- Record the program counter (PC) at revert

## 2. REVERT CONTEXT
- What data was passed in the last call?
- How much gas remained? (check for out of gas)
- Is there an error message? If not - it's a low-level error
- What values were on the stack before revert?
- What was the PC at revert?

## 3. FUNCTION CALL ANALYSIS
**Function Selector Analysis:**
- Extract first 4 bytes from input_data - this is function selector
- Check for CALLDATALOAD(0) operations - loading function selector
- Find comparison operations (EQ) with function selector
- Look for pattern: CALLDATALOAD → DIV/SHR → EQ → JUMPI

**Typical missing method patterns:**
- Series of EQ operations with different selectors, all returning false
- Final JUMP to fallback function or invalid opcode
- Revert at the start of execution without entering specific function
- PC points to function dispatcher code

## 4. CHECK COMMON CAUSES
**A. External Calls:**
- CALL/DELEGATECALL to EOA with data (address code = "0x")
- CALL to contract with non-existent method
- Incorrect call parameters (insufficient data)
- Expected vs actual return data
- Wrong function selector in input_data

**B. Computations:**
- Arithmetic overflow/underflow
- Division by zero
- Array bounds violation
- Invalid operations with zero values

**C. Conditions and Checks:**
- require() with specific condition
- assert() for critical errors
- Permission/balance checks
- Owner/access control checks
- Slippage protection in DEX
- Collateral ratio in lending protocols

**D. Gas:**
- Out of gas
- Insufficient gas for subcall
- Gas exhausted mid-execution

**E. Contract State:**
- Contract in paused state
- Incorrect initialization
- Outdated proxy/implementation addresses

## 5. DETAILED OPERATION ANALYSIS
For each operation before revert, check:

**Storage Operations (SLOAD/SSTORE):**
- Which slots are read/written?
- Are storage values correct?
- Are there flag check patterns (isPaused, isActive)?

**Arithmetic Operations:**
- ADD/SUB/MUL/DIV: are input values correct?
- Can overflow/underflow occur?
- Are values checked for zero before division?

**CALL Operations:**
- Is target address a contract? (eth_getCode != "0x")
- Is function selector in data correct?
- Is there enough gas for the call?
- Is return data of expected size?

**Logical Operations:**
- EQ/LT/GT: what is being compared?
- ISZERO: existence/validity check?
- AND/OR: bit masks and flags?

## 6. PROTOCOL-SPECIFIC CHECKS

**ERC20/ERC721:**
- Sufficient allowance for transferFrom?
- Sufficient balance for sender?
- Does token exist (for NFT)?

**DEX (Uniswap, Curve, etc.):**
- Slippage tolerance not exceeded?
- Sufficient liquidity in pool?
- Transaction deadline not expired?
- Correct token addresses?

**Lending (Aave, Compound):**
- Health factor above liquidation threshold?
- Sufficient collateral for loan?
- Borrowing caps not exceeded?
- Oracle prices up to date?

**Proxy Contracts:**
- Implementation address up to date?
- Proxy correctly configured?
- Storage layouts match?

## 7. SPECIFIC ERROR INDICATORS

**Missing Method in Contract:**
- Revert at start of execution (low PC)
- Series of failed EQ selector comparisons
- Jump to fallback function
- Input data contains valid selector but method not found

**EOA Instead of Contract:**
- CALL technically successful (success = true)
- Return data empty but expected
- ret_size > 0 in CALL parameters

**Insufficient Permissions:**
- Revert in ERC20.transferFrom
- Messages like "insufficient allowance"

**Out of Gas:**
- Gas near zero at revert
- Complex calculations or loops before error

## 8. ERROR MESSAGE ANALYSIS
- Empty message ("") = low-level error
- Specific text = require() with message
- Hex data = encoded error or revert reason

## 9. FINAL DIAGNOSIS
Determine root cause:
1. WHAT exactly went wrong?
2. WHY did it lead to revert?
3. HOW could it have been prevented?
4. WHAT data or state was incorrect?

## 10. FIX RECOMMENDATIONS
- Specific steps to fix the issue
- Checks to perform before retrying
- Alternative approaches if main method unavailable

Transaction Data:
Call Type: {call_op['op']}
Contract Address: {contract_address}
Call Data: {call_op['args'].get('input', '')}
Value: {call_op['args'].get('value', '0')}
Gas: {call_op.get('gas', '0')}
Gas Cost: {call_op.get('gasCost', '0')}

Revert Data: {revert_op.get('result', '')}
Revert Gas: {revert_op.get('gas', '0')}
Revert Gas Cost: {revert_op.get('gasCost', '0')}

Trace Context:
{json.dumps(revert_info['trace'], indent=2)}

Provide a detailed technical analysis following the above structure. Always include contract addresses in your explanations."""

    try:
        # Инициализируем модель
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Получаем ответ
        response = model.generate_content(prompt)
        
        return response.text
        
    except Exception as e:
        return f"Error analyzing revert: {str(e)}"

def main():
    # Получаем информацию о реверте
    revert_info = get_revert_info()
    
    if revert_info:
        # Анализируем реверт
        analysis = analyze_revert(revert_info)
        
        # Сохраняем результат
        with open('revert_analysis.txt', 'w') as f:
            f.write(analysis)
            
        print("\nAnalysis saved to revert_analysis.txt")
    else:
        print("\nNo revert information found")

if __name__ == "__main__":
    main() 