import json
import os

total_input = 0
total_output = 0
total_tokens = 0
total_cost = 0
message_count = 0

# 遍历所有会话文件
sessions_dir = '/Users/liuyilin/.openclaw/agents/main/sessions'
if os.path.exists(sessions_dir):
    for filename in os.listdir(sessions_dir):
        if filename.endswith('.jsonl'):
            filepath = os.path.join(sessions_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            if data.get('type') == 'message' and 'message' in data:
                                msg = data['message']
                                if 'usage' in msg:
                                    usage = msg['usage']
                                    total_input += usage.get('input', 0)
                                    total_output += usage.get('output', 0)
                                    total_tokens += usage.get('totalTokens', 0)
                                    
                                    cost = usage.get('cost', {})
                                    if isinstance(cost, dict):
                                        total_cost += cost.get('total', 0)
                                    message_count += 1
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                continue

print(f'消息数量: {message_count}')
print(f'输入 tokens: {total_input:,}')
print(f'输出 tokens: {total_output:,}')
print(f'总 tokens: {total_tokens:,}')
print(f'总成本: ${total_cost:.4f}')
if message_count > 0:
    print(f'平均每条消息 tokens: {total_tokens//message_count:,}')
else:
    print('平均每条消息 tokens: 0')