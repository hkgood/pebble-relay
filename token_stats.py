import json
import os
from datetime import datetime, timedelta

# 获取本周的日期范围（假设周日是一周的开始）
today = datetime.now()
start_of_week = today - timedelta(days=today.weekday() + 1)  # 本周一
end_of_week = start_of_week + timedelta(days=6)  # 本周日

print(f'统计周期: {start_of_week.strftime("%Y-%m-%d")} 到 {end_of_week.strftime("%Y-%m-%d")}')

total_input = 0
total_output = 0
total_cache_read = 0
total_cache_write = 0
total_tokens = 0
total_cost = 0
session_count = 0

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
                                    timestamp = data.get('timestamp', '')
                                    
                                    # 检查时间是否在本周内
                                    if timestamp:
                                        try:
                                            msg_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                            if start_of_week <= msg_time <= end_of_week:
                                                total_input += usage.get('input', 0)
                                                total_output += usage.get('output', 0)
                                                total_cache_read += usage.get('cacheRead', 0)
                                                total_cache_write += usage.get('cacheWrite', 0)
                                                total_tokens += usage.get('totalTokens', 0)
                                                
                                                cost = usage.get('cost', {})
                                                if isinstance(cost, dict):
                                                    total_cost += cost.get('total', 0)
                                                session_count += 1
                                        except:
                                            pass
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                continue

print(f'会话数量: {session_count}')
print(f'输入 tokens: {total_input:,}')
print(f'输出 tokens: {total_output:,}')
print(f'缓存读取 tokens: {total_cache_read:,}')
print(f'缓存写入 tokens: {total_cache_write:,}')
print(f'总 tokens: {total_tokens:,}')
print(f'总成本: ${total_cost:.4f}')
if session_count > 0:
    print(f'平均每次会话 tokens: {total_tokens//session_count:,}')
else:
    print('平均每次会话 tokens: 0')